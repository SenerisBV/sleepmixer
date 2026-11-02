#!/bin/bash
# Regenerates the Plan 7a listening set: eight 60-second WAVs, seed 1, into this folder.
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

for scene in chimes waves; do
  run "$scene-plain"
  run "$scene-mid"       --distance 0.5 --slowness 0.5
  run "$scene-far"       --distance 1 --slowness 1 --fragmentation 0.6 --proportion 0.8
  run "$scene-nochannel" --no-channel
done
