#!/usr/bin/env python3
"""
sift.py

Media intake: ffprobe facts -> classify -> rename -> move/copy into an "intake" structure.

MVP1 responsibility:
- Load configuration from TOML (default: ./config.toml)
- Validate required settings and normalize paths
- Create required folder structure (cache + tier folders under outgoing_root)

MVP1.2 additions (this change):
- Scan incoming files and run ffprobe for each file
- Cache ffprobe-derived technical metrics (resolution, codecs, bitrate, fps, HDR-ish hints, etc.)
- Use cache on subsequent runs
- Add --rescan to force a fresh scan and overwrite the cache
- Add --limit to cap how many files are probed (useful during iteration)
- Add --only-ext to restrict scanning to certain extensions (optional)

Design notes:
- Uses Python 3.11+ built-in `tomllib` (no third-party deps).
- Uses ffprobe JSON output; treats failures per-file (does not kill the whole run).
- Cache is deterministic-ish (sorted by relpath) and includes enough stats to detect changes later.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        "Python 3.11+ is required (missing tomllib). "
        "Install a newer Python or adapt the project to use a TOML dependency."
    ) from exc


# ----------------------------
# Data model
# ----------------------------


@dataclass(frozen=True)
class PathsConfig:
    incoming: Path
    outgoing_root: Path
    metadata_cache: Path


@dataclass(frozen=True)
class IOConfig:
    mode: str  # "move" | "copy"
    mkdirs: bool
    dedupe_on_collision: bool


@dataclass(frozen=True)
class FFProbeConfig:
    bin: str
    args: List[str]


@dataclass(frozen=True)
class ClassificationConfig:
    media_type_strategy: str
    tv_sxe_regex: str
    enable_season_episode_words: bool
    tv_season_episode_regex: str

    video_stream_strategy: str
    audio_stream_strategy: str

    audio_codec_preference: List[str]
    problem_audio_codecs: List[str]
    problem_audio_profile_regex: List[str]

    hdr_color_transfer: List[str]
    hdr_side_data_regex: List[str]


@dataclass(frozen=True)
class NamingConfig:
    movie_template: str
    tv_template: str
    hdr_sep: str
    flags_sep: str
    fallback_to_stem: bool
    vcodec_map: Dict[str, str]
    acodec_map: Dict[str, str]
    sanitize: bool
    max_filename_len: int


@dataclass(frozen=True)
class TierDef:
    id: str
    folder: str
    description: str
    requires: Dict[str, Any]
    flags: List[str]


@dataclass(frozen=True)
class TierModelConfig:
    tiers: int
    tier: List[TierDef]


@dataclass(frozen=True)
class FlagsConfig:
    enable_hfr_flag: bool
    hfr_fps_threshold: float
    enable_low_bitrate_flag: bool
    low_bitrate_thresholds: Dict[str, int]
    low_bitrate_flag_name: str


@dataclass(frozen=True)
class ReportingConfig:
    write_jsonl_report: bool
    report_path: Path


@dataclass(frozen=True)
class SiftConfig:
    paths: PathsConfig
    io: IOConfig
    ffprobe: FFProbeConfig
    classification: ClassificationConfig
    naming: NamingConfig
    tier_model: TierModelConfig
    flags: FlagsConfig
    reporting: ReportingConfig


# ----------------------------
# TOML helpers
# ----------------------------


class ConfigError(RuntimeError):
    pass


def _as_bool(d: Dict[str, Any], key: str) -> bool:
    v = d.get(key)
    if isinstance(v, bool):
        return v
    raise ConfigError(f"Expected boolean for '{key}', got: {type(v).__name__}")


def _as_str(d: Dict[str, Any], key: str) -> str:
    v = d.get(key)
    if isinstance(v, str) and v != "":
        return v
    raise ConfigError(f"Expected non-empty string for '{key}', got: {v!r}")


def _as_int(d: Dict[str, Any], key: str) -> int:
    v = d.get(key)
    if isinstance(v, int):
        return v
    raise ConfigError(f"Expected integer for '{key}', got: {type(v).__name__}")


def _as_float(d: Dict[str, Any], key: str) -> float:
    v = d.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    raise ConfigError(f"Expected float for '{key}', got: {type(v).__name__}")


def _as_list_str(d: Dict[str, Any], key: str) -> List[str]:
    v = d.get(key)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    raise ConfigError(f"Expected list of strings for '{key}', got: {v!r}")


def _as_dict(d: Dict[str, Any], key: str) -> Dict[str, Any]:
    v = d.get(key)
    if isinstance(v, dict):
        return v
    raise ConfigError(f"Expected table/dict for '{key}', got: {type(v).__name__}")


def _as_path(s: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(s))
    return Path(expanded).resolve()


def _require_table(root: Dict[str, Any], table: str) -> Dict[str, Any]:
    if table not in root or not isinstance(root[table], dict):
        raise ConfigError(f"Missing required table: [{table}]")
    return root[table]


def _optional_str(d: Dict[str, Any], key: str, default: str) -> str:
    if key not in d:
        return default
    v = d.get(key)
    if isinstance(v, str):
        return v
    raise ConfigError(f"Expected string for '{key}', got: {type(v).__name__}")


def _optional_bool(d: Dict[str, Any], key: str, default: bool) -> bool:
    if key not in d:
        return default
    v = d.get(key)
    if isinstance(v, bool):
        return v
    raise ConfigError(f"Expected boolean for '{key}', got: {type(v).__name__}")


# ----------------------------
# Load + validate config
# ----------------------------


def load_toml(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as e:
        raise ConfigError(
            f"Config file not found: {path}\n"
            "Create it by copying config.example.toml to config.toml and editing paths."
        ) from e
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise ConfigError(f"Config is not valid UTF-8: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"TOML parse error in {path}: {e}") from e


def parse_config(root: Dict[str, Any]) -> SiftConfig:
    # ---- paths
    paths = _require_table(root, "paths")
    paths_cfg = PathsConfig(
        incoming=_as_path(_as_str(paths, "incoming")),
        outgoing_root=_as_path(_as_str(paths, "outgoing_root")),
        metadata_cache=_as_path(_as_str(paths, "metadata_cache")),
    )

    # ---- io
    io = _require_table(root, "io")
    mode = _as_str(io, "mode").lower()
    if mode not in {"move", "copy"}:
        raise ConfigError("io.mode must be 'move' or 'copy'")
    io_cfg = IOConfig(
        mode=mode,
        mkdirs=_as_bool(io, "mkdirs"),
        dedupe_on_collision=_as_bool(io, "dedupe_on_collision"),
    )

    # ---- ffprobe
    ffprobe = _require_table(root, "ffprobe")
    ffprobe_cfg = FFProbeConfig(
        bin=_as_str(ffprobe, "bin"),
        args=_as_list_str(ffprobe, "args"),
    )

    # ---- classification
    cls = _require_table(root, "classification")
    media_type_strategy = _as_str(cls, "media_type_strategy").lower()
    if media_type_strategy not in {"folder", "guess", "sxe"}:
        raise ConfigError(
            "classification.media_type_strategy must be 'folder', 'guess', or 'sxe'"
        )

    default_sxe = r"(?i)\bs\s*\d{1,2}\s*[._ -]?\s*e\s*\d{1,3}\b"
    default_words = r"(?i)\bseason\s*\d{1,2}\b.*\bepisode\s*\d{1,3}\b"

    classification_cfg = ClassificationConfig(
        media_type_strategy=media_type_strategy,
        tv_sxe_regex=_optional_str(cls, "tv_sxe_regex", default_sxe),
        enable_season_episode_words=_optional_bool(
            cls, "enable_season_episode_words", False
        ),
        tv_season_episode_regex=_optional_str(
            cls, "tv_season_episode_regex", default_words
        ),
        video_stream_strategy=_as_str(cls, "video_stream_strategy").lower(),
        audio_stream_strategy=_as_str(cls, "audio_stream_strategy").lower(),
        audio_codec_preference=_as_list_str(cls, "audio_codec_preference"),
        problem_audio_codecs=_as_list_str(cls, "problem_audio_codecs"),
        problem_audio_profile_regex=_as_list_str(cls, "problem_audio_profile_regex"),
        hdr_color_transfer=_as_list_str(cls, "hdr_color_transfer"),
        hdr_side_data_regex=_as_list_str(cls, "hdr_side_data_regex"),
    )

    # ---- naming
    naming = _require_table(root, "naming")
    naming_cfg = NamingConfig(
        movie_template=_as_str(naming, "movie_template"),
        tv_template=_as_str(naming, "tv_template"),
        hdr_sep=_as_str(naming, "hdr_sep"),
        flags_sep=_as_str(naming, "flags_sep"),
        fallback_to_stem=bool(naming.get("fallback_to_stem", True)),
        vcodec_map={k: str(v) for k, v in _as_dict(naming, "vcodec_map").items()},
        acodec_map={k: str(v) for k, v in _as_dict(naming, "acodec_map").items()},
        sanitize=_as_bool(naming, "sanitize"),
        max_filename_len=_as_int(naming, "max_filename_len"),
    )

    # ---- tier model
    tier_model = _require_table(root, "tier_model")
    tiers = _as_int(tier_model, "tiers")
    if tiers not in {3, 5}:
        raise ConfigError("tier_model.tiers must be 3 or 5")

    tier_list = tier_model.get("tier")
    if not isinstance(tier_list, list) or not tier_list:
        raise ConfigError(
            "tier_model.tier must be a non-empty array of tables ([[tier_model.tier]])"
        )

    parsed_tiers: List[TierDef] = []
    for i, t in enumerate(tier_list, start=1):
        if not isinstance(t, dict):
            raise ConfigError(f"tier_model.tier[{i}] must be a table")
        requires = t.get("requires", {})
        if requires is None:
            requires = {}
        if not isinstance(requires, dict):
            raise ConfigError(f"tier_model.tier[{i}].requires must be a table/dict")
        flags = t.get("flags", [])
        if flags is None:
            flags = []
        if not isinstance(flags, list) or not all(isinstance(x, str) for x in flags):
            raise ConfigError(f"tier_model.tier[{i}].flags must be a list of strings")

        parsed_tiers.append(
            TierDef(
                id=_as_str(t, "id"),
                folder=_as_str(t, "folder"),
                description=str(t.get("description", "")).strip(),
                requires=dict(requires),
                flags=list(flags),
            )
        )

    tier_cfg = TierModelConfig(tiers=tiers, tier=parsed_tiers)

    # ---- flags
    flags = _require_table(root, "flags")
    low_bt = flags.get("low_bitrate_thresholds")
    if not isinstance(low_bt, dict) or not all(
        isinstance(k, str) and isinstance(v, int) for k, v in low_bt.items()
    ):
        raise ConfigError(
            "flags.low_bitrate_thresholds must be a table of { string = int } (bps)"
        )

    flags_cfg = FlagsConfig(
        enable_hfr_flag=_as_bool(flags, "enable_hfr_flag"),
        hfr_fps_threshold=_as_float(flags, "hfr_fps_threshold"),
        enable_low_bitrate_flag=_as_bool(flags, "enable_low_bitrate_flag"),
        low_bitrate_thresholds={k: int(v) for k, v in low_bt.items()},
        low_bitrate_flag_name=_as_str(flags, "low_bitrate_flag_name"),
    )

    # ---- reporting
    reporting = _require_table(root, "reporting")
    reporting_cfg = ReportingConfig(
        write_jsonl_report=_as_bool(reporting, "write_jsonl_report"),
        report_path=_as_path(_as_str(reporting, "report_path")),
    )

    return SiftConfig(
        paths=paths_cfg,
        io=io_cfg,
        ffprobe=ffprobe_cfg,
        classification=classification_cfg,
        naming=naming_cfg,
        tier_model=tier_cfg,
        flags=flags_cfg,
        reporting=reporting_cfg,
    )


# ----------------------------
# Folder creation (MVP1)
# ----------------------------


def ensure_dirs(cfg: SiftConfig) -> List[Path]:
    ensured: List[Path] = []

    def _mk(p: Path) -> None:
        p.mkdir(parents=True, exist_ok=True)
        ensured.append(p)

    _mk(cfg.paths.outgoing_root)
    _mk(cfg.paths.metadata_cache)

    if cfg.reporting.write_jsonl_report:
        _mk(cfg.reporting.report_path.parent)

    for media_type in ("movies", "tv"):
        base = cfg.paths.outgoing_root / media_type
        _mk(base)
        for t in cfg.tier_model.tier:
            _mk(base / t.folder)

    return ensured


# ----------------------------
# Scanning + ffprobe + cache
# ----------------------------


CACHE_VERSION = 2
DEFAULT_SCAN_CACHE_NAME = "scan.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_ratio(r: Any) -> Optional[float]:
    """
    ffprobe often reports avg_frame_rate as '24000/1001'.
    """
    if not isinstance(r, str) or "/" not in r:
        return _safe_float(r)
    num_s, den_s = r.split("/", 1)
    num = _safe_float(num_s)
    den = _safe_float(den_s)
    if not num or not den:
        return None
    if den == 0:
        return None
    return num / den


def _ffprobe_json(
    cfg: SiftConfig, media_path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Run ffprobe and return (json_dict, error_string).
    Never raises on ffprobe failure; errors are captured per-file.
    """
    cmd = [cfg.ffprobe.bin, *cfg.ffprobe.args, str(media_path)]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, f"ffprobe not found: {cfg.ffprobe.bin}"
    except OSError as e:
        return None, f"ffprobe exec error: {e}"

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if not stderr:
            stderr = f"ffprobe exited {proc.returncode}"
        return None, stderr

    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as e:
        return None, f"ffprobe output was not valid JSON: {e}"


