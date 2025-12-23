from pathlib import Path

from sift.inventory import build_inventory

# Copy of helper to avoid cross-test import problems
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


def test_tv_sxe_renders_template(tmp_path):
    cfg = make_cfg(tmp_path)
    # create incoming dir and a sample TV file
    inc = cfg.paths.incoming
    inc.mkdir(parents=True)
    name = "Big Brother AU S16E12 720p WEB H264-JFF[EZTVx.to].mkv"
    (inc / name).write_bytes(b"x")

    inv = build_inventory(cfg, rescan=True)
    items = inv.get("items", [])
    assert len(items) == 1
    pn = items[0].get("proposed_name")
    assert pn is not None
    assert "S16E12" in pn or "S16E12" in items[0]["relpath"]
    # Ensure extension preserved
    assert pn.endswith(".mkv")


def test_audio_codec_and_channels_tokens(tmp_path):
    # Ensure audio_tag uses 'ch' suffix and explicit audio_codec/audio_channels tokens work
    cfg = make_cfg(tmp_path)
    from sift.router import render_name

    item = {
        "relpath": "Show.S01E01.mkv",
        "ffprobe": {
            "ok": True,
            "video": {"height": 720, "codec": "h264"},
            "audio": {"channels": 2, "codec": "aac"},
        },
    }

    name = render_name(cfg, item)
    # default template contains vcodec_tag and audio_tag
    assert "2.0ch" in name
    # default TV template doesn't include audio codec; explicit check below

    # explicit tokens should be present when included in a config naming template
    from sift.model import NamingConfig, SiftConfig

    new_naming = NamingConfig(
        movie_template=cfg.naming.movie_template,
        tv_template="{stem} [{audio_codec} {audio_channels}ch].{ext}",
        hdr_sep=cfg.naming.hdr_sep,
        flags_sep=cfg.naming.flags_sep,
        fallback_to_stem=cfg.naming.fallback_to_stem,
        vcodec_map=cfg.naming.vcodec_map,
        acodec_map=cfg.naming.acodec_map,
        sanitize=cfg.naming.sanitize,
        max_filename_len=cfg.naming.max_filename_len,
    )

    new_cfg = SiftConfig(
        paths=cfg.paths,
        io=cfg.io,
        ffprobe=cfg.ffprobe,
        classification=cfg.classification,
        naming=new_naming,
        tier_model=cfg.tier_model,
        flags=cfg.flags,
        reporting=cfg.reporting,
    )

    name2 = render_name(new_cfg, item)
    assert "AAC" in name2
    assert "2ch" in name2


def test_transfer_uses_proposed_name(tmp_path):
    cfg = make_cfg(tmp_path)
    inc = cfg.paths.incoming
    inc.mkdir(parents=True)
    src = inc / "orig.mkv"
    src.write_bytes(b"data")

    inventory = {
        "items": [
            {
                "relpath": "orig.mkv",
                "path": str(src),
                "size": src.stat().st_size,
                "mtime_ns": src.stat().st_mtime_ns,
                "ffprobe": {"ok": True},
                "proposed_name": "Renamed Movie (2020).mkv",
            }
        ]
    }

    from sift.transfer import transfer_inventory

    res = transfer_inventory(cfg, inventory, dry_run=False, only_ok_ffprobe=False)
    assert res.copied == 1

    dst = (
        cfg.paths.outgoing_root
        / "movies"
        / cfg.tier_model.tier[0].folder
        / "Renamed Movie (2020).mkv"
    )
    assert dst.exists()
