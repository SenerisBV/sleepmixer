"""Time-stretching and pitch-shifting (the 'slowed' half of slowed-and-reverb).

Prefers Rubber Band (via ``pyrubberband``, requires the ``rubberband`` CLI) for
formant-aware, artefact-free stretching. Falls back to librosa's phase vocoder,
and finally to plain resampling — which couples speed and pitch together, a
lo-fi result that happens to suit the aesthetic anyway.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer


def slow_and_pitch(buf: AudioBuffer, speed: float, pitch_semitones: float) -> AudioBuffer:
    """Slow to ``speed`` (fraction of original) and shift pitch independently.

    ``speed=0.7`` makes the clip 1/0.7 ≈ 1.43x longer; ``pitch_semitones=-2``
    drops it two semitones."""
    speed = max(float(speed), 0.05)
    try:
        return _rubberband(buf, speed, pitch_semitones)
    except Exception:
        try:
            return _librosa_stretch(buf, speed, pitch_semitones)
        except Exception:
            return _resample_fallback(buf, speed, pitch_semitones)


def _rubberband(buf: AudioBuffer, speed: float, semitones: float) -> AudioBuffer:
    import pyrubberband as pyrb

    # pyrubberband works on (n,) or (n, channels); rate>1 speeds up, so to slow
    # down we pass rate=speed (<1).
    y = pyrb.time_stretch(buf.data, buf.sr, speed)
    if abs(semitones) > 1e-6:
        y = pyrb.pitch_shift(y, buf.sr, semitones)
    return AudioBuffer(np.asarray(y, dtype=np.float32), buf.sr)


def _librosa_stretch(buf: AudioBuffer, speed: float, semitones: float) -> AudioBuffer:
    import librosa

    cols = []
    for c in range(buf.n_channels):
        ch = np.ascontiguousarray(buf.data[:, c])
        ch = librosa.effects.time_stretch(ch, rate=speed)
        if abs(semitones) > 1e-6:
            ch = librosa.effects.pitch_shift(ch, sr=buf.sr, n_steps=semitones)
        cols.append(ch)
    m = min(len(c) for c in cols)
    out = np.stack([c[:m] for c in cols], axis=1)
    return AudioBuffer(out.astype(np.float32), buf.sr)


def _resample_fallback(buf: AudioBuffer, speed: float, semitones: float) -> AudioBuffer:
    """Speed and pitch coupled (varispeed). semitones is folded into the rate."""
    from scipy.signal import resample

    rate = speed * (2.0 ** (semitones / 12.0))
    n_out = int(round(buf.n_frames / rate))
    out = resample(buf.data, n_out, axis=0)
    return AudioBuffer(np.asarray(out, dtype=np.float32), buf.sr)