def _summarize_ffprobe(ff: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract a compact, stable subset of technical metrics.
    Keep it boring and cache-friendly.

    What you get (best-effort):
    - container format
    - duration_s
    - overall bitrate_bps
    - video: codec, profile, width, height, pix_fmt, fps, bit_rate, color* and hdr-ish hints
    - audio: codec, profile, channels, sample_rate, bit_rate
    """
    out: Dict[str, Any] = {"ok": True}

    fmt = ff.get("format") or {}
    out["container"] = fmt.get("format_name")
    out["duration_s"] = _safe_float(fmt.get("duration"))
    out["overall_bitrate_bps"] = _safe_int(fmt.get("bit_rate"))
    out["size_bytes_probe"] = _safe_int(fmt.get("size"))

    streams = ff.get("streams") or []
    if not isinstance(streams, list):
        streams = []

    vstreams = [
        s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"
    ]
    astreams = [
        s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"
    ]

    # Pick "best" video stream: highest resolution, then first
    vbest = None
    if vstreams:

        def vkey(s: Dict[str, Any]) -> Tuple[int, int]:
            w = _safe_int(s.get("width")) or 0
            h = _safe_int(s.get("height")) or 0
            return (w * h, h)

        vbest = sorted(vstreams, key=vkey, reverse=True)[0]

    # Pick "best" audio stream: highest channels, then first
    abest = None
    if astreams:

        def akey(s: Dict[str, Any]) -> Tuple[int, int]:
            ch = _safe_int(s.get("channels")) or 0
            br = _safe_int(s.get("bit_rate")) or 0
            return (ch, br)

        abest = sorted(astreams, key=akey, reverse=True)[0]

    if vbest:
        vf: Dict[str, Any] = {}
        vf["codec"] = vbest.get("codec_name")
        vf["profile"] = vbest.get("profile")
        vf["width"] = _safe_int(vbest.get("width"))
        vf["height"] = _safe_int(vbest.get("height"))
        vf["pix_fmt"] = vbest.get("pix_fmt")
        vf["bit_rate_bps"] = _safe_int(vbest.get("bit_rate"))
        vf["fps"] = _parse_ratio(vbest.get("avg_frame_rate")) or _parse_ratio(
            vbest.get("r_frame_rate")
        )

        # Color / HDR-ish fields (presence depends on container/codec)
        vf["color_space"] = vbest.get("color_space")
        vf["color_transfer"] = vbest.get("color_transfer")
        vf["color_primaries"] = vbest.get("color_primaries")
        vf["color_range"] = vbest.get("color_range")
        vf["chroma_location"] = vbest.get("chroma_location")

        # Tags are common place for HDR naming; side_data_list can also exist.
        tags = vbest.get("tags") if isinstance(vbest.get("tags"), dict) else {}
        vf["tags"] = {k: str(v) for k, v in tags.items()} if tags else {}

        side_data = vbest.get("side_data_list")
        if isinstance(side_data, list):
            # Keep it small: just the type names.
            types = []
            for sd in side_data:
                if isinstance(sd, dict) and sd.get("side_data_type"):
                    types.append(str(sd.get("side_data_type")))
            vf["side_data_types"] = sorted(set(types))

        out["video"] = vf

    if abest:
        af: Dict[str, Any] = {}
        af["codec"] = abest.get("codec_name")
        af["profile"] = abest.get("profile")
        af["channels"] = _safe_int(abest.get("channels"))
        af["channel_layout"] = abest.get("channel_layout")
        af["sample_rate_hz"] = _safe_int(abest.get("sample_rate"))
        af["bit_rate_bps"] = _safe_int(abest.get("bit_rate"))
        out["audio"] = af

    out["stream_counts"] = {"video": len(vstreams), "audio": len(astreams)}
    return out


def scan_incoming_files(
    root: Path,
    *,
    only_ext: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Path]:
    if not root.exists():
        raise ConfigError(f"paths.incoming does not exist: {root}")
    if not root.is_dir():
        raise ConfigError(f"paths.incoming is not a directory: {root}")

    exts_norm: Optional[set[str]] = None
    if only_ext:
        exts_norm = {e.lower().lstrip(".") for e in only_ext if e.strip()}

    paths = [p for p in root.rglob("*") if p.is_file()]
    paths.sort(key=lambda p: str(p.relative_to(root)))

    if exts_norm is not None:
        paths = [p for p in paths if p.suffix.lower().lstrip(".") in exts_norm]

    if limit is not None and limit >= 0:
        paths = paths[:limit]

    return paths


def cache_path(cfg: SiftConfig) -> Path:
    return cfg.paths.metadata_cache / DEFAULT_SCAN_CACHE_NAME


def write_scan_cache(cfg: SiftConfig, items: List[Dict[str, Any]]) -> Path:
    cp = cache_path(cfg)
    payload = {
        "schema_version": CACHE_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "incoming_root": str(cfg.paths.incoming),
        "count": len(items),
        "items": items,
    }

    tmp = cp.with_suffix(cp.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(cp)
    return cp


def read_scan_cache(cfg: SiftConfig) -> Dict[str, Any]:
    cp = cache_path(cfg)
    try:
        raw = cp.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FileNotFoundError(str(cp)) from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Cache file is not valid JSON: {cp}: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"Cache file must be a JSON object: {cp}")

    if int(data.get("schema_version", -1)) != CACHE_VERSION:
        raise ConfigError(
            f"Cache schema mismatch in {cp}: found {data.get('schema_version')}, expected {CACHE_VERSION}"
        )

    inc = data.get("incoming_root")
    if inc and str(inc) != str(cfg.paths.incoming):
        raise ConfigError(
            "Cache was generated for a different incoming_root.\n"
            f"  cache incoming_root : {inc}\n"
            f"  config incoming_root: {cfg.paths.incoming}\n"
            "Use --rescan to rebuild the cache."
        )

    return data


def build_inventory(
    cfg: SiftConfig,
    *,
    rescan: bool,
    only_ext: Optional[List[str]],
    limit: Optional[int],
) -> Dict[str, Any]:
    """
    Return full inventory payload (either from cache or fresh scan).
    """
    if not rescan:
        try:
            return read_scan_cache(cfg)
        except FileNotFoundError:
            pass  # fall through to scan

    media_paths = scan_incoming_files(
        cfg.paths.incoming, only_ext=only_ext, limit=limit
    )

    items: List[Dict[str, Any]] = []
    errors = 0

    for p in media_paths:
        rel = str(p.relative_to(cfg.paths.incoming))
        try:
            st = p.stat()
        except OSError:
            continue

        base: Dict[str, Any] = {
            "relpath": rel,
            "path": str(p),
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }

        ffj, err = _ffprobe_json(cfg, p)
        if err or ffj is None:
            errors += 1
            base["ffprobe"] = {"ok": False, "error": err}
        else:
            base["ffprobe"] = _summarize_ffprobe(ffj)

        items.append(base)

    # Stable ordering
    items.sort(key=lambda x: x.get("relpath", ""))

    cp = write_scan_cache(cfg, items)
    return {
        "schema_version": CACHE_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "incoming_root": str(cfg.paths.incoming),
        "count": len(items),
        "errors": int(errors),
        "items": items,
        "_cache_path": str(cp),
        "_fresh_scan": True,
    }


# ----------------------------
# CLI
# ----------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sift",
        description="Media intake: read config, ffprobe incoming media, cache technical metrics.",
    )
    p.add_argument(
        "--config",
        default="config.toml",
        help="Path to config TOML (default: ./config.toml).",
    )
    p.add_argument(
        "--print-config",
        action="store_true",
        help="Print parsed config summary and exit (debug).",
    )
    p.add_argument(
        "--print-folders",
        action="store_true",
        help="Print folders that would be created and exit (does not create them).",
    )
    p.add_argument(
        "--rescan",
        action="store_true",
        help="Force a fresh scan + ffprobe and overwrite the scan cache.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap how many files are probed (debug/iteration). Default: no limit.",
    )
    p.add_argument(
        "--only-ext",
        action="append",
        default=None,
        help="Restrict scanning to extensions (repeatable). Example: --only-ext mkv --only-ext mp4",
    )
    return p


def print_config_summary(cfg: SiftConfig) -> None:
    print("sift config summary")
    print("-------------------")
    print(f"incoming              : {cfg.paths.incoming}")
    print(f"outgoing_root         : {cfg.paths.outgoing_root}")
    print(f"metadata_cache        : {cfg.paths.metadata_cache}")
    print(f"mode                  : {cfg.io.mode}")
    print(f"mkdirs                : {cfg.io.mkdirs}")
    print(f"dedupe_on_collision   : {cfg.io.dedupe_on_collision}")
    print(
        f"ffprobe               : {cfg.ffprobe.bin} {' '.join(cfg.ffprobe.args)} <file>"
    )
    print(f"media_type_strategy   : {cfg.classification.media_type_strategy}")
    print(
        f"tiers                 : {cfg.tier_model.tiers} ({len(cfg.tier_model.tier)} rules)"
    )
    print(
        f"report_jsonl          : {cfg.reporting.write_jsonl_report} -> {cfg.reporting.report_path}"
    )


def planned_folders(cfg: SiftConfig) -> List[Path]:
    folders: List[Path] = []

    folders.append(cfg.paths.outgoing_root)
    folders.append(cfg.paths.metadata_cache)

    if cfg.reporting.write_jsonl_report:
        folders.append(cfg.reporting.report_path.parent)

    for media_type in ("movies", "tv"):
        base = cfg.paths.outgoing_root / media_type
        folders.append(base)
        for t in cfg.tier_model.tier:
            folders.append(base / t.folder)

    unique = sorted(set(folders), key=lambda p: str(p))
    return unique


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    cfg_path = _as_path(str(args.config))
    try:
        root = load_toml(cfg_path)
        cfg = parse_config(root)
    except ConfigError as e:
        print(f"[sift] config error: {e}", file=sys.stderr)
        return 2

    if args.print_config:
        print_config_summary(cfg)
        return 0

    if args.print_folders:
        for p in planned_folders(cfg):
            print(p)
        return 0

    if cfg.io.mkdirs:
        ensure_dirs(cfg)

    # Build inventory (cache unless --rescan or cache missing).
    try:
        inv = build_inventory(
            cfg,
            rescan=bool(args.rescan),
            only_ext=list(args.only_ext) if args.only_ext else None,
            limit=args.limit,
        )
    except (ConfigError, OSError) as e:
        print(f"[sift] scan/cache error: {e}", file=sys.stderr)
        return 3

    cp = cache_path(cfg)
    fresh = bool(inv.get("_fresh_scan", False))
    count = int(inv.get("count", 0))
    errors = int(inv.get("errors", 0)) if fresh else int(inv.get("errors", 0) or 0)

    # If we loaded from cache, inv won't have errors unless previous writer included it.
    if not fresh:
        errors = int(inv.get("errors", 0) or 0)

    print(
        f"[sift] inventory: {count} files "
        f"({'fresh scan' if fresh else 'from cache'}) "
        f"errors={errors} -> {cp}"
    )

    print("[sift] config loaded OK. (MVP1.2: ffprobe scan + cache)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
