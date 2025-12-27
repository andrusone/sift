from pathlib import Path

from sift.inventory import _mark_samples, _normalize_stem
from sift.model import (
    PathsConfig,
    IOConfig,
    FFProbeConfig,
    ClassificationConfig,
    NamingConfig,
    TierModelConfig,
    TierDef,
    FlagsConfig,
    ReportingConfig,
    SampleDetectionConfig,
    SiftConfig,
)


def make_cfg(base: Path, **overrides) -> SiftConfig:
    defaults = {
        "enabled": True,
        "min_duration_s": 300.0,
        "prefer_longest_variant": True,
        "min_video_streams": 1,
    }
    defaults.update(overrides)
    return SiftConfig(
        paths=PathsConfig(
            incoming=base / "incoming",
            outgoing_root=base / "outgoing",
            metadata_cache=base / "cache",
        ),
        io=IOConfig(mode="copy", mkdirs=True, dedupe_on_collision=True),
        ffprobe=FFProbeConfig(bin="ffprobe", args=[]),
        classification=ClassificationConfig(
            media_type_strategy="folder",
            tv_sxe_regex="x",
            enable_season_episode_words=False,
            tv_season_episode_regex="y",
            video_stream_strategy="best",
            audio_stream_strategy="best",
            audio_codec_preference=[],
            problem_audio_codecs=[],
            problem_audio_profile_regex=[],
            hdr_color_transfer=[],
            hdr_side_data_regex=[],
        ),
        naming=NamingConfig(
            movie_template="x",
            tv_template="y",
            hdr_sep=" ",
            flags_sep=" ",
            fallback_to_stem=True,
            vcodec_map={},
            acodec_map={},
            sanitize=True,
            max_filename_len=200,
        ),
        tier_model=TierModelConfig(
            tiers=1,
            tier=[
                TierDef(id="T1", folder="tier1", description="", requires={}, flags=[])
            ],
        ),
        flags=FlagsConfig(
            enable_hfr_flag=False,
            hfr_fps_threshold=60.0,
            enable_low_bitrate_flag=False,
            low_bitrate_thresholds={"default": 1},
            low_bitrate_flag_name="LOW",
            judgement_flags=[],
        ),
        reporting=ReportingConfig(
            write_jsonl_report=False, report_path=base / "report.jsonl"
        ),
        sample_detection=SampleDetectionConfig(**defaults),
    )


def test_normalize_stem_removes_noise():
    assert _normalize_stem("Movie.Name.2023.SAMPLE") == "movie name 2023"
    assert _normalize_stem("Movie [720p] (Sample)") == "movie"
    assert _normalize_stem("Movie_Trailer_1080p") == "movie"
    assert _normalize_stem("Movie.Name.2023.[GROUP]") == "movie name 2023"


def test_mark_samples_skips_short_files(tmp_path):
    cfg = make_cfg(tmp_path, min_duration_s=300.0)
    items = [
        {
            "relpath": "short.mkv",
            "path": str(tmp_path / "short.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 120.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
        {
            "relpath": "long.mkv",
            "path": str(tmp_path / "long.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 6000.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
    ]
    _mark_samples(cfg, items)
    assert items[0].get("skip_reason") == "sample_too_short"
    assert "skip_reason" not in items[1]


def test_mark_samples_skips_no_video(tmp_path):
    cfg = make_cfg(tmp_path, min_video_streams=1)
    items = [
        {
            "relpath": "audio_only.mkv",
            "path": str(tmp_path / "audio_only.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 6000.0,
                "stream_counts": {"video": 0, "audio": 1},
            },
        },
    ]
    _mark_samples(cfg, items)
    assert items[0].get("skip_reason") == "no_video_stream"


def test_prefer_longest_variant_marks_shorter(tmp_path):
    cfg = make_cfg(tmp_path, prefer_longest_variant=True, min_duration_s=60.0)
    items = [
        {
            "relpath": "Movie.2023.1080p.mkv",
            "path": str(tmp_path / "Movie.2023.1080p.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 7200.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
        {
            "relpath": "Movie.2023.Sample.mkv",
            "path": str(tmp_path / "Movie.2023.Sample.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 300.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
        {
            "relpath": "Movie.2023.[TRAILER].mkv",
            "path": str(tmp_path / "Movie.2023.[TRAILER].mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 180.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
    ]
    _mark_samples(cfg, items)
    # The full movie (7200s) should not be marked
    assert "skip_reason" not in items[0]
    # Sample (300s) and trailer (180s) should be marked as shorter variants
    assert items[1].get("skip_reason") == "sample_shorter_variant"
    assert items[2].get("skip_reason") == "sample_shorter_variant"


def test_prefer_longest_disabled_keeps_all(tmp_path):
    cfg = make_cfg(tmp_path, prefer_longest_variant=False, min_duration_s=60.0)
    items = [
        {
            "relpath": "Movie.2023.1080p.mkv",
            "path": str(tmp_path / "Movie.2023.1080p.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 7200.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
        {
            "relpath": "Movie.2023.Sample.mkv",
            "path": str(tmp_path / "Movie.2023.Sample.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 300.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
    ]
    _mark_samples(cfg, items)
    # When prefer_longest_variant is disabled, both should pass (above min_duration_s)
    assert "skip_reason" not in items[0]
    assert "skip_reason" not in items[1]


def test_disabled_sample_detection(tmp_path):
    cfg = make_cfg(tmp_path, enabled=False, min_duration_s=300.0)
    items = [
        {
            "relpath": "short.mkv",
            "path": str(tmp_path / "short.mkv"),
            "ffprobe": {
                "ok": True,
                "duration_s": 30.0,
                "stream_counts": {"video": 1, "audio": 1},
            },
        },
    ]
    _mark_samples(cfg, items)
    # When disabled, no samples should be marked
    assert "skip_reason" not in items[0]
