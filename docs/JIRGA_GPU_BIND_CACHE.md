# Jirga: GPU graphics-pipeline bind suppression (opt-in)

## Why this experiment

The uploaded \`jirga-gpu-both.log\` on Fedora RADV Radeon 680M has:
- 17 frame-stat windows, 5 with >=3500 draws/frame.
- Median heavy-scene FPS **16.6**, including **13.5 FPS at 6533 draws/frame** and **14.3 at 6651**.
- The first 12 fragment shader CSE samples removed 40 IR instructions, and the
  first 12 pre-raster samples removed 33. These are real compiler transforms
  but not evidence of a corresponding FPS gain.
- A final \`STOP: watchdog timeout\` after the timed launch; not enough
  information alone to conclude a real GPU hang.

The next target is redundant GPU **state commands**. The rasterizer
currently emits \`vkCmdBindPipeline\` for every draw, including when the
same graphics pipeline was already bound. Vulkan permits omitting that
redundant command because pipeline binding persists between draws in
a command buffer.

## Source changes

New \`Scheduler::BindGraphicsPipeline\` function, used for both direct
and indirect indexed/non-indexed rasterizer draw callbacks. With the
opt-in \`TLG_GPU_BIND_CACHE=1\`, the Vulkan recorder suppresses an
identical graphics-pipeline bind and counts each suppression. Different
pipeline handles, including optional SquarePass pipelines, are always
bound normally. The cache is invalidated when a new command buffer is
recorded and at every new dynamic-rendering scope.

No guest draw, vertex, texture, shader, descriptor write, depth/stencil
test, or resource barrier is removed. Compute-pipeline binding is
independent and unaffected.

**Default remains OFF.** This path assumes no unrelated code binds a
different graphics pipeline directly in the same rendering scope
without notifying the scheduler. It is therefore experimental until
the native game renders correctly during movement, menus and effects.

The prior wave32 and exact shader CSE experiments remain available
and can be kept ON identically across the A/B below.

## Backup, build, A/B

With the game closed, back up the known-good binary and shared library:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-bind-cache
    cp -a port/out/tlg-probe port/out/backup-before-bind-cache/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-bind-cache/

After GitHub's **Linux and Windows build** for PR #10 is green:

    git fetch origin
    git switch --track origin/perf/jirga-gpu-pipeline-bind-cache
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

Use the same camera/viewpoint in the densest Jirga crowd:

    TLG_GPU_BIND_CACHE=0 TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=1 TLG_GFX_CSE_FRAGMENT=1 ./run_gr2.sh 90 > "$HOME/jirga-gpu-bind-off.log" 2>&1

    TLG_GPU_BIND_CACHE=1 TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=1 TLG_GFX_CSE_FRAGMENT=1 ./run_gr2.sh 90 > "$HOME/jirga-gpu-bind-on.log" 2>&1

To confirm activation:

    grep -E 'GPU draw bind cache:|Frame stats:|Frame pacing:|FREEZE:|STOP:' \
        "$HOME/jirga-gpu-bind-on.log"

If \`GPU draw bind cache: N redundant graphics pipeline binds skipped\`
shows N > 0, the optimized Vulkan path activated. This does NOT by
itself establish any FPS benefit. Repeating matched crowd segments is
necessary to avoid scene-dependent false positives.

If characters, shadows, sky, particles or other geometry corrupt,
disable \`TLG_GPU_BIND_CACHE\` immediately; no rebuild required.

Full binary rollback, with GR2 closed:

    cp -a port/out/backup-before-bind-cache/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-bind-cache/libtlggpu.so port/out/gpu/libtlggpu.so

## Real GPU work still needs profiling

Omitting redundant pipeline binds can save driver/GPU state processing
but **does not reduce the number of vertices/pixels/shader invocations**.
If FPS remains near 15, our next step is to collect per-pass timestamps
with the previously corrected Vulkan profiler (separate from FPS A/B):

    TLG_GPU_BIND_CACHE=0 TLG_FS_WAVE32=1 TLG_GPU_PROFILE=1 \
       ./run_gr2.sh 90 > "$HOME/jirga-gpu-pass-timestamps.log" 2>&1

This is a diagnostic, NOT a gameplay-performance benchmark. Rendering
scope changes caused by timestamp collection add overhead, and the
profiler still needs verification on the user's hardware.

The target is sustained 30 FPS with correct graphics; PR #10 does
not claim that target is achieved or even achievable on this GPU.
