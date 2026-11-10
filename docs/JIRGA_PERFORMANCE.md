# Gravity Rush 2 — performance investigation: Jirga Para Lhao

## Goal

On Fedora Linux, Ryzen 7 7735U (Radeon 680M RADV, 16 GiB shared RAM),
identify the source of frame drops in Jirga Para Lhao before changing the
Vulkan renderer. The game ordinarily targets 30 FPS, so the effective
frame budget is about **33.33 ms**. The already working local build and
saved game remain unchanged by this tool.

The renderer already implements per-window 5-second TLG_FRAME_STATS,
optional TLG_GPU_PROFILE Vulkan timestamps, and configurable draw-prep
workers (TLG_PREP_WORKERS). We use these rather than making speculative
GPU changes. GPU timestamps are *not* enabled in the baseline because
they impose measurement overhead.

## Procedure

From the repository root, after fetching the performance branch, make
a save in Jirga Para Lhao and position Kat at a repeatable viewpoint.
Close other CPU/GPU-intensive programs and keep graphics settings and
camera movement as constant as possible. Then run:

    python3 scripts/jirga_perf.py run baseline --seconds 150

The game launches normally through run_gr2.sh. The first 45 seconds
are ignored for the performance summary; they cover initial startup,
loading and some shader compilation. This is an approximate time from
process launch, not an automatic detector of arriving in Jirga.

Run a second pass with fewer draw-preparation workers:

    python3 scripts/jirga_perf.py run prep4 --seconds 150

This changes only TLG_PREP_WORKERS=4, temporarily for that launch.
The current default is 8 workers for a 16-thread CPU. Reducing them may
help memory contention on an iGPU or may decrease performance: **measure
rather than assume**. If needed also compare:

    python3 scripts/jirga_perf.py run prep2 --seconds 150

For **diagnosis only** (not directly comparable to baseline due to
timestamp overhead), get the actual GPU pass breakdown:

    python3 scripts/jirga_perf.py run gpu-profile --seconds 150

For a CPU submission-path experiment, the opt-in
drawpipe-off variant disables the draw-recording pipeline and may hurt
performance; do not treat it as a recommended graphics preset:

    python3 scripts/jirga_perf.py run drawpipe-off --seconds 150

Every run writes run.log and summary.json into a separate
port/out/perf/YYYYMMDD-HHMMSS-profile-PID/ directory.

No shader cache is cleared, no launcher setting is rewritten, and no
save file is intentionally touched by the benchmark tool. The game
itself uses its normal saves and can update them through gameplay.
Preserve a separate backup before testing modifications to the game.

To analyze existing log files without starting the game:

    python3 scripts/jirga_perf.py analyze port/out/logs/last_run.log --warmup 0

If the launcher log is stored elsewhere, use its actual path.
You can analyze multiple files in a single command by listing them.

## How we decide what to optimize

- Worst-frame time, average 5-second FPS and median per-window p99
  quantify stutters. These are not a true whole-session p99 and cannot
  tell if the scene is visually correct.
- High shader/pipeline compile counts coinciding with spikes point to
  cold shader compilation, not necessarily a persistent GPU bottleneck.
- GPU-profile pass totals near or exceeding 33.3 ms/frame point to
  GPU-side constraints (but the profiler itself has overhead).
- High draw counts and CPU-side capture, sync or queue waits may instead
  indicate CPU submission overhead or thread contention.
- If prep4 beats baseline repeatedly with identical view, investigate
  worker scheduling/overhead; if not, keep original behavior.

**Decision gate:** make a renderer optimization only after a reproducible
baseline and specific bottleneck are established; validate both visual
correctness and pacing on the same Jirga save, and compare 30 FPS areas
for regressions.

The old black-screen investigation remains separate on
fix/black-screen-f58-f59. This branch starts from upstream main and does
not merge or depend on that draft diagnostic code.
