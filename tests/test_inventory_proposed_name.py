from pathlib import Path

from sift.inventory import build_inventory

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
    )


def test_build_inventory_includes_proposed_name(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg.paths.incoming).mkdir(parents=True)
    src_file = cfg.paths.incoming / "movie.mkv"
    src_file.write_bytes(b"0" * 1024)

    inv = build_inventory(cfg, rescan=True)
    assert isinstance(inv, dict)
    items = inv.get("items", [])
    assert len(items) == 1
    assert "proposed_name" in items[0]
    # Config provided a movie_template of "x" in this test helper, so the rendered
    # proposed_name should equal that literal template value.
    assert items[0]["proposed_name"] == "x"
