import unittest
from sift.ffprobe import summarize


class TestSummarize(unittest.TestCase):
    def test_summarize_extracts_resolution_and_codecs(self):
        ff = {
            "format": {
                "format_name": "matroska,webm",
                "duration": "10.0",
                "bit_rate": "1000",
                "size": "123",
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "avg_frame_rate": "24000/1001",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "eac3",
                    "channels": 6,
                    "sample_rate": "48000",
                    "bit_rate": "640000",
                },
            ],
        }
        s = summarize(ff)
        self.assertTrue(s["ok"])
        self.assertEqual(s["video"]["width"], 3840)
        self.assertEqual(s["video"]["height"], 2160)
        self.assertEqual(s["video"]["codec"], "hevc")
        self.assertEqual(s["audio"]["codec"], "eac3")
        self.assertEqual(s["audio"]["channels"], 6)

    def test_audio_codec_preference_selects_preferred_over_higher_channels(self):
        """When multiple audio tracks exist, prefer codec by preference list over channel count."""
        ff = {
            "format": {"format_name": "matroska,webm"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "truehd",
                    "channels": 8,
                    "sample_rate": "48000",
                    "bit_rate": None,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "eac3",
                    "channels": 6,
                    "sample_rate": "48000",
                    "bit_rate": "640000",
                },
            ],
        }
        # Without preference, should pick TrueHD (8 channels > 6 channels)
        s_no_pref = summarize(ff)
        self.assertEqual(s_no_pref["audio"]["codec"], "truehd")
        self.assertEqual(s_no_pref["audio"]["channels"], 8)

        # With preference ["eac3", "ac3", "aac", "truehd"], should pick eac3
        preference = ["eac3", "ac3", "aac", "truehd"]
        s_with_pref = summarize(ff, audio_codec_preference=preference)
        self.assertEqual(s_with_pref["audio"]["codec"], "eac3")
        self.assertEqual(s_with_pref["audio"]["channels"], 6)

    def test_audio_codec_preference_fallback_to_channels_for_unlisted(self):
        """For codecs not in preference list, fall back to channel count."""
        ff = {
            "format": {"format_name": "matroska,webm"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "flac",
                    "channels": 8,
                    "sample_rate": "48000",
                    "bit_rate": None,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "opus",
                    "channels": 2,
                    "sample_rate": "48000",
                    "bit_rate": "128000",
                },
            ],
        }
        # Both codecs unlisted - should pick by channels (flac 8ch > opus 2ch)
        preference = ["eac3", "ac3", "aac"]
        s = summarize(ff, audio_codec_preference=preference)
        self.assertEqual(s["audio"]["codec"], "flac")
        self.assertEqual(s["audio"]["channels"], 8)
