# Black screen after the Sony logo (issues #58 / #59)

**Status: investigating; no confirmed gameplay fix.** This branch preserves the stock launcher,
GPU options, audio, controllers, mods and save handling. Instrumentation is off by default.

## Evidence

On Fedora Linux with an AMD Radeon 680M (RADV REMBRANDT), CUSA03694 update
01.11 successfully initializes Vulkan, loads the game modules, and presents
approximately 30 FPS with 18 draws/frame after the Sony splash, but stays black.
Reproducing it with `tlg-probe` directly makes a GUI-launcher-only problem unlikely.
Multiple thread dumps show guest worker threads inside `pthread_cond_wait`.
The stock `TLG_WAIT_STATS=1` output reports waits **after completion** and can
be quiet when a thread stays blocked; silence alone cannot prove deadlock.

Related upstream reports: [#58](https://github.com/HayatoG/gr2_pc/issues/58) and
[#59](https://github.com/HayatoG/gr2_pc/issues/59). The `AvPlayer` warning
"already stopped" and zero audio samples may be symptoms, not causes.

## New diagnostics (opt in)

Build this branch using the upstream Linux instructions:

```bash
cd port
TLG_LTO=OFF TLG_PGO=off bash build.sh
```

Use the **modified** `out/tlg-probe` with the matching library and generated
game image; do not swap a single binary into an unrelated release. To exercise
the stock launcher/runner path from a source checkout, return to the repository
root and run:

```bash
TLG_WAIT_STATS=1 TLG_WAIT_ACTIVE=1 ./run_gr2.sh 40 \
  > "$HOME/gr2-active-waits.log" 2>&1
```

This runner reads the usual saved launcher settings. Alternatively, set the two
variables on the command that starts the source-build `tlg-probe`.

Every five seconds, alongside stock completed-wait stats, the runtime prints:

- `Runtime: active waits (TLG_WAIT_ACTIVE, >=1000 ms)`, with the thread name,
  OS TID, wait duration, object handle, descriptive name and guest frame pointer.
- `Runtime: pending semaphores (TLG_WAIT_ACTIVE)`, with the semaphore ID,
  token count, maximum, queued waiter count and first requested token count.

These lines are **observational only**: no guest wakeup, timeout or semaphore
contract is changed. `TLG_WAIT_ACTIVE` needs `TLG_WAIT_STATS=1`; neither is
enabled by default. The semaphore snapshot is capped at 32 lines per interval.

The saved logs may contain local paths; remove personal paths before attaching
them to a public bug report.

## Interpreting the result

A durable `DrawThread` or main-thread wait with an increasing duration and a
stable semaphore ID is a lead, **not by itself proof of faulty semaphore code**.
The next step is to cross-reference that ID with signaling calls, event flags,
and the guest call site. Do not force-post semaphores to bypass the stall.

Rebuild and compare with unmodified upstream at the exact same game version and
source revision. Validate on the affected Fedora/RADV host, then verify
Windows/Linux build checks and launcher, audio, input, saves and mods before
calling any subsequent change a fix. No proprietary game or firmware data
belongs in this repository.

## Compare locally built and packaged executables

See [the safe three-way Linux A/B experiment](BLACK_SCREEN_AB_EXPERIMENT.md). It rebuilds the stock C runtime using the same toolchain and GPU library as the working fork and separately checks the exact pinned official Linux release. The test is observational and does not establish a fix by itself.
