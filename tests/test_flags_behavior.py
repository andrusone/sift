from pathlib import Path

from sift.router import render_name

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
    SiftConfig,
)


def make_cfg(base: Path) -> SiftConfig:
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
            movie_template="{title} ({year}) [{res}{hdr_sep}{hdr} {vcodec_tag} {audio_tag}{flags_sep}{flags}].{ext}",
            tv_template="{show} - S{season2}E{episode2} [{res}{hdr_sep}{hdr} {vcodec_tag} {audio_tag}{flags_sep}{flags}].{ext}",
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
                TierDef(
                    id="T1", folder="tier1", description="", requires={}, flags=["REF"]
                )
            ],
        ),
        flags=FlagsConfig(
            enable_hfr_flag=False,
            hfr_fps_threshold=60.0,
            enable_low_bitrate_flag=False,
            low_bitrate_thresholds={"default": 1},
            low_bitrate_flag_name="LOW",
        ),
        reporting=ReportingConfig(
            write_jsonl_report=False, report_path=base / "report.jsonl"
        ),
    )


def test_judgement_flags_filtered(tmp_path):
    # Build a cfg explicitly with sxe strategy and a T4 tier
    base = make_cfg(tmp_path)
    classification = ClassificationConfig(
        media_type_strategy="sxe",
        tv_sxe_regex=r"(?i)\bs\s*\d{1,2}\s*[._ -]?\s*e\s*\d{1,3}\b",
        enable_season_episode_words=False,
        tv_season_episode_regex="y",
        video_stream_strategy=base.classification.video_stream_strategy,
        audio_stream_strategy=base.classification.audio_stream_strategy,
        audio_codec_preference=base.classification.audio_codec_preference,
        problem_audio_codecs=base.classification.problem_audio_codecs,
        problem_audio_profile_regex=base.classification.problem_audio_profile_regex,
        hdr_color_transfer=base.classification.hdr_color_transfer,
        hdr_side_data_regex=base.classification.hdr_side_data_regex,
    )

    tier_model = TierModelConfig(
        tiers=1,
        tier=[
            TierDef(
                id="T4",
                folder="T4-LowQuality",
                description="",
                requires={"res": ["720p", "SD"]},
                flags=["REPLACE_SOON"],
            )
        ],
    )

    cfg = SiftConfig(
        paths=base.paths,
        io=base.io,
        ffprobe=base.ffprobe,
        classification=classification,
        naming=base.naming,
        tier_model=tier_model,
        flags=base.flags,
        reporting=base.reporting,
    )

    # Build an item that will route to T4 (LowQuality) by making height 720
    item = {
        "relpath": "Show S01E02 720p.mkv",
        "path": str(tmp_path / "Show S01E02 720p.mkv"),
        "ffprobe": {
            "ok": True,
            "video": {"height": 720, "codec": "h264"},
            "overall_bitrate_bps": 10000000,
        },
    }

    name = render_name(cfg, item)
    assert "REPLACE_SOON" not in name

    # Also ensure common non-descriptive tier flags like 'OK' are filtered by default
    tier_model_ok = TierModelConfig(
        tiers=1,
        tier=[
            TierDef(
                id="T3",
                folder="T3",
                description="",
                requires={"res": ["1080p"]},
                flags=["OK"],
            )
        ],
    )
    cfg2 = SiftConfig(
        paths=base.paths,
        io=base.io,
        ffprobe=base.ffprobe,
        classification=classification,
        naming=base.naming,
        tier_model=tier_model_ok,
        flags=base.flags,
        reporting=base.reporting,
    )
    item_ok = {
        "relpath": "Show S01E02 1080p.mkv",
        "path": str(tmp_path / "Show S01E02 1080p.mkv"),
        "ffprobe": {
            "ok": True,
            "video": {"height": 1080, "codec": "h264"},
            "overall_bitrate_bps": 10000000,
        },
    }
    name2 = render_name(cfg2, item_ok)
    assert "OK" not in name2


def test_hfr_and_low_bitrate_flags(tmp_path):
    base = make_cfg(tmp_path)
    classification = ClassificationConfig(
        media_type_strategy="sxe",
        tv_sxe_regex=r"(?i)\bs\s*\d{1,2}\s*[._ -]?\s*e\s*\d{1,3}\b",
        enable_season_episode_words=False,
        tv_season_episode_regex="y",
        video_stream_strategy=base.classification.video_stream_strategy,
        audio_stream_strategy=base.classification.audio_stream_strategy,
        audio_codec_preference=base.classification.audio_codec_preference,
        problem_audio_codecs=base.classification.problem_audio_codecs,
        problem_audio_profile_regex=base.classification.problem_audio_profile_regex,
        hdr_color_transfer=base.classification.hdr_color_transfer,
        hdr_side_data_regex=base.classification.hdr_side_data_regex,
    )

    flags_cfg = FlagsConfig(
        enable_hfr_flag=True,
        hfr_fps_threshold=50.0,
        enable_low_bitrate_flag=True,
        low_bitrate_thresholds={"720p": 15000000},
        low_bitrate_flag_name="LOW_BR",
        judgement_flags=["REPLACE_SOON", "REPLACE", "INCOMPATIBLE", "REVIEW"],
    )

    cfg = SiftConfig(
        paths=base.paths,
        io=base.io,
        ffprobe=base.ffprobe,
        classification=classification,
        naming=base.naming,
        tier_model=base.tier_model,
        flags=flags_cfg,
        reporting=base.reporting,
    )

    item = {
        "relpath": "Show S01E02 720p.mkv",
        "path": str(tmp_path / "Show S01E02 720p.mkv"),
        "ffprobe": {
            "ok": True,
            "video": {"height": 720, "codec": "h264", "fps": 60},
            "overall_bitrate_bps": 10000000,
        },
    }

    name = render_name(cfg, item)
    assert "HFR" in name
    assert "LOW_BR" in name
