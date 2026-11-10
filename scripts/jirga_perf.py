#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""GR2 Linux performance reproduction: 5-second frametime windows and GPU-pass totals.

This tool never edits launcher settings, game data or saves. It starts the existing
runner unchanged, with a small number of optional environment-only A/B switches.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "port" / "out" / "perf"
FRAME = re.compile(r"Frame stats:\s*([\d.]+) FPS, worst frame ([\d.]+) ms.*?(\d+) draws/frame")
PACING = re.compile(r"Frame pacing: median ([\d.]+) ms, stddev ([\d.]+) ms, p99 ([\d.]+) ms")
GPU = re.compile(r"GPU profile: ([\d.]+) ms/frame over (\d+) frames, (\d+) labels")
GPU_ITEM = re.compile(r"^\s+([\d.]+) ms/frame\s+([\d.]+)/frame\s+(.+?)\s*$")
COMPILES = re.compile(r"(\d+) shader/pipeline compiles")
WORKERS = re.compile(r"GPU: draw preparation workers: (\d+)")
PIPE = re.compile(r"Draw pipe: ([\d.]+) draws/s pipelined, ([\d.]+) drains/s that waited, stage A waited ([\d.]+)%, stage B busy ([\d.]+)%")
STALL = re.compile(r"Stall: ([\d.]+) ms frame; waits: readback [\d.]+ ms, GPU ticks ([\d.]+) ms")
STALL_CPU = re.compile(r"GPU thread on CPU ([\d.]+) ms")
STALL_DRAWS = re.compile(r"\s+(\d+) draws, (\d+) dispatches")
HEAVY_DRAWS = 1000
PROFILES = {
    "baseline": {},
    "prep4": {"TLG_PREP_WORKERS": "4"},
    "prep2": {"TLG_PREP_WORKERS": "2"},
    "drawpipe-off": {"TLG_DRAW_PIPE": "0"},
    "gpu-profile": {"TLG_GPU_PROFILE": "1"},
    # Experimental: keep Vulkan timestamp instrumentation off the draw-pipe recording thread.
    # This is NOT validated as a deadlock fix, and results have different CPU scheduling.
    "gpu-profile-nopipe": {"TLG_GPU_PROFILE": "1", "TLG_DRAW_PIPE": "0"},
}


def number_stats(values):
    if not values:
        return None
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "max": round(max(values), 3),
        "mean": round(statistics.mean(values), 3),
    }


