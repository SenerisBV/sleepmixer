"""The 'disintegration' engine — the Basinski-flavoured part.

A single seamless loop is repeated many times to fill the target duration. On
each repetition the loop is degraded a little more, with the amount of decay
interpolated from the stem's ``*_start`` to ``*_end`` settings across the whole
mix. Because stems are processed independently, you can let the vocal dissolve
into reverb-ghosts while the harmonic bed stays (almost) intact — the thing you
can't do to a finished stereo master.

All processing here is plain numpy/scipy, so it runs without any ML deps.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .audio import AudioBuffer
from .config import StemDecayConfig
from .looping import equal_power_crossfade
from .util import db_to_amp, iteration_rng, lerp, shape_progress


def _lowpass(x: np.ndarray, cutoff_hz: float, sr: int) -> np.ndarray:
    """Zero-phase Butterworth lowpass applied per channel."""
    nyq = sr * 0.5
    cutoff = float(np.clip(cutoff_hz, 20.0, nyq * 0.99))
    if cutoff >= nyq * 0.98:
        return x
    sos = signal.butter(4, cutoff / nyq, btype="low", output="sos")
    return signal.sosfiltfilt(sos, x, axis=0).astype(np.float32)


def _apply_dropouts(x: np.ndarray, density: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Punch brief, smoothly-ramped gaps into the signal (tape dropouts)."""
    if density <= 0:
        return x
    n = x.shape[0]
    gap = max(int(0.05 * sr), 1)           # ~50 ms gaps
    n_gaps = int(density * n / gap)
    if n_gaps <= 0:
        return x
    env = np.ones(n, dtype=np.float32)
    ramp = max(int(0.005 * sr), 1)          # 5 ms in/out ramp to avoid clicks
    win = np.hanning(ramp * 2)
    for _ in range(n_gaps):
        start = int(rng.integers(0, max(n - gap, 1)))
        seg = slice(start, start + gap)
        env[seg] = 0.0
        env[start:start + ramp] = win[:ramp][::-1]
        tail = slice(start + gap - ramp, start + gap)
        env[tail] = win[:ramp]
    return x * env[:, None]


def _spectral_holes(x: np.ndarray, fraction: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Zero a random (but fixed-per-call) subset of frequency bins.

    The same bin mask is held across the whole loop so it reads as 'missing
    frequencies' rather than noise."""
    if fraction <= 0:
        return x
    nper = 1024
    f, t, Z = signal.stft(x, fs=sr, nperseg=nper, axis=0)
    n_bins = Z.shape[0]
    mask = rng.random(n_bins) > fraction          # True = keep
    Z = Z * mask[:, None, None]
    _, xrec = signal.istft(Z, fs=sr, nperseg=nper, time_axis=-1, freq_axis=0)
    # istft may return a slightly different length; trim/pad to match.
    xrec = np.moveaxis(xrec, -1, 0)
    out = np.zeros_like(x)
    m = min(out.shape[0], xrec.shape[0])
    out[:m] = xrec[:m]
    return out.astype(np.float32)


def apply_decay(
    loop: AudioBuffer,
    progress: float,
    decay: StemDecayConfig,
    rng: np.random.Generator,
) -> AudioBuffer:
    """Return ``loop`` degraded to the level implied by ``progress`` (0..1)."""
    if not decay.enabled or progress <= 0:
        return loop.copy()

    p = shape_progress(progress, decay.curve)
    x = loop.data.astype(np.float32)
    sr = loop.sr

    # 1. High-frequency erosion.
    cutoff = lerp(decay.lowpass_start_hz, decay.lowpass_end_hz, p)
    x = _lowpass(x, cutoff, sr)

    # 2. Spectral holes (missing frequencies).
    frac = lerp(decay.spectral_hole_start, decay.spectral_hole_end, p)
    x = _spectral_holes(x, frac, sr, rng)

    # 3. Dropouts.
    density = lerp(decay.dropout_start, decay.dropout_end, p)
    x = _apply_dropouts(x, density, sr, rng)

    # 4. Amplitude fade.
    gain = db_to_amp(lerp(decay.amp_start_db, decay.amp_end_db, p))
    x = x * gain

    # 5. Rising noise floor (tape hiss).
    noise_amp = db_to_amp(lerp(decay.noise_start_db, decay.noise_end_db, p))
    if noise_amp > 1e-6:
        x = x + rng.standard_normal(x.shape).astype(np.float32) * noise_amp

    return AudioBuffer(x, sr)


def plan_iterations(
    loop_frames: int, target_frames: int, crossfade_ms: float, sr: int
) -> tuple[int, int]:
    """Return ``(n_iterations, xfade_frames)`` for a stream of this shape.

    Shared by the batch stream builder and the preview path so both agree on
    which iteration a given point in the arc corresponds to."""
    xfade = min(int(crossfade_ms / 1000.0 * sr), loop_frames // 2)
    stride = max(loop_frames - xfade, 1)
    n_iter = int(np.ceil((target_frames - xfade) / stride)) + 1
    return max(n_iter, 1), xfade


def decayed_iteration(
    loop: AudioBuffer,
    iteration: int,
    n_iterations: int,
    decay: StemDecayConfig,
    seed: int,
    stem: str,
) -> AudioBuffer:
    """The loop as it sounds on repetition ``iteration`` of ``n_iterations``."""
    progress = iteration / max(n_iterations - 1, 1)
    return apply_decay(loop, progress, decay, iteration_rng(seed, stem, iteration))


def build_disintegrating_stream(
    loop: AudioBuffer,
    target_frames: int,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
    cancel=None,
) -> AudioBuffer:
    """Repeat ``loop`` until ``target_frames`` is reached, degrading each pass.

    Successive iterations are joined with an equal-power crossfade so cycle
    boundaries don't click. Each iteration's randomness is derived from
    ``(seed, stem, iteration)`` so any single iteration can be reproduced in
    isolation — see ``util.iteration_rng``."""
    sr = loop.sr
    ch = loop.n_channels
    loop_len = loop.n_frames
    n_iter, xfade = plan_iterations(loop_len, target_frames, crossfade_ms, sr)

    out = np.zeros((target_frames + loop_len, ch), dtype=np.float32)
    pos = 0
    for i in range(n_iter):
        if cancel is not None:
            cancel.check()
        chunk = decayed_iteration(loop, i, n_iter, decay, seed, stem).data
        if pos == 0:
            out[:loop_len] += chunk
            pos = loop_len
        else:
            start = pos - xfade
            a = out[start:start + xfade]
            b = chunk[:xfade]
            out[start:start + xfade] = equal_power_crossfade(a, b)
            end = start + loop_len
            out[start + xfade:end] += chunk[xfade:]
            pos = end
        if pos >= target_frames:
            break

    return AudioBuffer(out[:target_frames], sr)
