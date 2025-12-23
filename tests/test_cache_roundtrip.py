import tempfile
import unittest
from pathlib import Path

from sift.cache import read_cache, write_cache
from sift.model import (
    PathsConfig,
    IOConfig,
    FFProbeConfig,
    ClassificationConfig,
    NamingConfig,
    TierModelConfig,
    FlagsConfig,
    ReportingConfig,
    SiftConfig,
    TierDef,
)


def dummy_cfg(cache_dir: Path) -> SiftConfig:
    return SiftConfig(
        paths=PathsConfig(
            incoming=cache_dir, outgoing_root=cache_dir, metadata_cache=cache_dir
        ),
        io=IOConfig(mode="copy", mkdirs=True, dedupe_on_collision=True),
        ffprobe=FFProbeConfig(
            bin="ffprobe",
            args=[
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
            ],
        ),
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
            tiers=3,
            tier=[
                TierDef(id="t1", folder="tier1", description="", requires={}, flags=[])
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
            write_jsonl_report=False, report_path=cache_dir / "report.jsonl"
        ),
    )


class TestCache(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = dummy_cfg(Path(td))
            items = [
                {
                    "relpath": "a.mkv",
                    "path": "/x/a.mkv",
                    "size": 1,
                    "mtime_ns": 2,
                    "ffprobe": {"ok": True},
                }
            ]
            write_cache(cfg, items=items, errors=0)
            data = read_cache(cfg)
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["items"][0]["relpath"], "a.mkv")
