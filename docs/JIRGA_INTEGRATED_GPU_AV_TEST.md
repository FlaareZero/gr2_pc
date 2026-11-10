# Integrated Gravity Rush 2 test: GPU optimization + HLE/AvPlayer

Branch: `integration/gpu-avplayer-test`  
Draft PR: https://github.com/FlaareZero/gr2_pc/pull/12

## Included vs deliberately excluded

**Included in this single build:**

- Fragment wave32 on supported shaders (`TLG_FS_WAVE32`).
- Exact pre-raster and fragment arithmetic CSE (`TLG_GFX_CSE_VERTEX`,
  `TLG_GFX_CSE_FRAGMENT`).
- Vulkan graphics pipeline bind cache (`TLG_GPU_BIND_CACHE`).
- AvPlayer decoder queue wakeup on EOF, a single owner for thread
  join/detach, and silence for benign repeated Stop calls.
- Existing nonblocking Vulkan profiler fixes (NOT enabled in gameplay).

**Not included/enabled:** texture registry cache experimental reuse,
direct Vulkan recorder, 2-frame GPU queues, or in-game GPU profiling.
These previously either did not help or produced graphical regressions.

**Important:** the `baseline` option below is a toggle-off control
within this build. The binary still contains previously compiled
scheduler optimizations from PR #3/#6, and the AV fix. It is not the
unmodified original game executable.

## Back up, then compile

Close the game. Do not compile if another instance still uses the GPU
library. From the Fedora fork clone:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-integration
    cp -a port/out/tlg-probe port/out/backup-before-integration/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-integration/

Once the [combined Linux/Windows CI](https://github.com/FlaareZero/gr2_pc/actions)
is green for the current PR #12 head:

    git fetch origin
    git switch --track origin/integration/gpu-avplayer-test
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

If a local tracking branch already exists, use:

    git switch integration/gpu-avplayer-test
    git pull --ff-only origin integration/gpu-avplayer-test

Avoid deleting shader caches. A new CSE/wave32 profile may compile
fresh GPU pipelines; allow warm-up before comparing crowded areas.

## Playable controlled test (no watchdog)

Run these commands **one after another**. For each, start from the
same save, face the same crowded location in Jirga Para Lhao, spend
at least 30 seconds with >=3500 draws/frame, and quit normally. The
wrapper supplies launcher argument `0` (the watchdog is disabled).

    bash scripts/test_jirga_integrated.sh baseline
    bash scripts/test_jirga_integrated.sh shaders
    bash scripts/test_jirga_integrated.sh full

`baseline`: the three GPU experiments off, HLE/AV fix still installed.

`shaders`: wave32 + pre-raster/fragment shader CSE, pipeline bind cache
OFF; most promising known GPU shader combination.

`full`: shader combination + Vulkan duplicate pipeline bind
suppression. **This is the combined performance candidate** and may
be visually unverified until tested on the target machine.

The script writes separate timestamped logs under
`~/jirga-integration-<mode>-YYYYMMDD-HHMMSS.log`, prints frame-stat
lines while the game runs, and reports the median FPS and median
draw count for windows with >=3500 draws/frame on exit. It also counts
`HLE thread: join failed`, repeated AvPlayer stop warnings and
unexpected STOP/FREEZE lines.

For the first smoke run, launch only `full` if you prefer a short
check. Afterwards `baseline` and `shaders` distinguish whether
wave32/CSE and/or the pipeline bind cache are responsible for a change.

**Do not append `90` to the normal launcher for this test:** the
`--timeout 90` flag invokes an intentional SIGALRM/stack dump on
Linux. `STOP: watchdog timeout` in such a timed capture does NOT by
itself mean Vulkan deadlocked.

## AV correctness checks

In addition to FPS, test a gameplay section that plays a video:
- Movie reaches natural EOF, then game resumes.
- Video can be interrupted/skipped if the game permits it.
- Repeated interaction with a cinematic/menu playback path does not
  hang, crash or leave audio running after playback.
- On exit no new `HLE thread: join failed` messages appear.

The automated HLE smoke test exercises decoder EOF, requested stop
and repeated cleanup **without PS4 game assets**. Passing automated
tests cannot establish actual game/runtime correctness. The previous
`Thread::Join` Linux finished-then-detach workaround is retained to
avoid breaking historical guest callback scheduling; this PR removes
the AvPlayer self/concurrent joins, not the workaround itself.

## Rollback

If shader artifacts or crashes appear, close the game. Switch to the
`baseline` option for GPU-feature-level rollback without rebuilding:

    bash scripts/test_jirga_integrated.sh baseline

To fully restore the original compiled executable and GPU library:

    cd ~/Scaricati/gr2-debug
    cp -a port/out/backup-before-integration/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-integration/libtlggpu.so port/out/gpu/libtlggpu.so

Do not rerun `build.sh` on the integration branch after restoring
the originals, or it will recompile the experimental version.

## Interpretation and limitations

- FPS/frametimes should only be compared for closely matched crowd
  draw counts and camera position, not idle or menu intervals.
- The shader optimizer can generate fresh SPIR-V, so first-run pipeline
  compilation may distort results. Repeat warm-cache captures.
- Skipped Vulkan pipeline binds are real GPU-driver packet reductions
  but do not reduce vertex/fragment *work* or promise 30 FPS.
- This integration is currently **experimental** and must stay in a
  draft PR until cross-platform CI, natural movie EOF and real crowded
  gameplay are verified.
