"""Source character: a light "where was this found" texture on a voiced passage.

Applied to the raw provider take by `voicing.render_character`, never to paid
audio in place. Every recipe is subtle and every value below is a PLACEHOLDER
(recorded in docs/project-state.md) to tune by ear. Deterministic per seed.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt


KINDS = ("tape", "room", "oldmic", "hum", "clean")

# PLACEHOLDERS
TAPE_WOW_HZ, TAPE_WOW_CENTS = 0.4, 3.0
TAPE_FLUTTER_HZ, TAPE_FLUTTER_CENTS = 7.0, 1.0
TAPE_HISS_DB = -52.0           # white-noise RMS, dBFS
TAPE_LOWPASS_HZ = 7000.0
ROOM_DECAY_S = 0.4             # time for the reverb tail to fall 60 dB
ROOM_WET = 0.15                # wet share of the output energy (wet / (dry + wet))
ROOM_VOICE_BAND_HZ = (100.0, 4000.0)  # where the 15% is measured
ROOM_DAMP_HZ = 5000.0          # the tail is a little darker than the voice
OLDMIC_BAND_HZ = (150.0, 5000.0)
OLDMIC_DRIVE = 1.3
HUM_HZ = 50.0
HUM_DB = -55.0                 # each of the fundamental, 2nd and 3rd harmonic
HUM_FADE_S = 0.005             # fade-in so the hum has no step at sample 0


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
    """A small room: the dry voice plus a short, dark, exponentially decaying noise tail.

    Not `sleepmix.effects` reverb: pedalboard's tail cannot get shorter than
    ~0.6 s to -60 dB and its wet/dry gains are not in energy terms, so the
    "small room, 0.4 s, 15% wet" spec could not be met. This impulse response
    is exact: amplitude -60 dB at ROOM_DECAY_S, and its energy is set so the
    tail is ROOM_WET of the output energy across the voice band. Level is not
    compensated (it rises ~0.7 dB); `normalise` sets it afterwards.
    """
    n = int(ROOM_DECAY_S * sr)
    t = np.arange(n) / sr
    # flat-magnitude random-phase noise (a plain noise IR has a Rayleigh-random
    # response, so a held vowel could land on a hot or dead bin), then the decay
    ph = np.exp(2j * np.pi * rng.random(n // 2 + 1))
    ph[0] = 1
    ir = np.fft.irfft(ph, n) * np.exp(-np.log(1000) * t / ROOM_DECAY_S)
    ir = sosfilt(butter(1, ROOM_DAMP_HZ, "low", fs=sr, output="sos"), ir)
    # scale so the tail's mean power gain over the voice band is wet/(1-wet)
    H = np.abs(np.fft.rfft(ir, 1 << 17)) ** 2
    f = np.fft.rfftfreq(1 << 17, 1 / sr)
    band = (f >= ROOM_VOICE_BAND_HZ[0]) & (f <= ROOM_VOICE_BAND_HZ[1])
    ir *= np.sqrt(ROOM_WET / (1 - ROOM_WET) / H[band].mean())
    return x + fftconvolve(x.astype(np.float64), ir)[: len(x)]


def _oldmic(x, sr, rng):
    # The bandpass takes a few dB off broadband input, so the recipe matches RMS
    # to its input to stay level-neutral on its own; `normalise` sets the final level.
    y = np.tanh(OLDMIC_DRIVE * x.astype(np.float64)) / OLDMIC_DRIVE
    return _match_rms(sosfilt(butter(2, OLDMIC_BAND_HZ, "band", fs=sr, output="sos"), y), x)


def _hum(x, sr, rng):
    t = np.arange(len(x)) / sr
    h = sum(np.sin(2 * np.pi * HUM_HZ * k * t + rng.uniform(0, 2 * np.pi))
            for k in (1, 2, 3)) * _db(HUM_DB)
    fade = min(int(HUM_FADE_S * sr), len(x))
    h[:fade] *= 0.5 * (1 - np.cos(np.pi * np.arange(fade) / max(fade, 1)))
    return x + h


_RECIPES = {"tape": _tape, "room": _room, "oldmic": _oldmic, "hum": _hum}
_PREFIX = {"tape": "TAPE_", "room": "ROOM_", "oldmic": "OLDMIC_", "hum": "HUM_"}


def character_params(kind: str) -> dict:
    """The recipe constants `kind` uses right now, by name (tuples as lists so
    the dict round-trips through JSON). Recorded in each manifest, so a
    rendered file says exactly which tuning made it."""
    if kind == "clean":
        return {"kind": "clean"}
    if kind not in _RECIPES:
        raise ValueError(f"unknown source character '{kind}' (one of {', '.join(KINDS)})")
    g = globals()
    out: dict = {"kind": kind}
    for name in sorted(n for n in g if n.startswith(_PREFIX[kind]) and n.isupper()):
        v = g[name]
        out[name] = list(v) if isinstance(v, tuple) else v
    return out


def apply_character(x: np.ndarray, sr: int, kind: str, seed: int) -> np.ndarray:
    """Texture mono float32 `x`; same length out. `clean` returns it unchanged."""
    x = np.asarray(x, dtype=np.float32)
    if kind == "clean":
        return x
    if kind not in _RECIPES:
        raise ValueError(f"unknown source character '{kind}' (one of {', '.join(KINDS)})")
    rng = np.random.default_rng(seed)
    return np.asarray(_RECIPES[kind](x, sr, rng), dtype=np.float32)