def analyze(content, skip_windows=0):
    """Extract meaningful windowed measurements; do not equate FPS with actual gameplay."""
    lines = content.splitlines()
    windows = []
    gpu_windows = []
    gpu_labels = {}
    pipes = []
    stalls = []
    all_windows = []
    current_gpu = None
    frame_count = 0
    for line_index, line in enumerate(lines):
        stall = STALL.search(line)
        if stall:
            cpu = STALL_CPU.search(lines[line_index + 2]) if line_index + 2 < len(lines) else None
            draw = STALL_DRAWS.search(lines[line_index + 3]) if line_index + 3 < len(lines) else None
            stalls.append({"frame_ms": float(stall.group(1)),
                           "gpu_ticks_ms": float(stall.group(2)),
                           "gpu_thread_cpu_ms": float(cpu.group(1)) if cpu else None,
                           "draws": int(draw.group(1)) if draw else None,
                           "dispatches": int(draw.group(2)) if draw else None})
        match = FRAME.search(line)
        if match:
            frame_count += 1
            fps, worst, draws = match.groups()
            all_windows.append({
                "window": frame_count,
                "approx_seconds": frame_count * 5,
                "fps": float(fps),
                "worst_ms": float(worst),
                "draws": int(draws),
                "shader_compiles": int(COMPILES.search(line).group(1)) if COMPILES.search(line) else None,
                "pacing_p99_ms": None,
                "pacing_stddev_ms": None,
            })
            continue
        pacing = PACING.search(line)
        if pacing and all_windows and all_windows[-1]["window"] == frame_count:
            all_windows[-1]["pacing_p99_ms"] = float(pacing.group(3))
            all_windows[-1]["pacing_stddev_ms"] = float(pacing.group(2))
            continue
        profile = GPU.search(line)
        if profile:
            avg_ms, frames, labels = profile.groups()
            current_gpu = {"ms": float(avg_ms), "frames": int(frames),
                           "labels": int(labels), "parts": []}
            gpu_windows.append(current_gpu)
            continue
        if current_gpu:
            item = GPU_ITEM.match(line)
            if item:
                ms, count, name = item.groups()
                current_gpu["parts"].append({"ms": float(ms), "count": float(count),
                                             "name": name})
                gpu_labels.setdefault(name, []).append(float(ms))
            else:
                current_gpu = None
        pipe = PIPE.search(line)
        if pipe:
            draws, drains, stage_a, stage_b = pipe.groups()
            pipes.append({"draws_per_second": float(draws),
                          "drains_per_second": float(drains),
                          "stage_a_wait_pct": float(stage_a),
                          "stage_b_busy_pct": float(stage_b)})
    # Never hide every captured window just because the user ended a run before warm-up.
    post_warmup = [w for w in all_windows if w["window"] > skip_windows]
    windows = post_warmup if post_warmup else all_windows
    fallback = bool(skip_windows and all_windows and not post_warmup)
    heavy_windows = [w for w in all_windows if w["draws"] >= HEAVY_DRAWS]
    heavy_stalls = [x for x in stalls if x["draws"] is not None and x["draws"] >= HEAVY_DRAWS]
    first = WORKERS.search(content)
    p99s = [w["pacing_p99_ms"] for w in windows if w["pacing_p99_ms"] is not None]
    return {
        "window_seconds": 5,
        "skipped_windows": skip_windows,
        "post_warmup_windows": len(post_warmup),
        "warmup_fallback_to_all_windows": fallback,
        "all_window_count": len(all_windows),
        "all_frame_windows": all_windows,
        "heavy_draw_threshold": HEAVY_DRAWS,
        "heavy_window_count": len(heavy_windows),
        "heavy_fps_windows": number_stats([w["fps"] for w in heavy_windows]),
        "heavy_draws_windows": number_stats([w["draws"] for w in heavy_windows]),
        "heavy_frame_windows": heavy_windows,
        "heavy_stall_count": len(heavy_stalls),
        "heavy_gpu_ticks_ms": number_stats([x["gpu_ticks_ms"] for x in heavy_stalls]),
        "heavy_gpu_cpu_ms": number_stats([x["gpu_thread_cpu_ms"] for x in heavy_stalls if x["gpu_thread_cpu_ms"] is not None]),
        "heavy_stalls": heavy_stalls,
        "freeze_reported": "FREEZE: no frame for" in content,
        "window_count": len(windows),
        "fps_5s_windows": number_stats([w["fps"] for w in windows]),
        "worst_frame_ms_windows": number_stats([w["worst_ms"] for w in windows]),
        "p99_ms_windows": number_stats(p99s),
        "draws_per_frame_windows": number_stats([w["draws"] for w in windows]),
        "below_29_5_fps_windows": sum(w["fps"] < 29.5 for w in windows),
        "frame_windows": windows,
        "gpu_profile_windows": len(gpu_windows),
        "gpu_ms_per_frame": number_stats([g["ms"] for g in gpu_windows]),
        "gpu_expensive_labels": [
            {"name": name, "mean_ms_per_frame": round(statistics.mean(ms), 3),
             "windows": len(ms)}
            for name, ms in sorted(gpu_labels.items(),
                                   key=lambda kv: statistics.mean(kv[1]), reverse=True)[:12]
        ],
        "draw_pipeline_windows": pipes,
        "prep_workers": int(first.group(1)) if first else None,
        "errors": [line[:260] for line in lines if line.startswith("STOP:")][:10],
        "notice": ("All timing windows are approximate 5-second periods from process start. "
                   "GPU profile adds overhead, and FPS is not visual proof. "
                   "Compare runs in the same scene with the same camera/view and a warm cache."),
    }


