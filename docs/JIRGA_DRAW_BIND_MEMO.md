# Gravity Rush 2: eliminate redundant Vulkan draw bindings (experimental)

## Hypothesis

In crowded Jirga Para Lhao on Fedora / Radeon 680M, GR2 can issue
roughly 6,000-7,000 guest draws per frame. Earlier experiments with lower
internal resolution, additional in-flight frames and CPU-side texture
caches have not established an FPS gain: GPU-tick waits still dominate.
Do not blindly remove draws, geometry, characters or GPU barriers.

Each guest draw currently re-emits \`vkCmdBindPipeline\`, indexed draws
re-emit \`vkCmdBindIndexBuffer\`, and on devices supporting dynamic vertex
inputs the code re-emits \`vkCmdSetVertexInputEXT\`, even if the state is
exactly the same as for the previous draw.

This branch provides **opt-in Vulkan command reduction**: if the state
already bound in the same primary command buffer is *exactly identical*,
we omit only the redundant state-setting command. The actual draw,
resources, synchronization, push constants, shader, descriptors,
dynamic stencil/depth and rendering scope are unchanged.

This does **not** merge draws or reduce shader geometry work. 30 FPS
is the goal, NOT an outcome demonstrated by this patch.

## Safety: state lifetime and invalidation

The memo is owned by \`Vulkan::Scheduler\` and updated on its serialized
command-recording path, not in the guest-thread simulation.

It invalidates:
- on every freshly allocated primary command buffer;
- whenever a raw \`Scheduler::CommandBuffer()\` is requested, because
  host passes may bind pipelines/index buffers without going through
  this optimization;
- the dynamic-vertex-input memo whenever a **static vertex input**
  graphics pipeline is bound (e.g. the host depth-resample pass).
  Vulkan explicitly invalidates previous dynamic values in that case.

It tracks the host depth-resample pipeline and the guest graphics
pipeline, including any extra square-blend pipeline bind. Compute and
graphics bindings remain separate, as Vulkan defines.

The implementation is OFF by default, pending compile, visual and A/B
testing. The stats option can be enabled independently so the original
behavior gives a reference for total attempted bind calls.

## Controlled local build (keep working binary pair)

With the game closed:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-draw-bind
    cp -a port/out/tlg-probe port/out/backup-before-draw-bind/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-draw-bind/
    git fetch origin
    git switch --track origin/perf/jirga-draw-bind-memo
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

This branch starts from **upstream main**, not the earlier speculative
cache or recorder branches. The regular \`main\` build script may not
honor \`TLG_BUILD_JOBS\` as this feature was introduced on a separate
branch; if you need to constrain memory, invoke Ninja with limited jobs
according to your local build setup. Ensure the build actually succeeds
before running the new binary.

### Compare identical scenes

Capture the same crowded area, same save/camera, same resolution and
shader cache, 60-90 seconds each, preferably repeat A/B/A/B:

    TLG_DRAW_BIND_MEMO=0 TLG_DRAW_BIND_STATS=1 TLG_FRAME_STATS=1 ./run_gr2.sh 90 > "$HOME/jirga-bind-off.log" 2>&1

    TLG_DRAW_BIND_MEMO=1 TLG_DRAW_BIND_STATS=1 TLG_FRAME_STATS=1 ./run_gr2.sh 90 > "$HOME/jirga-bind-on.log" 2>&1

The new \`Vulkan draw bind memo:\` report appears every ~5 seconds,
showing \`gfx skipped S/N\`, \`index skipped S/N\`,
\`vertex-input skipped S/N\`, and \`enabled=0/1\`.
On OFF runs all skips must be zero. On ON runs, a positive skip count
confirms the new code actually suppressed redundant Vulkan commands;
it is **not itself proof of an FPS gain**. Record heavy-scene FPS and
p99 frame pacing from the same ~6,000-draw intervals and check all
textures/NPCs/shadows remain correct.

No settings or game data are rewritten by these flags. The game itself
can still autosave as normal.

### Rollback

To revert just the new optimization:

    TLG_DRAW_BIND_MEMO=0 ./run_gr2.sh

To restore the exact previous working binary pair, close the game:

    cp -a port/out/backup-before-draw-bind/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-draw-bind/libtlggpu.so port/out/gpu/libtlggpu.so

Do not rerun the build on this branch after restoring the old pair.

## Next engineering step

If the memo avoids many binds but FPS remains ~15, the bottleneck is
GPU work not driver command binding, and the next substantial project
is to identify expensive geometry passes, overdraw and redundant
attachment transitions with robust **nonblocking** timestamp profiling.
Only then attempt compatible multi-draw/instancing; naïvely batching
draw calls with different push constants, resources or draw state would
render the wrong scene.
