"""Source character: a light "where was this found" texture on a voiced passage.

Applied to the raw provider take by `voicing.render_character`, never to paid
audio in place. Every recipe is subtle and every value below is a PLACEHOLDER
(recorded in docs/project-state.md) to tune by ear. Deterministic per seed.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from ..audio import AudioBuffer
from ..config import ReverbConfig
from ..effects import apply_reverb

KINDS = ("tape", "room", "oldmic", "hum", "clean")

# PLACEHOLDERS
TAPE_WOW_HZ, TAPE_WOW_CENTS = 0.4, 3.0
TAPE_FLUTTER_HZ, TAPE_FLUTTER_CENTS = 7.0, 1.0
TAPE_HISS_DB = -52.0           # white-noise RMS, dBFS
TAPE_LOWPASS_HZ = 7000.0
ROOM_CONFIG = ReverbConfig(room_size=0.3, damping=0.6, wet=0.15, dry=0.85,
                           width=1.0, predelay_ms=0.0)   # ~0.4 s decay, 15% wet
OLDMIC_BAND_HZ = (150.0, 5000.0)
OLDMIC_DRIVE = 1.3
HUM_HZ = 50.0
HUM_DB = -55.0                 # each of the fundamental, 2nd and 3rd harmonic


def _db(db: float) -> float:
    return 10 ** (db / 20)


def _match_rms(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Scale `y` to `x`'s overall RMS, so a filter or reverb does not change level."""
    ry = np.sqrt(np.mean(np.square(y, dtype=np.float64)))
    rx = np.sqrt(np.mean(np.square(x, dtype=np.float64)))
    return y * (rx / ry) if ry > 0 and rx > 0 else y


def _modulate(x: np.ndarray, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Wow and flutter as a time-varying read position (smooth, clickless).

    A pitch deviation of c cents at f Hz is a delay of amplitude
    (2**(c/1200) - 1) / (2*pi*f) seconds.
    """
    n = np.arange(len(x), dtype=np.float64)
    t = n / sr
    delay = np.zeros_like(t)
    for hz, cents in ((TAPE_WOW_HZ, TAPE_WOW_CENTS), (TAPE_FLUTTER_HZ, TAPE_FLUTTER_CENTS)):
        amp = (2 ** (cents / 1200) - 1) / (2 * np.pi * hz)
        delay += amp * np.sin(2 * np.pi * hz * t + rng.uniform(0, 2 * np.pi))
    return np.interp(n - delay * sr, n, x.astype(np.float64))


def _tape(x, sr, rng):
    y = _modulate(x, sr, rng)
    y = sosfilt(butter(2, TAPE_LOWPASS_HZ, "low", fs=sr, output="sos"), y)
    return y + rng.standard_normal(len(y)) * _db(TAPE_HISS_DB)


def _room(x, sr, rng):
    out = apply_reverb(AudioBuffer(x, sr), ROOM_CONFIG).data[:, 0]
    out = out[: len(x)]
    return _match_rms(np.pad(out, (0, len(x) - len(out))), x)


def _oldmic(x, sr, rng):
    y = np.tanh(OLDMIC_DRIVE * x.astype(np.float64)) / OLDMIC_DRIVE
    return _match_rms(sosfilt(butter(2, OLDMIC_BAND_HZ, "band", fs=sr, output="sos"), y), x)


def _hum(x, sr, rng):
    t = np.arange(len(x)) / sr
    h = sum(np.sin(2 * np.pi * HUM_HZ * k * t + rng.uniform(0, 2 * np.pi))
            for k in (1, 2, 3)) * _db(HUM_DB)
    return x + h


_RECIPES = {"tape": _tape, "room": _room, "oldmic": _oldmic, "hum": _hum}


def apply_character(x: np.ndarray, sr: int, kind: str, seed: int) -> np.ndarray:
    """Texture mono float32 `x`; same length out. `clean` returns it unchanged."""
    x = np.asarray(x, dtype=np.float32)
    if kind == "clean":
        return x
    if kind not in _RECIPES:
        raise ValueError(f"unknown source character '{kind}' (one of {', '.join(KINDS)})")
    rng = np.random.default_rng(seed)
    return np.asarray(_RECIPES[kind](x, sr, rng), dtype=np.float32)
