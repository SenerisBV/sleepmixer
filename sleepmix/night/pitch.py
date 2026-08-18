"""The frequencies actually present in a piece of material.

A ghost is built from its source's own spectrum, so this answers a specific
question rather than a musicological one: *what is physically in this loop*.
Chroma or key detection would give a tidier answer and a less honest one — it
would tell you what key a listener would name, and the ghost would then sound
at notes the source may never have played.

Octave folding is what keeps the set small and useful. A bass note and its
third harmonic are the same pitch class as far as a drone is concerned, and
folding lets a ghost sound an octave away from where the source did without
inventing a pitch that was not there.

Audio in, numbers out. Nothing downstream of this module ever sees a buffer,
which is what lets ``night/sources.py`` and ``night/plan.py`` stay audio-free.
"""
from __future__ import annotations

import numpy as np

from ..audio import AudioBuffer

# The band every pitch is folded into — one octave, low enough that a drone
# built here sits under rather than over whatever else is sounding.
FOLD_LOW_HZ = 55.0
FOLD_HIGH_HZ = 110.0

# A peak must carry at least this fraction of the strongest peak's magnitude
# to count as a pitch. Below it, the "peak" is the shoulder of a real one or
# it is noise.
#
# This is the only tonality gate here. Two others were tried and dropped:
# a peak-to-median-floor ratio (fit to white noise, then failed on pink
# noise, band-limited noise, and this repo's own cached stems — see
# task-1-report.md, "Finding 1"), and spectral flatness computed over the
# in-band spectrum (a principled, standard measure, but one that reads any
# signal concentrated in a sub-band of _MIN_HZ.._MAX_HZ as "tonal" by
# construction — band-limited noise scored as more tonal than every real
# instrument tested, so it could not separate the two either). Rejecting
# noise without a pitch was never in this task's spec; it is not attempted.
MIN_PEAK_FRACTION = 0.02

# Frequencies outside this are not pitches for this purpose: below it is
# rumble and room, above it there is nothing a drone should chase.
_MIN_HZ = 40.0
_MAX_HZ = 4000.0

# Two folded pitches closer than this are the same pitch.
_MERGE_CENTS = 45.0


def _fold(hz: float) -> float:
    """Bring ``hz`` into ``[FOLD_LOW_HZ, FOLD_HIGH_HZ)`` by octaves.

    ``hz`` can be zero (silence, a DC bin), and this is also the boundary
    that any value read from an untrusted source ultimately funnels through,
    so non-finite input (NaN, +/-inf) is treated the same as "no pitch"
    rather than trusted: without this guard, a positive infinity halves
    forever and never leaves the first loop, and a NaN fails every
    comparison and falls through both loops unfolded, unnoticed, into the
    caller.
    """
    if not np.isfinite(hz) or hz <= 0:
        return 0.0
    while hz >= FOLD_HIGH_HZ:
        hz /= 2.0
    while hz < FOLD_LOW_HZ:
        hz *= 2.0
    return hz


def pitch_set(buf: AudioBuffer, max_pitches: int = 6) -> tuple[float, ...]:
    """The dominant frequencies in ``buf``, octave-folded, ascending.

    Returns an empty tuple for silence, for an empty buffer, or for material
    with no peak worth the name — all three are ordinary rather than
    exceptional, and a caller with no pitches simply has no ghost to build.
    """
    mono = buf.to_mono().data[:, 0]
    n = len(mono)
    if n < 64 or not np.any(mono):
        return ()

    windowed = mono * np.hanning(n).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, 1.0 / buf.sr)

    in_band = (freqs >= _MIN_HZ) & (freqs <= _MAX_HZ)
    spectrum = np.where(in_band, spectrum, 0.0)
    if not np.any(spectrum):
        return ()

    # A local maximum, so the shoulders of one partial do not become three.
    peaks = np.zeros(len(spectrum), dtype=bool)
    peaks[1:-1] = (spectrum[1:-1] > spectrum[:-2]) & (spectrum[1:-1] >= spectrum[2:])
    peak_idx = np.flatnonzero(peaks)
    if peak_idx.size == 0:
        return ()

    strongest = float(spectrum[peak_idx].max())
    peak_idx = peak_idx[spectrum[peak_idx] >= strongest * MIN_PEAK_FRACTION]
    if peak_idx.size == 0:
        return ()

    # Loudest first, so merging keeps the strongest of a cluster.
    peak_idx = peak_idx[np.argsort(spectrum[peak_idx])[::-1]]

    kept: list[float] = []
    for idx in peak_idx:
        if len(kept) >= max_pitches:
            break
        folded = _fold(float(freqs[idx]))
        if folded <= 0:
            continue
        if any(abs(1200.0 * np.log2(folded / k)) < _MERGE_CENTS for k in kept):
            continue
        kept.append(folded)

    return tuple(sorted(kept))
