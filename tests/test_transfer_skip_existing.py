from pathlib import Path
import shutil

from sift.transfer import transfer_inventory

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


def test_transfer_skips_if_proposed_name_exists(tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    # Create incoming file
    src_dir = cfg.paths.incoming
    src_dir.mkdir(parents=True)
    src_file = src_dir / "movie.mkv"
    src_file.write_bytes(b"0" * 1024)

    # Create an existing file at the destination tier with same name
    tier_root = cfg.paths.outgoing_root / "movies" / cfg.tier_model.tier[0].folder
    tier_root.mkdir(parents=True)
    existing = tier_root / "movie.mkv"
    existing.write_bytes(b"processed")

    inventory = {
        "items": [
            {
                "relpath": "movie.mkv",
                "path": str(src_file),
                "size": src_file.stat().st_size,
                "mtime_ns": src_file.stat().st_mtime_ns,
                "ffprobe": {"ok": True},
            }
        ]
    }

    result = transfer_inventory(cfg, inventory, dry_run=False, only_ok_ffprobe=False)
    assert result.copied == 0
    assert result.skipped == 1
    assert result.details[0]["reason"] == "already_processed"
    assert result.details[0]["existing_path"] == str(existing)

    # cleanup
    shutil.rmtree(cfg.paths.outgoing_root)
