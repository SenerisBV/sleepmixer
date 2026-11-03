#!/usr/bin/env bash
# The Esoterica listening set: passage 1 of every voiced recording, plain and
# through the night engine's channel, so the operator can judge by ear.
#
# For each recording in esoterica/library/ that has a recording.json (unvoiced
# ones are skipped) it writes, into the git-ignored esoterica/listening/:
#   <id>-plain.wav       the rendered p01.wav (source character applied), copied
#                        untouched; not the raw provider take p01.raw.wav
#   <id>-near.wav        nightctl audition voice, --distance 0 (clear, through the AM channel)
#   <id>-far.wav         nightctl audition voice, --distance 0.6 --fragmentation 0.3
# and prints RMS / peak / centroid for each. Free: no provider, no key.
#
# Usage: esoterica/listening.sh            (renders the first SECONDS of the passage)
#        SECONDS_PER_FILE=150 esoterica/listening.sh
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
lib="$root/esoterica/library"
out="$root/esoterica/listening"
secs="${SECONDS_PER_FILE:-90}"

(cd "$root/swift" && swift build -c release --product nightctl >/dev/null)
nightctl="$root/swift/.build/release/nightctl"
mkdir -p "$out"

stats() {  # RMS / peak / centroid of a WAV, same definitions as nightctl's printout
  (cd "$root" && pipenv run python - "$1" <<'PY' 2>/dev/null
import sys, numpy as np, soundfile as sf
x, sr = sf.read(sys.argv[1], dtype="float64")
if x.ndim > 1: x = x.mean(axis=1)
rms = 20*np.log10(max(np.sqrt(np.mean(x**2)), 1e-12))
peak = 20*np.log10(max(np.max(np.abs(x)), 1e-12))
m = np.abs(np.fft.rfft(x)); f = np.fft.rfftfreq(len(x), 1/sr)
print(f"rms {rms:.1f} dB  peak {peak:.1f} dB  centroid {np.sum(f*m)/max(np.sum(m),1e-12):.0f} Hz")
PY
)
}

n=0
for dir in "$lib"/*/; do
  id="$(basename "$dir")"
  [ -f "$dir/recording.json" ] || { echo "skipped $id (not voiced)"; continue; }
  src="$dir/p01.wav"
  cp "$src" "$out/$id-plain.wav"
  echo "$id-plain.wav  $(stats "$out/$id-plain.wav")"
  "$nightctl" audition voice --file "$src" --seconds "$secs" --at 0 --distance 0 \
    --out "$out/$id-near.wav"
  "$nightctl" audition voice --file "$src" --seconds "$secs" --at 0 --distance 0.6 \
    --fragmentation 0.3 --out "$out/$id-far.wav"
  n=$((n + 1))
done
echo "$n recordings -> $out"
