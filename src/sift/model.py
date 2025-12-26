from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


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

    horizontal_4k_threshold: int = 3800
    vertical_thresholds: Dict[str, int] = field(
        default_factory=lambda: {"2160p": 2000, "1080p": 1000, "720p": 700}
    )


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
    # judgement_flags: list of flags that are *judgements* and should not be
    # shown in rendered filenames. Configure in your TOML to control behavior.
    judgement_flags: List[str] = field(
        default_factory=lambda: [
            "REPLACE_SOON",
            "REPLACE",
            "INCOMPATIBLE",
            "REVIEW",
            "OK",
            "KEEP",
        ]
    )


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
