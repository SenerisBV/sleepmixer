"""Waveform summary for display.

A UI drawing a waveform needs a few thousand min/max pairs, not forty megabytes
of samples. Computing them here means the browser receives a small JSON array
instead of decoding an entire WAV to scan it.

Min *and* max are kept rather than absolute peak so the drawn waveform stays
signed — an asymmetric signal looks asymmetric, which is a real cue when you are
picking a loop region by eye.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer


def compute_peaks(buf: AudioBuffer, buckets: int = 2000) -> list[list[float]]:
    """Return ``buckets`` ``[min, max]`` pairs across the whole buffer."""
    buckets = max(int(buckets), 1)
    if buf.n_frames == 0:
        return [[0.0, 0.0] for _ in range(buckets)]

    mono = buf.to_mono().data[:, 0]
    # Bucket boundaries by index rather than a reshape, so a buffer that does
    # not divide evenly (or is shorter than `buckets`) still yields one pair per
    # bucket instead of dropping the remainder.
    edges = np.linspace(0, mono.shape[0], buckets + 1).astype(int)
    out: list[list[float]] = []
    for i in range(buckets):
        lo, hi = edges[i], edges[i + 1]
        if hi <= lo:
            # Fewer frames than buckets: repeat the nearest sample rather than
            # emitting an empty bucket.
            lo = min(lo, mono.shape[0] - 1)
            hi = lo + 1
        segment = mono[lo:hi]
        out.append([float(segment.min()), float(segment.max())])
    return out
