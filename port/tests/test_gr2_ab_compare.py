#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
import importlib.util
from pathlib import Path
import io
import tarfile
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / "tools" / "gr2_ab_compare.py"
SPEC = importlib.util.spec_from_file_location("gr2_ab_compare", FILE)
ab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ab)


class ComparisonTests(unittest.TestCase):
    def test_successful_run_metrics(self):
        log = ("Frame stats: 30.2 FPS, worst frame 34.5 ms\n"
               "Runtime: Ajm batches=1561, jobs=1541, ATRAC9 frames decoded=1536\n"
               "Runtime: files opened=12, reads=6390 (903950039 bytes), writes=1\n"
               "tlg-av: VideoDecoderThread start\n"
               "tlg-av: AudioDecoderThread start\n")
        metrics = ab.metrics(log)
        self.assertEqual(metrics["fps"], "30.2")
        self.assertEqual(metrics["ajm_jobs"], 1541)
        self.assertEqual(metrics["atrac9_frames"], 1536)
        self.assertEqual(metrics["file_reads"], 6390)
        self.assertEqual(metrics["bytes_read"], 903950039)
        self.assertTrue(metrics["video_decoder_started"])

    def test_frames_alone_cannot_prove_gameplay(self):
        metrics = ab.metrics("Frame stats: 30.2 FPS, worst frame 34.5 ms\n")
        self.assertEqual(metrics["fps"], "30.2")
        self.assertIsNone(metrics["ajm_jobs"])
        self.assertFalse(metrics["video_decoder_started"])
        self.assertNotIn("gameplay_pass", metrics)

    def test_same_guest_image_and_isolated_users(self):
        argv = ab.command(Path("/a/probe"), Path("/image"), Path("/content"),
                          Path("/patches"), Path("/game"), Path("/isolated"), 40)
        self.assertEqual(argv[:2], ["/a/probe", "/image"])
        self.assertEqual(argv[argv.index("--app0") + 1], "/game")
        self.assertEqual(argv[argv.index("--user") + 1], "/isolated")
        self.assertEqual(argv[argv.index("--timeout") + 1], "40")

    def test_malicious_release_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fake.tar.gz"
            with tarfile.open(path, "w:gz") as tar:
                value = b"bad"
                member = tarfile.TarInfo("gr2-linux-x86_64/out/../evil")
                member.size = len(value)
                tar.addfile(member, io.BytesIO(value))
            with self.assertRaises(RuntimeError):
                ab.unpack_runtime(path, Path(temp) / "unpacked")


if __name__ == "__main__":
    unittest.main()
