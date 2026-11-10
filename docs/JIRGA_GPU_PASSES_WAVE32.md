# Jirga Para Lhao — GPU-first performance experiment (RDNA2 / Radeon 680M)

## Evidence and scope

The real 90-second `jirga-fused-on.log` showed:
- Seven 5-second windows with >3,500 draws/frame at **12.0–18.3 FPS**
  (median ~13.4 FPS).
- Across 100 heavy-frame stall reports (>3,500 draws), median
  **54.45 ms** waiting for GPU ticks vs **0.2 ms** recorder wait.
- No shader compilations in the heavy-frame windows.
- `STOP: watchdog timeout` at the end of the timed run, not by itself
  evidence of a shader error or GPU crash.

`GPU ticks` is the **host wait for GPU timeline progress**, NOT
the execution time of vertex/fragment shader stages. We need actual GPU
timestamps before optimizing a specific pass. Prior experiments mostly
reduced CPU-side work and did not provide 30 FPS in dense crowds.

## Changes

### 1. GPU-side: fragment shader wave32, opt-in

`TLG_FS_WAVE32=1` requests a Vulkan subgroup size of **32** on
**fragment shaders only**, provided the physical device supports
`subgroupSizeControl`, size 32 within min/max, and the fragment stage in
`requiredSubgroupSizeStages`.

To reduce compatibility risk, the port only selects fragment shader
metadata declaring **no lane ID, quad/shuffle/ballot or subgroup mask
operations**. This is conservative, but shader metadata cannot guarantee
that every shader is safe to switch. The compute pipelines are **not**
changed (they depend on the emulated guest wave64 semantics). All other
stages retain their original wave64 setting.

The feature is OFF by default. The first eligible shader logs a line
starting `GPU: TLG_FS_WAVE32=1 enabled on eligible fragment pipelines`.
If that line does not appear, this A/B likely selected no shaders.
The change modifies *how GPU fragment instructions execute*; it does
not remove NPCs, draw calls or textures. It can help, hurt or leave FPS
unchanged. **Watch for any rendering errors and switch it OFF if seen.**

AMD GPUOpen explains that native RDNA wave32 and wave64 have distinct
occupancy and resource behaviors:
https://gpuopen.com/learn/occupancy-explained/

The Vulkan restriction on supported stage, feature and size:
https://docs.vulkan.org/refpages/latest/refpages/source/VkPipelineShaderStageCreateInfo.html

### 2. GPU-pass timestamps no longer block the Vulkan submission thread

The original `TLG_GPU_PROFILE=1` used
`vkGetQueryPoolResults(... VK_QUERY_RESULT_WAIT_BIT)`. On a previous
Radeon run it froze after 18 frames; the GPU submit thread may have
waited on a timestamp that hadn't even been submitted.

The profiler now **polls** older slices without the WAIT bit and keeps
pending slices in flight until all of their results are ready. It
never resets/reuses a pending query slice. The aim is to collect
per-pass measurements without that deadlock; this does **not** prove
that every other source of profiler hangs has been eliminated.

The log will contain lines such as:

    GPU profile: 45.00 ms/frame over 60 frames, 7 labels
      20.000 ms/frame  3.0/frame pass 1920x1080 [...] depth ... vs ... ps ...

The labels identify exact guest vertex/fragment shader hashes, color
attachment formats and dimensions, allowing focused GPU rendering
optimizations instead of speculative CPU tuning.

**Profiler overhead:** timestamps may split rendering scopes and
increase frame time. Do NOT compare FPS between a profiled run and an
unprofiled baseline, and do not treat a list of passes as a hardware
pipeline-stage breakdown (GPU geometry vs pixel time needs RGP or
more specific counters).

## Controlled test on the affected laptop

Close GR2, then back up the working executable+GPU library:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-gpu-profile
    cp -a port/out/tlg-probe port/out/backup-before-gpu-profile/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-gpu-profile/

Get the new branch, build only after GitHub CI passes:

    git fetch origin
    git switch --track origin/perf/jirga-gpu-pass-profile
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

Test the same crowded Jirga viewpoint and camera, with FSR and
diagnostic captures kept consistent. A first wave32 launch may compile
new driver variants: repeat with warm caches to compare.

**Control (original wave64 fragment shaders):**

    TLG_FS_WAVE32=0 ./run_gr2.sh 90 > "$HOME/jirga-wave64.log" 2>&1

**New GPU execution variant:**

    TLG_FS_WAVE32=1 ./run_gr2.sh 90 > "$HOME/jirga-wave32.log" 2>&1

For a **separate**, profiled wave64 run only after confirming normal
gameplay still renders:

    TLG_FS_WAVE32=0 TLG_GPU_PROFILE=1 ./run_gr2.sh 90 > "$HOME/jirga-gpu-passes.log" 2>&1

To see what was sampled:

    grep -E '^GPU profile:|^  +[0-9]+\.[0-9]+ ms/frame|FREEZE:' "$HOME/jirga-gpu-passes.log"

Check visuals, effects, NPCs and load/save. If the experimental
wave32 output has artifacts, disable it immediately:

    TLG_FS_WAVE32=0 ./run_gr2.sh

The old binary pair can be restored after closing the game:

    cp -a port/out/backup-before-gpu-profile/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-gpu-profile/libtlggpu.so port/out/gpu/libtlggpu.so

## Decision gate

- If wave32 speeds up the same scene **and** visuals are correct,
  identify which FS shader hashes matter and add per-shader opt-in.
- If one or two pass labels account for most GPU time, target their
  shaders, draw geometry or attachment traffic.
- If GPU time is mostly between submissions, investigate GPU barriers,
  residency and memory transfers before changing more shaders.
- If 30 FPS is not observed, report it accurately. Neither the flag nor
  the profiler is a proven 30 FPS fix.

This branch contains PR #6's previously unmerged CPU hot-path changes,
but not the unproven texture-cache PR #4. The GPU wave32 and profiler
changes can be compared independently using the environment flags.
