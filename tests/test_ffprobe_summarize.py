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