def report(summary):
    label = summary.get("label", "log")
    data = summary["analysis"]
    print("\nScene performance:", label)
    print("Measured 5-second windows:", data["window_count"],
          "| post-warmup:", data["post_warmup_windows"],
          "| all:", data["all_window_count"])
    if data["warmup_fallback_to_all_windows"]:
        print("  WARNING: run ended before configured warm-up; using ALL captured windows.")
    for key in ("fps_5s_windows", "worst_frame_ms_windows", "p99_ms_windows",
                "draws_per_frame_windows", "gpu_ms_per_frame"):
        v = data[key]
        print("  {:26s} {}".format(key, "n/a" if not v else
               "median={} min={} max={}".format(v["median"], v["min"], v["max"])))
    print("  below 29.5 FPS:", data["below_29_5_fps_windows"],
          "| prep workers:", data["prep_workers"])
    print("  heavy scene (>={}) windows: {}; FPS: {}; median GPU ticks: {} ms; GPU-thread CPU: {} ms".format(
        data["heavy_draw_threshold"], data["heavy_window_count"],
        "n/a" if not data["heavy_fps_windows"] else data["heavy_fps_windows"]["median"],
        "n/a" if not data["heavy_gpu_ticks_ms"] else data["heavy_gpu_ticks_ms"]["median"],
        "n/a" if not data["heavy_gpu_cpu_ms"] else data["heavy_gpu_cpu_ms"]["median"]))
    if data["freeze_reported"]:
        print("  WARNING: FREEZE report found; a profiler hang is not a valid GPU performance sample.")
    if data["gpu_expensive_labels"]:
        print("  GPU passes (ranked by average ms/frame, sampled with profiling overhead):")
        for item in data["gpu_expensive_labels"][:8]:
            print("    {:6.3f}ms {}".format(item["mean_ms_per_frame"], item["name"][:100]))
    if not data["window_count"]:
        print("  No frame samples found: check the game has run with TLG_FRAME_STATS=1.")
    print("  Note: 30 FPS alone does NOT prove the game is rendering visibly.")


def run_case(profile, seconds, warmup, label=None):
    if profile not in PROFILES:
        raise ValueError("Invalid profile: " + profile)
    session = OUT / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" +
                     profile + "-" + str(os.getpid()))
    session.mkdir(parents=True)
    env = dict(os.environ)
    for key in ("TLG_WAIT_STATS", "TLG_WAIT_ACTIVE", "TLG_TRACE_SEMA",
                "TLG_PREP_WORKERS", "TLG_DRAW_PIPE", "TLG_GPU_PROFILE"):
        env.pop(key, None)
    env["TLG_FRAME_STATS"] = "1"
    env.update(PROFILES[profile])
    log_path = session / "run.log"
    print("GR2 scene benchmark: {} ({}s)".format(profile, seconds), flush=True)
    print("Use the SAME Jirga Para Lhao viewpoint for each run. Saved launcher configuration is unchanged.", flush=True)
    print("Log:", log_path, flush=True)
    with open(log_path, "w", encoding="utf-8") as out:
        proc = subprocess.run(["bash", str(ROOT / "run_gr2.sh"), str(seconds)],
                              cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result = {
        "label": label or profile,
        "profile": profile,
        "settings": {key: env.get(key) for key in
                     ("TLG_FRAME_STATS", "TLG_GPU_PROFILE", "TLG_PREP_WORKERS",
                      "TLG_DRAW_PIPE", "TLG_UPSCALER", "TLG_OUTPUT_RES")},
        "duration_seconds": seconds,
        "warmup_seconds": warmup,
        "exit_code": proc.returncode,
        "log": str(log_path),
        "analysis": analyze(text, skip_windows=warmup // 5),
    }
    summary = session / "summary.json"
    summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    report(result)
    print("\nShare summary.json and run.log from:", session)
    return proc.returncode if proc.returncode not in (0, 124) else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    launch = sub.add_parser("run", help="launch one controlled performance variant")
    launch.add_argument("profile", choices=list(PROFILES))
    launch.add_argument("--seconds", type=int, default=150)
    launch.add_argument("--warmup", type=int, default=45)
    launch.add_argument("--label", default=None)
    analyze_cmd = sub.add_parser("analyze", help="analyze one or more existing run.log files")
    analyze_cmd.add_argument("logs", nargs="+", type=Path)
    analyze_cmd.add_argument("--warmup", type=int, default=45)
    args = p.parse_args(argv)
    if args.command == "run":
        if not 30 <= args.seconds <= 900:
            p.error("seconds must be between 30 and 900")
        if not 0 <= args.warmup < args.seconds:
            p.error("warmup must be smaller than seconds")
        return run_case(args.profile, args.seconds, args.warmup, args.label)
    if args.warmup < 0:
        p.error("warmup must be nonnegative")
    for path in args.logs:
        content = path.read_text(encoding="utf-8", errors="replace")
        report({"label": str(path), "analysis": analyze(content, args.warmup // 5)})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit("Performance tool: " + str(error))
