"""Reverb and tone shaping.

Uses Spotify's ``pedalboard`` (studio-grade reverb) when available, and falls
back to a small numpy Schroeder reverb so the pipeline still works without it.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer
from .config import ReverbConfig
from .util import db_to_amp


def apply_reverb(buf: AudioBuffer, cfg: ReverbConfig, wet_scale: float = 1.0) -> AudioBuffer:
    """Apply reverb. ``wet_scale`` lets a stem dial the global wet up/down."""
    wet = float(np.clip(cfg.wet * wet_scale, 0.0, 1.0))
    try:
        return _pedalboard_reverb(buf, cfg, wet)
    except Exception:
        return _schroeder_reverb(buf, cfg, wet)


def _pedalboard_reverb(buf: AudioBuffer, cfg: ReverbConfig, wet: float) -> AudioBuffer:
    from pedalboard import Pedalboard, Reverb

    board = Pedalboard([
        Reverb(
            room_size=cfg.room_size,
            damping=cfg.damping,
            wet_level=wet,
            dry_level=cfg.dry,
            width=cfg.width,
        )
    ])
    # pedalboard expects shape (channels, samples).
    x = buf.data.T
    pre = _predelay(buf.data, cfg.predelay_ms, buf.sr).T
    out = board(pre.astype(np.float32), buf.sr)
    return AudioBuffer(out.T, buf.sr)


def _predelay(x: np.ndarray, ms: float, sr: int) -> np.ndarray:
    d = int(ms / 1000.0 * sr)
    if d <= 0:
        return x
    return np.concatenate([np.zeros((d, x.shape[1]), dtype=np.float32), x], axis=0)


def _schroeder_reverb(buf: AudioBuffer, cfg: ReverbConfig, wet: float) -> AudioBuffer:
    """Classic 4-comb + 2-allpass Schroeder reverb (numpy fallback)."""
    sr = buf.sr
    x = buf.data.astype(np.float32)

    # Comb-filter delays scale with room size.
    base = np.array([1557, 1617, 1491, 1422]) / 44100.0
    comb_delays = (base * (0.5 + cfg.room_size) * sr).astype(int)
    comb_gain = 0.78 - 0.25 * cfg.damping
    allpass_delays = (np.array([225, 556]) / 44100.0 * sr).astype(int)

    pre = _predelay(x, cfg.predelay_ms, sr)
    wet_sig = np.zeros_like(pre)
    for d in comb_delays:
        wet_sig += _comb(pre, int(d), comb_gain)
    wet_sig /= len(comb_delays)
    for d in allpass_delays:
        wet_sig = _allpass(wet_sig, int(d), 0.5)

    n = max(pre.shape[0], x.shape[0])
    dry = np.zeros((n, x.shape[1]), dtype=np.float32)
    dry[:x.shape[0]] = x
    wet_full = np.zeros((n, x.shape[1]), dtype=np.float32)
    wet_full[:wet_sig.shape[0]] = wet_sig
    out = dry * cfg.dry + wet_full * wet
    return AudioBuffer(out, sr)


def _comb(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    if delay <= 0:
        return x.copy()
    y = np.zeros_like(x)
    for c in range(x.shape[1]):
        buf = np.zeros(delay, dtype=np.float32)
        idx = 0
        col = x[:, c]
        out = y[:, c]
        for i in range(len(col)):
            d = buf[idx]
            v = col[i] + d * gain
            buf[idx] = v
            out[i] = d
            idx = (idx + 1) % delay
    return y


def _allpass(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    if delay <= 0:
        return x.copy()
    y = np.zeros_like(x)
    for c in range(x.shape[1]):
        buf = np.zeros(delay, dtype=np.float32)
        idx = 0
        col = x[:, c]
        out = y[:, c]
        for i in range(len(col)):
            d = buf[idx]
            v = col[i] + d * gain
            buf[idx] = v
            out[i] = d - gain * v
            idx = (idx + 1) % delay
    return y
