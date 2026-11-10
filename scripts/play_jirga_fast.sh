#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Gravity Rush 2: opt-in 1080p output / lower internal scene resolution for
# integrated Radeon graphics. Does NOT modify game files or permanent settings.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
usage() {
  cat <<'HELP'
Usage: bash scripts/play_jirga_fast.sh [quality|balanced|performance|native|crowd|crowd-direct] [seconds]
       bash scripts/play_jirga_fast.sh --show-config [mode]

Quality       FSR 3.1 at about 1280x720 internal -> 1920x1080 output (default)
Balanced      FSR 3.1 at about 1130x636 internal -> 1920x1080 output
Performance   FSR 3.1 at 960x540 internal -> 1920x1080 output
Native        Original native resolution and upscaler off, 1 frame ahead (A/B reference)
Crowd         Native scene with 2 queued GPU frames (CPU/GPU overlap test)
Crowd-direct  As crowd, but Vulkan recording executes on the GPU command thread

The output size follows the existing in-game settings; set 1920x1080
there before comparing. No full rebuild or shader-cache deletion required.
Expected FSR log messages: "Scene resolution: raster ..." and
"Upscaler: FSR 3 ... on". With 6000+ draws/frame this may still
be GPU-command / geometry limited; actual improvement must be measured.
HELP
}
show=false
if [[ ${1:-} == --show-config ]]; then
  show=true
  shift
fi
mode=${1:-quality}
if [[ ${1:-} == -h || ${1:-} == --help ]]; then
  usage
  exit 0
fi
case "$mode" in
  quality)     preset=1; provider=fsr3; jitter=1 ;;
  balanced)    preset=2; provider=fsr3; jitter=1 ;;
  performance) preset=3; provider=fsr3; jitter=1 ;;
  native)      preset=0; provider=off;  jitter=0 ;;
  crowd)       preset=0; provider=off;  jitter=0 ;;
  crowd-direct) preset=0; provider=off; jitter=0 ;;
  *) usage >&2; exit 2 ;;
esac
# Preserve user choice if they deliberately set jitter for an A/B experiment.
jitter=${TLG_JITTER:-$jitter}
# A conservative 4 prep workers on 16 host threads; the Jirga benchmark showed
# no universal gain from 4 vs 8, so allow explicit override.
default_workers=4
if [[ "$mode" == native || "$mode" == crowd || "$mode" == crowd-direct ]]; then default_workers=8; fi
workers=${TLG_PREP_WORKERS:-$default_workers}
# Increase GPU queue depth only for crowd experiments: the old 1-frame limit
# may serialize CPU submission with GPU execution when there are 6k+ draws.
# Does not reduce GPU work; it may help throughput or increase input latency.
frames=1
if [[ "$mode" == crowd || "$mode" == crowd-direct ]]; then frames=2; fi
frames=${TLG_FRAMES_AHEAD:-$frames}
if [[ "$frames" != 0 && "$frames" != 1 && "$frames" != 2 ]]; then
  echo "TLG_FRAMES_AHEAD must be 0, 1 or 2" >&2
  exit 2
fi
# Single threaded Vulkan command recording: diagnostic A/B for recorder contention.
recorder=${TLG_VK_RECORD_THREAD:-1}
if [[ "$mode" == crowd-direct ]]; then recorder=0; fi
if ! [[ "$workers" =~ ^([0-9]|1[0-6])$ ]]; then
  printf 'Invalid TLG_PREP_WORKERS=%s (expected 0..16)\n' "$workers" >&2
  exit 2
fi
if [[ "$show" == true ]]; then
  printf 'mode=%s\nTLG_UPSCALER=%s\nTLG_UPSCALE_PRESET=%s\nTLG_JITTER=%s\nTLG_PREP_WORKERS=%s\nTLG_FRAMES_AHEAD=%s\nTLG_VK_RECORD_THREAD=%s\n' \
         "$mode" "$provider" "$preset" "$jitter" "$workers" "$frames" "$recorder"
  exit 0
fi
if (( $# > 0 )); then shift; fi
if [[ ! -x $root/port/out/tlg-probe ]]; then
  printf 'Working game binary missing: %s\n' "$root/port/out/tlg-probe" >&2
  exit 1
fi
printf 'GR2 Jirga trial: %s (FSR %s, preset %s, jitter %s, prep workers %s, frames ahead %s, vk recorder %s)\n' \
       "$mode" "$provider" "$preset" "$jitter" "$workers" "$frames" "$recorder"
printf 'Compare in the SAME crowded scene; the original game files and launcher settings are unchanged.\n'
exec env -u TLG_GPU_PROFILE -u TLG_WAIT_ACTIVE -u TLG_WAIT_STATS \
    -u TLG_TRACE_SEMA \
    TLG_UPSCALER="$provider" TLG_UPSCALE_PRESET="$preset" \
    TLG_JITTER="$jitter" TLG_PREP_WORKERS="$workers" \
    TLG_FRAMES_AHEAD="$frames" TLG_VK_RECORD_THREAD="$recorder" \
    TLG_FRAME_STATS=1 bash "$root/run_gr2.sh" "$@"
