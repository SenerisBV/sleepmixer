"""Seamless looping primitives: equal-power crossfades and loop construction."""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer


def equal_power_crossfade(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Blend two equal-length blocks with an equal-power (sin/cos) curve.

    Equal-power (rather than linear) keeps perceived loudness constant through
    the transition, which matters for sustained pads."""
    n = a.shape[0]
    if b.shape[0] != n:
        raise ValueError("crossfade blocks must be the same length")
    t = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)[:, None]
    fade_out = np.cos(t)
    fade_in = np.sin(t)
    return (a * fade_out + b * fade_in).astype(np.float32)


def make_seamless(loop: AudioBuffer, crossfade_ms: float) -> AudioBuffer:
    """Make a clip loop on itself cleanly.

    The tail is crossfaded against a copy of the head, so when the (now shorter)
    result is repeated end-to-end there's no discontinuity at the seam."""
    sr = loop.sr
    n = loop.n_frames
    xfade = min(int(crossfade_ms / 1000.0 * sr), n // 2)
    if xfade <= 0:
        return loop.copy()
    head = loop.data[:xfade]
    tail = loop.data[-xfade:]
    blended = equal_power_crossfade(tail, head)
    body = loop.data[xfade:n - xfade]
    out = np.concatenate([blended, body], axis=0)
    return AudioBuffer(out, sr)


def concat_crossfade(segments: list[AudioBuffer], crossfade_ms: float) -> AudioBuffer:
    """Concatenate buffers, crossfading each junction by ``crossfade_ms``."""
    if not segments:
        raise ValueError("no segments to concatenate")
    sr = segments[0].sr
    ch = segments[0].n_channels
    xfade = int(crossfade_ms / 1000.0 * sr)
    out = segments[0].data.copy()
    for seg in segments[1:]:
        x = min(xfade, out.shape[0], seg.n_frames)
        if x <= 0:
            out = np.concatenate([out, seg.data], axis=0)
            continue
        out[-x:] = equal_power_crossfade(out[-x:], seg.data[:x])
        out = np.concatenate([out, seg.data[x:]], axis=0)
    return AudioBuffer(out, sr)
