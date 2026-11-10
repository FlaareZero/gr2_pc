#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parent / "jirga_perf.py"
SPEC = importlib.util.spec_from_file_location("jirga_perf", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class PerfTests(unittest.TestCase):
    def test_frame_windows_and_gpu_passes(self):
        log = (
            "GPU: draw preparation workers: 8 (+1 scanner, 16 hardware threads)\n"
            "Frame stats: 28.1 FPS, worst frame 88.2 ms (vblank 60 Hz); "
            "5 shader/pipeline compiles, 6.5 ms; async: 1 ms, 4 ms, 0 ms; "
            "792 draws/frame\n"
            "Frame pacing: median 33.33 ms, stddev 5.21 ms, p99 65.9 ms\n"
            "GPU profile: 24.50 ms/frame over 120 frames, 2 labels\n"
            "   12.000 ms/frame  1.0/frame  expensive lighting\n"
            "    7.250 ms/frame  2.0/frame  opaque geometry\n"
            "Frame stats: 30.0 FPS, worst frame 34.0 ms (vblank 60 Hz); "
            "0 shader/pipeline compiles, 0 ms; 500 draws/frame\n"
            "Frame pacing: median 33.33 ms, stddev 0.4 ms, p99 33.6 ms\n"
        )
        data = mod.analyze(log)
        self.assertEqual(data["window_count"], 2)
        self.assertEqual(data["prep_workers"], 8)
        self.assertEqual(data["frame_windows"][0]["shader_compiles"], 5)
        self.assertEqual(data["frame_windows"][0]["pacing_p99_ms"], 65.9)
        self.assertEqual(data["below_29_5_fps_windows"], 1)
        self.assertEqual(data["gpu_expensive_labels"][0]["name"], "expensive lighting")
        self.assertEqual(data["gpu_ms_per_frame"]["median"], 24.5)

    def test_warmup_skips_initial_frames(self):
        log = ("Frame stats: 15 FPS, worst frame 200 ms; 100 draws/frame\n"
               "Frame pacing: median 50 ms, stddev 10 ms, p99 100 ms\n"
               "Frame stats: 30 FPS, worst frame 33.3 ms; 200 draws/frame\n"
               "Frame pacing: median 33.3 ms, stddev 0 ms, p99 33.3 ms\n")
        data = mod.analyze(log, skip_windows=1)
        self.assertEqual(data["window_count"], 1)
        self.assertEqual(data["fps_5s_windows"]["median"], 30.0)
        self.assertEqual(data["frame_windows"][0]["pacing_p99_ms"], 33.3)

    def test_no_false_positive_from_menu(self):
        data = mod.analyze("GPU ready; 30 FPS", skip_windows=0)
        self.assertEqual(data["window_count"], 0)
        self.assertIsNone(data["gpu_ms_per_frame"])

    def test_profiles_have_no_persistent_settings(self):
        self.assertEqual(mod.PROFILES["baseline"], {})
        self.assertEqual(mod.PROFILES["prep4"]["TLG_PREP_WORKERS"], "4")
        self.assertNotIn("TLG_UPSCALER", mod.PROFILES["baseline"])


if __name__ == "__main__":
    unittest.main()
