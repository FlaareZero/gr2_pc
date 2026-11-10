# Gravity Rush 2 black-screen: controlled Fedora build comparison

## What is verified

The official Linux release v2026.10.24-a2e69a1 was reported to stay black
after the Sony logo on AMD Radeon 680M / RADV REMBRANDT (Fedora, game
CUSA03694 update 01.11). A full locally compiled build of this fork instead
reached gameplay, including audio, input, and loading, with debugging OFF.

The fork differs from upstream only by read-only wait instrumentation and
diagnostic tooling. The change in behavior may be related to compiler,
dependencies, packaged libraries, caches/user data, timing, or something
else. **It has not been shown that the diagnostic patch fixes the game.**

## Run the automated comparison safely

From the existing fork checkout (already compiled and run successfully):

    cd ~/Scaricati/gr2-debug
    python3 port/tools/gr2_ab_compare.py

The script:

1. Rebuilds only the *original* runtime C code from commit a2e69a1 into
   port/out/tlg-probe-stock, linking against the *same locally compiled*
   Vulkan GPU library and dependencies as the working fork. It does NOT
   rebuild the large C++ GPU core.
2. Downloads the original release archive from HayatoG/gr2_pc at the
   exact 24 October 2026 tag. The published release SHA-256 is checked
   before any downloaded executable is launched. Only the runtime,
   GPU library and bundled dependencies are extracted.
3. Launches fork-local, stock-local, and upstream-release for 45 seconds
   each. All receive the same prepared image/content/patches and the same
   launcher-derived settings and game files, but separate fresh user
   directories and independent cold shader caches.
4. Saves three run logs and a JSON report inside
   port/out/ab-tests/YYYYMMDD-HHMMSS-PID/.

Do **not** remove or replace port/out/tlg-probe, port/user or the
existing game directory. This comparison does not modify them.

Because only the independent temporary dirs contain test save data,
your existing saves remain untouched. The test may start without your
progress: do not infer that game load/save integration is broken on that
basis. The official archive downloads about 80 MB.

## Options

If you have already downloaded the official release into the tool cache:

    python3 port/tools/gr2_ab_compare.py --offline

To skip the locally recompiled stock runtime:

    python3 port/tools/gr2_ab_compare.py --skip-stock --seconds 30

To test only the working fork under fresh user data:

    python3 port/tools/gr2_ab_compare.py --skip-release --skip-stock

If the game folder is not set in the launcher, pass TLG_GAME_DIR as an
environment variable; it will be applied identically to all cases.

## Interpret the result

| Fork local | Stock local | Official package | Likely next investigation |
| --- | --- | --- | --- |
| Works | Works | Black | Prebuilt toolchain, library bundling, RPATH, stripped binary |
| Works | Black | Black | Instrumentation changes binary/timing despite inactive flags |
| Works | Works | Works | Old installation, cache/config differences, intermittent freeze |
| Black | Black | Black | New empty user directory, common content or environment |

These are hypotheses, not conclusions. Every run must be observed
**visually**; 30 FPS can still indicate a black screen. The report's
audio decoding and file read counters are supporting evidence only.

When the experiment ends, record which variant visibly reached gameplay,
then attach the generated summary.json and, if appropriate, the three
run.log files in this conversation. Logs can contain user-specific paths,
so review them before posting publicly.

## Scope and safeguards

- Python and shell tests live in port/tests and a dedicated GitHub Actions
  workflow. No proprietary GR2 or console data are needed in CI.
- The official release tag and SHA-256 are pinned; any mismatch aborts
  before execution. The script extracts only required files.
- The existing .github/workflows/build.yml is unchanged. It already has
  Linux and Windows PR build jobs, but Actions might require enabling
  on a newly forked repository.
- No automatic release is published before we identify and reproduce a
  meaningful fix on the affected hardware.
