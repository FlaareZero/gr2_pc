# Jirga Para Lhao — GPU shader ALU deduplication (pre-raster + fragment)

This branch builds on PR #7's validated-in-log fragment wave32 experiment.
It does **not** include the unproven texture-set reuse from PR #4 or the
visually broken direct-command recorder experiment.

## Hardware and evidence

Fedora Linux, Ryzen 7 7735U / Radeon 680M, 16 GiB system memory:

| Workload | Prior fused draw | Fragment wave32 |
|---|---:|---:|
| Frame-stat windows with >=3500 draws/frame | 7 | 11 |
| Median FPS | 13.4 | 18.4 |
| Median draws/frame | 5204 | 6130 |
| Median GPU-tick wait in heavy stalls | 54.45 ms | 34.05 ms |

The game log confirms \`TLG_FS_WAVE32=1\` was actually selected for at
least one fragment pipeline. These sessions **are not paired screenshots
or identical scene snapshots**; the apparent improvement is promising,
not a controlled proof. GPU ticks measure a host wait, not execution
time inside an individual GPU shader.

## Actual GPU code-generation optimization

\`shader_recompiler/recompiler.cpp\` now optionally performs an *exact,
basic-block-local* common-subexpression elimination (CSE) pass on the
compiler IR immediately before emitting SPIR-V. This removes redundant
pure arithmetic that a shader would otherwise need to execute.

- \`TLG_GFX_CSE_VERTEX=1\`: vertex, geometry and tessellation shaders.
- \`TLG_GFX_CSE_FRAGMENT=1\`: fragment shaders.
- \`TLG_FS_WAVE32=1\`: retains PR #7's fragment subgroup optimization
  for shaders without declared lane/subgroup operations.

The CSE pass only touches a **whitelist** of pure 32-bit arithmetic,
selected float operations, vector construction/extraction and selects.
Only instructions with identical opcode, operands, flags and definition
are merged, and only within the **same straight-line basic block**.
After this, dead-code elimination removes the now-unused instruction.
It does NOT change textures, memory accesses, exports, barriers,
subgroup semantics, control flow, per-instance coordinates, NPCs,
geometry topology, guest draw calls, animation, or render targets.

Both CSE toggles default OFF. They are also fields in
\`Shader::Profile\`, so the binary shader cache recognizes that the
SPIR-V has changed. Switching options invalidates that cache and
will cause cold shader compilation; *a warm-up run is essential*.
The log prints a few \`GPU IR CSE:\` lines, including how many redundant
instructions were removed. An individual shader may have 0 eliminations:
performance improvement is not guaranteed, and the GPU driver may
already deduplicate some identical SPIR-V operations.

### Why not wave32 in geometry?

The device reports \`requiredSubgroupSizeStages=0xf0\`, which includes
fragment but **not** the vertex/geometry/tessellation stages. Forcing
a required 32-lane subgroup size there would violate Vulkan stage
capability requirements. The pre-raster optimization is instead
instruction elimination, independent of wave size.

## Safe compilation

Close GR2. Back up the working binary and GPU shared library:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-gfx-cse
    cp -a port/out/tlg-probe port/out/backup-before-gfx-cse/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-gfx-cse/

Then, **after the Linux/Windows CI build is green**:

    git fetch origin
    git switch --track origin/perf/jirga-vertex-fragment-cse
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

If the build fails, do not use the new GPU shared library. Keep the
saved working pair.

## One combined A/B test

First run the **wave32 control** in the same crowded Jirga Para Lhao
save/camera, with the other two optimizations off:

    TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=0 TLG_GFX_CSE_FRAGMENT=0 \
      ./run_gr2.sh 90 > "$HOME/jirga-gpu-control.log" 2>&1

Now test **all three GPU features together**:

    TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=1 TLG_GFX_CSE_FRAGMENT=1 \
      ./run_gr2.sh 90 > "$HOME/jirga-gpu-both-first.log" 2>&1

This first combined run may be affected by cold pipeline-cache builds.
Run **exactly the same combined mode again** to measure with warm cache:

    TLG_FS_WAVE32=1 TLG_GFX_CSE_VERTEX=1 TLG_GFX_CSE_FRAGMENT=1 \
      ./run_gr2.sh 90 > "$HOME/jirga-gpu-both-warm.log" 2>&1

Check the actual graphics in the densest square: NPC bodies, shadows,
transparent surfaces, particles, textures, physics, animation, UI and
input should all behave normally. A CSE improvement must be evaluated
using the same ~6000-draw viewpoint and heavy-window median/p99
frametimes. **Do not enable TLG_GPU_PROFILE** for FPS A/B: it inserts
timestamps and may split rendering scopes.

Summarize the CSE activity:

    grep -E 'GPU IR CSE:|Frame stats:|Frame pacing:|FREEZE:|STOP:' \
      "$HOME/jirga-gpu-both-warm.log"

If something looks wrong, both CSE features can be disabled at launch,
without recompilation:

    TLG_GFX_CSE_VERTEX=0 TLG_GFX_CSE_FRAGMENT=0 TLG_FS_WAVE32=1 ./run_gr2.sh

For a complete binary rollback with GR2 closed:

    cp -a port/out/backup-before-gfx-cse/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-gfx-cse/libtlggpu.so port/out/gpu/libtlggpu.so

## What the data will decide

If the pre-raster and fragment passes report actual eliminated IR
instructions but performance remains identical, it means the driver
already optimizes the redundant expressions or GPU time is dominated
by something else (geometry count, memory access, full-screen pass
shaders, render-target traffic, GPU timeline barriers).
The nonblocking \`TLG_GPU_PROFILE=1\` profiling implementation is
available from PR #7 to identify expensive per-pass labels in a
**separate** run; it still needs visual and freeze validation on this
Radeon GPU.

We do **not** claim 30 FPS or any specific gain before the combined
in-game A/B and correctness checks succeed.
