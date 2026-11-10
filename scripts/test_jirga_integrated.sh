#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Zero-watchdog same-save GPU/HLE A/B tester. Quit the game normally to summarize.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mode=${1:-full}
case "$mode" in
  baseline) wave32=0; vertex=0; fragment=0; bind=0 ;;
  shaders)  wave32=1; vertex=1; fragment=1; bind=0 ;;
  full)     wave32=1; vertex=1; fragment=1; bind=1 ;;
  -h|--help)
    cat <<'HELP'
Usage: bash scripts/test_jirga_integrated.sh [baseline|shaders|full]
baseline = GPU experiments off, AvPlayer/HLE fix still on
shaders  = fragment wave32 and pre-raster+fragment CSE, bind cache off
full     = wave32, both CSE shader passes, Vulkan pipeline bind cache
Quit GR2 normally. No 90-second watchdog is used.
Logs are written to ~/jirga-integration-{mode}-{date}.log
HELP
    exit 0 ;;
  *) echo "Unknown mode $mode (use baseline|shaders|full)" >&2; exit 2 ;;
esac
[[ -x "$root/port/out/tlg-probe" ]] || { echo "Game binary missing; build first" >&2; exit 1; }
[[ -f "$root/port/out/gpu/libtlggpu.so" ]] || { echo "GPU library missing; build first" >&2; exit 1; }
log="$HOME/jirga-integration-${mode}-$(date +%Y%m%d-%H%M%S).log"
printf 'Mode: %s | wave32=%s | vertex CSE=%s | fragment CSE=%s | GPU bind cache=%s\n' \
  "$mode" "$wave32" "$vertex" "$fragment" "$bind"
printf 'Log file: %s\nPlay the SAME crowd camera view, then quit the game normally.\n' "$log"

cd "$root"
set +e
env -u TLG_GPU_PROFILE -u TLG_WAIT_ACTIVE -u TLG_WAIT_STATS -u TLG_TRACE_SEMA \
  TLG_FS_WAVE32="$wave32" TLG_GFX_CSE_VERTEX="$vertex" \
  TLG_GFX_CSE_FRAGMENT="$fragment" TLG_GPU_BIND_CACHE="$bind" \
  TLG_FUSED_DRAW_BINDS=0 TLG_TEXTURE_SET_EXACT=0 TLG_VK_RECORD_THREAD=1 \
  TLG_FRAMES_AHEAD=1 TLG_PREP_WORKERS=8 TLG_FRAME_STATS=1 \
  bash "$root/run_gr2.sh" 0 2>&1 | tee "$log" | \
  grep --line-buffered -E 'Frame stats:|Frame pacing:|GPU draw bind cache:|GPU IR CSE:|GPU: TLG_FS_WAVE32|HLE thread: join failed|Could not stop playback: already stopped|FREEZE:|STOP:'
pipe_status=("${PIPESTATUS[@]}")
set -e
python3 - "$log" <<'PY'
import re
import statistics
import sys
from pathlib import Path

data = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
pattern = re.compile(r"Frame stats:\s*([\d.]+)\s*FPS,[^\n]*?(\d+)\s*draws/frame")
windows = [(float(fps), int(draws)) for fps, draws in pattern.findall(data)]
heavy = [(fps, draws) for fps, draws in windows if draws >= 3500]
print(f"\nFrame-stat windows: {len(windows)}; crowded (>=3500 draws/frame): {len(heavy)}")
if heavy:
    print(f"Crowded median: {statistics.median(fps for fps, _ in heavy):.2f} FPS, "
          f"{statistics.median(draws for _, draws in heavy):.0f} draws/frame")
else:
    print("No crowded windows captured; visit a dense crowd.")
for label, token in (
    ("HLE join failures", "HLE thread: join failed"),
    ("AvPlayer repeated-stop warnings", "Could not stop playback: already stopped"),
    ("Freeze diagnostic", "FREEZE:"),
    ("Watchdog triggered", "STOP: watchdog timeout"),
):
    print(f"{label}: {data.count(token)}")
lines = [line for line in data.splitlines() if "GPU draw bind cache:" in line]
if lines:
    print("Last GPU bind-cache report:", lines[-1].strip())
print(f"Log: {sys.argv[1]}")
PY
exit "${pipe_status[0]}"
