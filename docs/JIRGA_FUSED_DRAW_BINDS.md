# Jirga Para Lhao — fused Vulkan draw-bind recording (experimental)

## Why this change

The Ryzen 7 7735U / Radeon 680M host shows ~6,000–7,000 draws/frame and
~13–16 FPS in a busy Jirga Para Lhao square. Previous changes to
resolution, worker count, GPU frame queue and texture-set generation cache
did not establish a useful FPS improvement. The `crowd-direct` mode
caused graphical artifacts and is not used here.

This patch **does not change the number of GPU draws**. It reduces the
CPU-side cost of scheduling each guest draw's supporting Vulkan bind
commands. It is a narrow optimization, not a promised 30 FPS fix.

With `TLG_FUSED_DRAW_BINDS=1`:
- `vkCmdBindIndexBuffer` for *direct indexed* draws executes in the
  same deferred callback as its `vkCmdDrawIndexed`, after the usual
  resource/barrier processing. A separate recorder closure is removed.
- When dynamic vertex input is active, `vkCmdSetVertexInputEXT` and
  `vkCmdBindVertexBuffers` are recorded in one callback, preserving
  their original ordering and copied input data.
- Indirect draws use their existing code paths, and no draw is culled,
  merged or reordered. Graphics settings, shaders and synchronization
  stay unchanged.

Default is **OFF** pending visual/CI validation. The branch is based on
PR #3, not the unproven image-cache changes in PR #4.

## Compile safely

Close the game. Back up the two working binaries:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-fused
    cp -a port/out/tlg-probe port/out/backup-before-fused/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-fused/
    git fetch origin
    git switch --track origin/perf/jirga-fused-draw-binds
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

Only continue after a successful compilation.

## A/B

From the same crowded Jirga save and camera direction, with the same
graphics settings and warm caches:

    TLG_FUSED_DRAW_BINDS=0 ./run_gr2.sh 90 > "$HOME/jirga-fused-off.log" 2>&1
    TLG_FUSED_DRAW_BINDS=1 ./run_gr2.sh 90 > "$HOME/jirga-fused-on.log" 2>&1

Compare five-second windows with approximately equal draw counts.
If the same square fluctuates with camera/NPC movement, alternate
OFF/ON/OFF/ON and compare matched segments. Evaluate median/p99 frame
times, not FPS on the main menu.

Check visually that indexed world geometry, crowd characters, shadows,
effects and interactions are identical. If anything corrupts the image,
stop and set `TLG_FUSED_DRAW_BINDS=0` — no rebuild needed.

To restore the *entire* original binary pair, close the game and run:

    cp -a port/out/backup-before-fused/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-fused/libtlggpu.so port/out/gpu/libtlggpu.so

## Limits

The host's GPU tick waits can remain ~45–53 ms even after the CPU binder
is sped up; no 30 FPS claim is justified until the on-device crowd test
passes. The next major opportunity will be GPU-side draw cost: repeated
pipeline/attachment changes or geometry shader work, measured per pass
before safely batching or changing those workloads.
