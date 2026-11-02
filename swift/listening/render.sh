#!/bin/bash
# Regenerates the listening set (Plan 7a waves, Plan 7b soft-mallet chimes and low warmth): ten
# 60-second WAVs, seed 1, into this folder.
# Each nightctl line (path, RMS, peak, centroid) is kept in measurements.txt.
# The WAVs and measurements.txt are git-ignored; this script is the record.
#
#   ./render.sh                 (from anywhere)
#   swift run -c release nightctl audition <scene> --seconds 60 --play    (to vary one by ear)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/.."
swift build -c release --product nightctl >/dev/null
nightctl="$(swift build -c release --show-bin-path)/nightctl"
: > "$here/measurements.txt"

run() { # name, then nightctl options
  local name="$1"; shift
  "$nightctl" audition "$scene" --seconds 60 --seed 1 "$@" --out "$here/$name.wav" | tee -a "$here/measurements.txt"
}

# Waves (Plan 7a), unchanged.
scene=waves
run "waves-plain"
run "waves-mid"       --distance 0.5 --slowness 0.5
run "waves-far"       --distance 1 --slowness 1 --fragmentation 0.6 --proportion 0.8
run "waves-nochannel" --no-channel

# Soft-mallet chimes (Plan 7b). The old chimes-plain/mid/far bells no longer exist.
scene=chimes
run "chimes-soft-plain"
run "chimes-soft-sleepy"    --ring 1 --softness 1
run "chimes-soft-deep"      --ring 1 --softness 1 --vibrato 1 --distance 0.6 --slowness 0.5
run "chimes-soft-nochannel" --no-channel

# Low warmth (Plan 7b).
scene=warmth
run "warmth-plain"
run "warmth-nochannel" --no-channel
