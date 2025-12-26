from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .errors import ConfigError
from .model import (
    ClassificationConfig,
    FFProbeConfig,
    FlagsConfig,
    IOConfig,
    NamingConfig,
    PathsConfig,
    ReportingConfig,
    SiftConfig,
    TierDef,
    TierModelConfig,
)
from .utils import as_path

try:
    import tomllib  # py311+
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("Python 3.11+ required (missing tomllib).") from exc


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


def _require_table(root: Dict[str, Any], table: str) -> Dict[str, Any]:
    if table not in root or not isinstance(root[table], dict):
        raise ConfigError(f"Missing required table: [{table}]")
    return root[table]


def _get(root: Dict[str, Any], path: str) -> Any:
    cur: Any = root
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur.get(part)
    return cur


def expect(
    root: Dict[str, Any],
    path: str,
    typ: type,
    *,
    default=object(),
    required: bool = True,
) -> Any:
    """Traverse `path` (dot-separated) and ensure the value exists and is `typ`.

    If `default` is provided and the value is missing, `default` is returned.
    Raises `ConfigError` on missing required values or type mismatches.
    """
    v = _get(root, path)
    if v is None:
        if default is not object():
            return default
        if required:
            raise ConfigError(f"Missing required config value: {path}")
        return None
    if not isinstance(v, typ):
        raise ConfigError(
            f"Expected {typ.__name__} for '{path}', got: {type(v).__name__}"
        )
    return v


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


def parse_config(root: Dict[str, Any]) -> SiftConfig:
    # ---- paths
    paths_cfg = PathsConfig(
        incoming=as_path(expect(root, "paths.incoming", str)),
        outgoing_root=as_path(expect(root, "paths.outgoing_root", str)),
        metadata_cache=as_path(expect(root, "paths.metadata_cache", str)),
    )

    # ---- io
    mode = expect(root, "io.mode", str).lower()
    if mode not in {"move", "copy"}:
        raise ConfigError("io.mode must be 'move' or 'copy'")
    io_cfg = IOConfig(
        mode=mode,
        mkdirs=expect(root, "io.mkdirs", bool),
        dedupe_on_collision=expect(root, "io.dedupe_on_collision", bool),
    )

    # ---- ffprobe
    ffprobe_cfg = FFProbeConfig(
        bin=expect(root, "ffprobe.bin", str),
        args=_as_list_str(expect(root, "ffprobe", dict), "args"),
    )

    # ---- classification
    media_type_strategy = expect(
        root, "classification.media_type_strategy", str
    ).lower()
    if media_type_strategy not in {"folder", "guess", "sxe"}:
        raise ConfigError(
            "classification.media_type_strategy must be 'folder', 'guess', or 'sxe'"
        )

    default_sxe = r"(?i)\bs\s*\d{1,2}\s*[._ -]?\s*e\s*\d{1,3}\b"
    default_words = r"(?i)\bseason\s*\d{1,2}\b.*\bepisode\s*\d{1,3}\b"

    classification_tbl = expect(root, "classification", dict)

    # Parse resolution settings with defaults
    resolution_tbl = classification_tbl.get("resolution", {})
    if not isinstance(resolution_tbl, dict):
        resolution_tbl = {}

    horizontal_4k_threshold = resolution_tbl.get("horizontal_4k_threshold", 3800)
    if not isinstance(horizontal_4k_threshold, int):
        raise ConfigError(
            "classification.resolution.horizontal_4k_threshold must be an integer"
        )

    vertical_thresholds_raw = resolution_tbl.get(
        "vertical_thresholds", {"2160p": 2000, "1080p": 1000, "720p": 700}
    )
    if not isinstance(vertical_thresholds_raw, dict):
        raise ConfigError(
            "classification.resolution.vertical_thresholds must be a table/dict"
        )
    vertical_thresholds = {k: int(v) for k, v in vertical_thresholds_raw.items()}

    classification_cfg = ClassificationConfig(
        media_type_strategy=media_type_strategy,
        tv_sxe_regex=_optional_str(classification_tbl, "tv_sxe_regex", default_sxe),
        enable_season_episode_words=_optional_bool(
            classification_tbl, "enable_season_episode_words", False
        ),
        tv_season_episode_regex=_optional_str(
            classification_tbl,
            "tv_season_episode_regex",
            default_words,
        ),
        video_stream_strategy=expect(
            root, "classification.video_stream_strategy", str
        ).lower(),
        audio_stream_strategy=expect(
            root, "classification.audio_stream_strategy", str
        ).lower(),
        audio_codec_preference=_as_list_str(
            classification_tbl, "audio_codec_preference"
        ),
        problem_audio_codecs=_as_list_str(classification_tbl, "problem_audio_codecs"),
        problem_audio_profile_regex=_as_list_str(
            classification_tbl, "problem_audio_profile_regex"
        ),
        hdr_color_transfer=_as_list_str(classification_tbl, "hdr_color_transfer"),
        hdr_side_data_regex=_as_list_str(classification_tbl, "hdr_side_data_regex"),
        horizontal_4k_threshold=horizontal_4k_threshold,
        vertical_thresholds=vertical_thresholds,
    )

    # ---- naming
    naming_tbl = expect(root, "naming", dict)
    naming_cfg = NamingConfig(
        movie_template=_as_str(naming_tbl, "movie_template"),
        tv_template=_as_str(naming_tbl, "tv_template"),
        hdr_sep=_as_str(naming_tbl, "hdr_sep"),
        flags_sep=_as_str(naming_tbl, "flags_sep"),
        fallback_to_stem=bool(naming_tbl.get("fallback_to_stem", True)),
        vcodec_map={k: str(v) for k, v in _as_dict(naming_tbl, "vcodec_map").items()},
        acodec_map={k: str(v) for k, v in _as_dict(naming_tbl, "acodec_map").items()},
        sanitize=_as_bool(naming_tbl, "sanitize"),
        max_filename_len=_as_int(naming_tbl, "max_filename_len"),
    )

    # ---- tier model
    tier_model = expect(root, "tier_model", dict)
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
        requires = t.get("requires", {}) or {}
        if not isinstance(requires, dict):
            raise ConfigError(f"tier_model.tier[{i}].requires must be a table/dict")
        flags = t.get("flags", []) or []
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

    # default judgement flags (these are considered "judgement" and don't
    # appear in filenames unless you override them in config)
    default_judgement = [
        "REPLACE_SOON",
        "REPLACE",
        "INCOMPATIBLE",
        "REVIEW",
        "OK",
        "KEEP",
    ]
    jf = flags.get("judgement_flags", default_judgement)
    if not isinstance(jf, list) or not all(isinstance(x, str) for x in jf):
        raise ConfigError("flags.judgement_flags must be a list of strings")

    flags_cfg = FlagsConfig(
        enable_hfr_flag=_as_bool(flags, "enable_hfr_flag"),
        hfr_fps_threshold=_as_float(flags, "hfr_fps_threshold"),
        enable_low_bitrate_flag=_as_bool(flags, "enable_low_bitrate_flag"),
        low_bitrate_thresholds={k: int(v) for k, v in low_bt.items()},
        low_bitrate_flag_name=_as_str(flags, "low_bitrate_flag_name"),
        judgement_flags=list(jf),
    )

    # ---- reporting
    reporting = _require_table(root, "reporting")
    reporting_cfg = ReportingConfig(
        write_jsonl_report=_as_bool(reporting, "write_jsonl_report"),
        report_path=as_path(_as_str(reporting, "report_path")),
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
