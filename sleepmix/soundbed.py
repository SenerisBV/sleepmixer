"""Sollos-style 'sound supplement' bed: colored noise + optional binaural beats.

Both layers are synthesised from scratch with numpy. Binaural beats only work
over headphones (each ear gets a slightly different carrier frequency, and the
brain perceives the difference as a low 'beat'); low beat frequencies sit in the
delta/theta range associated with sleep.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer
from .config import SoundbedConfig
from .util import db_to_amp

_EXPONENT = {"white": 0.0, "pink": -1.0, "brown": -2.0}


def colored_noise(n: int, sr: int, kind: str, rng: np.random.Generator) -> np.ndarray:
    """Generate ``n`` samples of mono colored noise via 1/f spectral shaping.

    ``power ∝ f**exponent`` — exponent 0 = white, -1 = pink, -2 = brown/red."""
    exponent = _EXPONENT.get(kind, -1.0)
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0   # avoid div-by-zero at DC
    # Amplitude scaling is power**0.5, i.e. f**(exponent/2).
    spectrum *= freqs ** (exponent / 2.0)
    y = np.fft.irfft(spectrum, n)
    peak = np.max(np.abs(y))
    if peak > 1e-12:
        y /= peak
    return y.astype(np.float32)


def binaural_beat(n: int, sr: int, carrier_hz: float, beat_hz: float) -> np.ndarray:
    """Stereo binaural tone: left = carrier, right = carrier + beat."""
    t = np.arange(n, dtype=np.float64) / sr
    left = np.sin(2 * np.pi * carrier_hz * t)
    right = np.sin(2 * np.pi * (carrier_hz + beat_hz) * t)
    return np.stack([left, right], axis=1).astype(np.float32)


def build_soundbed(duration_s: float, sr: int, cfg: SoundbedConfig,
                   rng: np.random.Generator) -> AudioBuffer:
    """Render the full stereo sound bed for the given duration."""
    n = int(duration_s * sr)
    bed = np.zeros((n, 2), dtype=np.float32)

    if cfg.noise_type and cfg.noise_type != "none":
        mono = colored_noise(n, sr, cfg.noise_type, rng) * db_to_amp(cfg.noise_gain_db)
        bed += mono[:, None]

    if cfg.binaural_enabled:
        tone = binaural_beat(n, sr, cfg.binaural_carrier_hz, cfg.binaural_beat_hz)
        bed += tone * db_to_amp(cfg.binaural_gain_db)

    return AudioBuffer(bed, sr)
