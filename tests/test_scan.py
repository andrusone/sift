import tempfile
import unittest
from pathlib import Path

from sift.scan import scan_files


class TestScan(unittest.TestCase):
    def test_scan_filters_extensions_and_orders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "b.mkv").write_bytes(b"x")
            (root / "a.mp4").write_bytes(b"x")
            (root / "c.txt").write_text("nope", encoding="utf-8")

            paths = scan_files(root, only_ext=["mp4", ".mkv"])
            rel = [p.name for p in paths]
            self.assertEqual(rel, ["a.mp4", "b.mkv"])
