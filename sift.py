#!/usr/bin/env python3
"""
sift.py

Media intake: ffprobe facts -> classify -> rename -> move/copy into an "intake" structure.

MVP1 responsibility:
- Load configuration from TOML (default: ./config.toml)
- Validate required settings and normalize paths
- Create required folder structure (cache + tier folders under outgoing_root)

Design notes:
- Uses Python 3.11+ built-in `tomllib` (no third-party deps).
- Fails fast with clear error messages.
- Treats config as an explicit contract; minimal “magic defaults”.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    # media_type_strategy:
    # - "folder": first directory under incoming is movies|tv
    # - "guess": reserved for future heuristics
    # - "sxe": if filename contains S##E## (or season/episode words) => tv, else movies
    media_type_strategy: str

    # Only used when media_type_strategy == "sxe"
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
    """
    Accept any string except the empty string.

    Note: whitespace-only strings are valid for formatting tokens like separators,
    e.g. hdr_sep = " ".
    """
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
    """
    Create directories implied by config. Returns a list of directories created (or ensured).
    This is intentionally deterministic and boring:
      - outgoing_root
      - metadata_cache
      - report_path parent
      - tier folders for both movies and tv under outgoing_root
    """
    ensured: List[Path] = []

    def _mk(p: Path) -> None:
        p.mkdir(parents=True, exist_ok=True)
        ensured.append(p)

    _mk(cfg.paths.outgoing_root)
    _mk(cfg.paths.metadata_cache)

    # Ensure report parent exists if reporting enabled
    if cfg.reporting.write_jsonl_report:
        _mk(cfg.reporting.report_path.parent)

    # Pre-create all tier folders for both media types
    for media_type in ("movies", "tv"):
        base = cfg.paths.outgoing_root / media_type
        _mk(base)
        for t in cfg.tier_model.tier:
            _mk(base / t.folder)

    return ensured


# ----------------------------
# CLI
# ----------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sift",
        description="Media intake: read config, later will inspect media via ffprobe and organize outputs.",
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
    if cfg.classification.media_type_strategy == "sxe":
        print(f"tv_sxe_regex          : {cfg.classification.tv_sxe_regex}")
        print(
            f"season/episode words  : {cfg.classification.enable_season_episode_words}"
        )
        if cfg.classification.enable_season_episode_words:
            print(
                f"tv_words_regex        : {cfg.classification.tv_season_episode_regex}"
            )
    print(
        f"audio_preference      : {', '.join(cfg.classification.audio_codec_preference)}"
    )
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

    # Dedup + stable ordering (Path is hashable)
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

    # MVP1 behavior: ensure dirs exist if configured, then exit.
    if cfg.io.mkdirs:
        ensure_dirs(cfg)

    print("[sift] config loaded OK. (MVP1: config ingestion + folder scaffold)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
