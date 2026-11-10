# GPU graphics-state deduplication — Jirga Para Lhao

## Evidence from the user-provided \`jirga-gpu-both.log\`

The 90-second combined wave32 + shader-CSE session confirms that shader
ALU deduplication is functioning but does **not** solve the crowd load:

- Five 5-second windows with >=3,500 draws/frame: median **16.6 FPS** at
  **5,651 draws/frame**.
- Four windows with >=5,000 draws/frame: median **15.45 FPS** at
  **6,092 draws/frame**.
- Two windows with >=6,000 draws/frame: median **13.9 FPS** at
  **6,592 draws/frame**.
- Median GPU-timeline wait in 67 heavy stalls: **45.5 ms**, with median
  **18.5 ms** GPU-thread CPU and **0.2 ms** recorder wait.
- 12 sampled fragment shaders removed only 40 repeated ALU IR
  instructions combined; 12 sampled pre-raster shaders removed 33.
- The GPU-pass profiler was not enabled, so the GPU-timeline wait does
  not isolate the hardware stage or render-pass cost.

The problem remains closely related to the total work of thousands of
GPU draw commands, not warm-cache shader compilation or simple raster
resolution.

## Opt-in implementation: \`TLG_GPU_BIND_DEDUP=1\`

The Vulkan command recorder now tracks the graphics pipeline and indexed
buffer state within each rendering scope:

- An identical \`vkCmdBindPipeline(GRAPHICS)\` is not re-emitted.
- An identical \`vkCmdBindIndexBuffer\` is not re-emitted if its **buffer
  handle, offset and index type** all match.
- Works on direct and indirect indexed draws and optional square/rect
  emulation.
- Does not skip or merge any guest draw or GPU shader work, change
  attachments, move any memory barriers, change shader binary or render
  geometry, or enable the artifact-producing \`crowd-direct\` mode.
- State is invalidated after \`EndRendering\`, before a new rendering
  scope, on raw command-buffer access, and upon new command buffer
  allocation. Host blit helpers using the raw scheduler command buffer
  therefore cannot leave a stale cached pipeline binding.
- The flag is **OFF by default** until compile/visual/FPS validation.
- With the flag enabled, every 256 submissions a line
  \`GPU bind dedup (256 submissions): emitted N, skipped M ...\`
  reports the **actual** removed Vulkan commands.

The GPU driver could already coalesce identical binds. A large \`M\`
does not by itself mean a significant FPS improvement. This is a
carefully scoped real GPU command-stream reduction, **not a promised
30 FPS fix**.

## Test after Linux/Windows CI succeeds

Close the game and preserve both currently working binaries:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-gpu-bind
    cp -a port/out/tlg-probe port/out/backup-before-gpu-bind/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-gpu-bind/

Compile the dedicated branch:

    git fetch origin
    git switch --track origin/perf/jirga-gpu-state-dedup
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

Use the same ~6,000-draw Jirga save/camera for the two tests and keep
both existing shader CSE and wave32 settings identical:

    TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=1 TLG_GFX_CSE_FRAGMENT=1 \
      TLG_GPU_BIND_DEDUP=0 ./run_gr2.sh 90 > "$HOME/jirga-gpu-bind-off.log" 2>&1

    TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=1 TLG_GFX_CSE_FRAGMENT=1 \
      TLG_GPU_BIND_DEDUP=1 ./run_gr2.sh 90 > "$HOME/jirga-gpu-bind-on.log" 2>&1

Run the second test again with warmed shader cache if the first new run
compiles shaders. Compare median frame time / FPS in windows with similar
draw count, and check that NPCs, the floor, shadow silhouettes,
particles, alpha blending and camera movement look identical.

Check whether redundant Vulkan binds were actually eliminated:

    grep 'GPU bind dedup' "$HOME/jirga-gpu-bind-on.log"

Note: normal gameplay may write its usual saves; this wrapper changes
no permanent settings. \`TLG_GPU_PROFILE\` should remain absent during FPS
A/B because timestamp queries can alter rendering scopes.

If artifacts are observed, disable immediately:

    TLG_GPU_BIND_DEDUP=0 ./run_gr2.sh

To restore the *entire* old compiled renderer and game binary (close
the game first):

    cd ~/Scaricati/gr2-debug
    cp -a port/out/backup-before-gpu-bind/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-gpu-bind/libtlggpu.so port/out/gpu/libtlggpu.so

## Next GPU optimization if this is not enough

The new stage-by-stage per-pass GPU timestamp profiler from PR #7 should
be run on **separate instrumentation captures** to rank expensive
vertex/geometry vs fragment-heavy draw passes by shader hashes and
render attachment dimensions. Its \`GPU profile\` output labels are per
render pass, not hardware wave/vertex/fragment stage counters.
Structural GPU optimizations such as safe geometry reuse, multi-draw
batching and overdraw reduction can then target dominant passes.
The user should not be asked to blindly remove NPCs or disable guest
draws to achieve an attractive FPS number.
