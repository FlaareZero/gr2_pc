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

## Measured Fedora/RADV results — November 10, 2026

The first user captures were baseline (8 draw-preparation workers), prep4,
then gpu-profile, from the same Ryzen 7 7735U / Radeon 680M / 16 GiB host.

**Baseline:** the renderer went from ~12–15 draws/frame around 30 FPS
to 4,759–4,780 draws/frame at **4.9–4.7 FPS**.
Among 31 heavy (>1,000 draws) stall samples, median GPU ticks were
**186.5 ms** and median GPU-thread CPU time **18.5 ms**. The slow
5-second windows reported **zero shader/pipeline compiles**.

**prep4:** one heavy 5-second window had **4,930 draws/frame at 17.6 FPS**,
and another 2,536 draws/frame at 22.0 FPS. In 29 heavy stall samples,
median GPU ticks were **34.2 ms** and GPU-thread CPU time **16.4 ms**.
This is promising for thread contention, but **not** a paired
same-camera A/B result; no general FPS improvement has been proven.

**GPU profile failed before useful measurements.** With
TLG_GPU_PROFILE=1 the game displayed only 18 guest flips, then emitted
FREEZE: no frame for 10 s. The DrawThread awaited GPU idle and the
GPU-command thread was inside DrawPipe::Drain. GPU-pass samples were not
produced. This may be a profiling/draw-pipeline interaction; the cause
has not been proven. Avoid the original gpu-profile mode for now.

**Measurement bug corrected:** baseline had 10 recorded FPS windows,
prep4 had 6, but the initial parser discarded all except 1 or 0
respectively because it always excluded the first 45 seconds.
The updated script preserves raw windows, falls back when all are
excluded, and separately reports heavy draw windows and GPU tick stalls.

### Revised, scene-focused test

Start in the same Jirga Para Lhao location with a fixed camera and warm
shader cache. Run each profile until several heavy (>1,000 draw)
windows have been captured; a repeat under the same view matters more
than a nominal runtime. A 0-second excluded warm-up prevents losing
the useful early windows in a short session:

    python3 scripts/jirga_perf.py run baseline --seconds 100 --warmup 0
    python3 scripts/jirga_perf.py run prep4 --seconds 100 --warmup 0

For a separate diagnostic experiment (not FPS A/B), the newly added
gpu-profile-nopipe mode sets TLG_DRAW_PIPE=0 along with
TLG_GPU_PROFILE=1. It is **unvalidated** on the laptop and changes host
scheduling; it may still freeze. Try it only after the normal A/B:

    python3 scripts/jirga_perf.py run gpu-profile-nopipe --seconds 100 --warmup 0

Do not confuse the no-pipe profiling timings with ordinary gameplay FPS.
Preserve any FREEZE report if the profiler still stalls.

## Playable opt-in performance mode (no rebuild) — November 10, 2026

**Concrete rendering-load reduction** for Radeon 680M on crowded Jirga scenes:
the FSR 3.1 Vulkan reconstruction already in the game can present at 1080p
while shading the 3D scene internally at a lower resolution. This changes
actual GPU raster work but not the number of guest draw calls, animations,
AI, NPC counts or save data.

The new script works with the existing compiled binary and injects
temporary environment overrides; it does not change permanent launcher
settings or delete the shader cache.

From the fork's root:

    bash scripts/play_jirga_fast.sh quality

The \`quality\` preset runs ~1280x720 internal scene pixels with FSR 3.1
and 1080p output **if your configured output is 1920x1080**.
First verify the game menu's output is 1920x1080.
If performance is still poor, trade more image quality for speed:

    bash scripts/play_jirga_fast.sh balanced
    bash scripts/play_jirga_fast.sh performance

- \`balanced\`: ~1130x636 internal scene.
- \`performance\`: 960x540 internal scene.
- \`native\`: upscaler off, original 1080p scene, comparison/reference.

To confirm whether the render path actually changed, look for messages
starting \`Upscaler: FSR 3.1 available (on)\`,
\`Scene resolution: raster ...\`, and an FSR context size.

This is a *testable performance workaround*, **not yet a verified FPS
improvement**. At 6,000–7,000 draw calls/frame, reducing pixels can
only shorten pixel/fragment/depth and related GPU costs. It does NOT
remove draw submissions, and the upscaler has its own GPU cost. Its
effectiveness will be measured from the heavy crowd scene before making
it the default. FSR temporal reconstruction may show ghosting/shimmer
on moving crowds because per-object motion is disabled in this game.
If visuals are unstable, test \`TLG_JITTER=0\` or return to \`native\`.

Compare the exact same save and camera viewpoint with F10 FPS overlay,
using the benchmark logs if desired. A regular game launch with
\`bash scripts/play_jirga_fast.sh quality\` needs no 100-second timeout.
The script does not launch a background process, modify renderer files,
or rewrite user saves. Gameplay itself may update saves normally.

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

**Known issue:** the original gpu-profile mode froze before rendering gameplay on Radeon 680M. Do not use it as a performance baseline. An unvalidated no-pipe alternative is described above.

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
