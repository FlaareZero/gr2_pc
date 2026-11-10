# Jirga Para Lhao: native Vulkan hot-path optimizations

This branch starts from upstream main. It does NOT enable the earlier
crowd-direct experiment (which introduced graphical artifacts), change
textures, remove NPCs, reorder draws, disable game features, or touch saves.

## Confirmed workload and scope

On Fedora with Ryzen 7 7735U / Radeon 680M / 16 GiB:
- 6,000–7,000 draws per frame in crowded Jirga.
- Roughly 14–16 FPS.
- Neither FSR Performance at ~540p internal nor two in-flight frames cured the slowdown.
- GPU tick waits around 44–46 ms and GPU command-thread CPU around 18–19 ms in heavy frames.

This branch tries to reduce host command recording and overbroad GPU
synchronization. It cannot guarantee 30 FPS; that requires roughly halving
overall frame time and may demand further work on the actual GPU workload.

## Changes to compiled code

1. The scheduler's RecordChunk used one virtual call to Execute and another
   virtual call to destroy every recorded closure, thousands of times per frame.
   Now a single per-concrete-type function pointer executes the closure and
   immediately runs its matching destructor. Command order/lifetime unchanged.
2. Recording queue handoff grows from 32 KiB to 64 KiB on 12+ sizing threads,
   reducing inter-thread mutex handoffs for large workloads. On smaller CPUs
   it stays 32 KiB; forced sync/submit semantics are unchanged.
   Use TLG_RECORD_BATCH_KB=32 to restore the original threshold (valid 16..96).
3. For fixed-function buffer reads, the Vulkan barrier tracker now labels the
   index, vertex-attribute and indirect-command input stages precisely, rather
   than marking every one as ALL_GRAPHICS. Shader reads/writes retain the old
   conservative scope. This is opt-out: TLG_PRECISE_BUFFER_STAGES=0 restores
   the original stage masks without rebuilding.
4. TLG_BUILD_JOBS=3 can cap local parallel compilation to three jobs on the
   16 GiB laptop. CI/build defaults are unchanged.

## Safe test (preserve the working executable)

Close the game first. From the existing fork:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-hotpath
    cp -a port/out/tlg-probe port/out/backup-before-hotpath/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-hotpath/
    git fetch origin
    git switch --track origin/perf/jirga-record-hotpath
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh

The new library replaces the previous local build but the pair of original
binaries was backed up. C++ header changes may trigger significant
incremental compilation.

Check visual correctness in the same crowd/position/camera and record
5-second frame windows with more than 6,000 draws/frame:

    cd ~/Scaricati/gr2-debug
    ./run_gr2.sh 90 > "$HOME/jirga-hotpath.log" 2>&1

If there are rendering artifacts, disable the newly narrowed barriers:

    TLG_PRECISE_BUFFER_STAGES=0 ./run_gr2.sh 90 > "$HOME/jirga-old-barriers.log" 2>&1

Compare queue overhead if needed:

    TLG_RECORD_BATCH_KB=32 ./run_gr2.sh 90 > "$HOME/jirga-old-batching.log" 2>&1

All modes preserve game configuration and saves; normal gameplay can still
write its own saves. The original code/binary pair is the definitive
control; these environment overrides do not disable the new typed thunk.

## Rollback

Close the game and copy back the original binaries:

    cd ~/Scaricati/gr2-debug
    cp -a port/out/backup-before-hotpath/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-hotpath/libtlggpu.so port/out/gpu/libtlggpu.so

Avoid running build.sh again on this branch until you intentionally want
the new optimized GPU library. Existing user data and shaders remain intact.

## Validation

A passing Linux/Windows compilation does not prove runtime correctness,
and a successful test with 30 FPS in an empty area does not validate
performance in heavy Jirga. Compare repeated captures in the same crowd
with a warm cache, inspect real gameplay, and keep this PR draft until
a reproducible improvement is measured. Do not promise 30 FPS.
