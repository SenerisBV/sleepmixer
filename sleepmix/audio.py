"""Audio container plus load/save helpers.

Samples are stored as float32 in shape ``(n_frames, n_channels)`` — the same
layout libsndfile/soundfile use — so I/O is a straight pass-through.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class AudioBuffer:
    """A block of audio: float32 samples of shape ``(n_frames, n_channels)``."""

    data: np.ndarray
    sr: int

    def __post_init__(self) -> None:
        arr = np.asarray(self.data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[:, None]
        elif arr.ndim != 2:
            raise ValueError(f"audio must be 1-D or 2-D, got shape {arr.shape}")
        self.data = arr

    # -- shape helpers --------------------------------------------------
    @property
    def n_frames(self) -> int:
        return self.data.shape[0]

    @property
    def n_channels(self) -> int:
        return self.data.shape[1]

    @property
    def duration(self) -> float:
        """Length in seconds."""
        return self.n_frames / self.sr

    def copy(self) -> "AudioBuffer":
        return AudioBuffer(self.data.copy(), self.sr)

    # -- channel layout -------------------------------------------------
    def to_mono(self) -> "AudioBuffer":
        if self.n_channels == 1:
            return self.copy()
        mono = self.data.mean(axis=1, keepdims=True)
        return AudioBuffer(mono, self.sr)

    def to_stereo(self) -> "AudioBuffer":
        if self.n_channels == 2:
            return self.copy()
        if self.n_channels == 1:
            return AudioBuffer(np.repeat(self.data, 2, axis=1), self.sr)
        # Downmix >2 channels to mono, then duplicate.
        return self.to_mono().to_stereo()

    def with_channels(self, n: int) -> "AudioBuffer":
        if n == 1:
            return self.to_mono()
        if n == 2:
            return self.to_stereo()
        raise ValueError(f"unsupported channel count: {n}")


def load_audio(path: str, sr: int | None = None) -> AudioBuffer:
    """Load an audio file. If ``sr`` is given, resample to it.

    Decoding mp3/m4a/etc. relies on libsndfile's codec support (modern builds
    handle mp3); WAV/FLAC/OGG always work.
    """
    import soundfile as sf

    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    buf = AudioBuffer(data, file_sr)
    if sr is not None and sr != file_sr:
        buf = resample(buf, sr)
    return buf


def save_audio(buf: AudioBuffer, path: str, subtype: str = "PCM_24") -> None:
    """Write ``buf`` to ``path`` (format inferred from the extension)."""
    import soundfile as sf

    sf.write(path, buf.data, buf.sr, subtype=subtype)


def resample(buf: AudioBuffer, target_sr: int) -> AudioBuffer:
    """Sample-rate conversion. Prefers ``soxr`` quality, falls back to scipy."""
    if buf.sr == target_sr:
        return buf.copy()
    try:
        import soxr

        out = soxr.resample(buf.data, buf.sr, target_sr)
    except Exception:
        from scipy.signal import resample_poly
        from math import gcd

        g = gcd(buf.sr, target_sr)
        up, down = target_sr // g, buf.sr // g
        out = resample_poly(buf.data, up, down, axis=0)
    return AudioBuffer(np.asarray(out, dtype=np.float32), target_sr)


def normalize_peak(buf: AudioBuffer, peak_db: float = -1.0) -> AudioBuffer:
    """Scale so the loudest sample sits at ``peak_db`` dBFS."""
    from .util import db_to_amp

    peak = float(np.max(np.abs(buf.data))) if buf.n_frames else 0.0
    if peak < 1e-9:
        return buf.copy()
    target = db_to_amp(peak_db)
    return AudioBuffer(buf.data * (target / peak), buf.sr)


def silence(n_frames: int, n_channels: int, sr: int) -> AudioBuffer:
    return AudioBuffer(np.zeros((n_frames, n_channels), dtype=np.float32), sr)


def sum_buffers(buffers: list[AudioBuffer]) -> AudioBuffer:
    """Sum ``buffers`` at the widest channel count, padding shorter ones.

    This is the reference signal loop detection runs against, and it must be
    computed identically wherever it is needed. ``pipeline.run_pipeline`` and
    ``session.RenderSession`` both derive a loop point from it; if their two
    summations differed by so much as a channel-mapping order, the preview would
    audition a different part of the song than the render produces. One function
    is the only way to make that impossible rather than merely currently true.

    ``sr`` is taken from the first buffer — callers pass stems from a single
    separation pass, which share a rate by construction.
    """
    if not buffers:
        raise ValueError("cannot sum an empty list of buffers")
    n = max(b.n_frames for b in buffers)
    ch = max(b.n_channels for b in buffers)
    acc = np.zeros((n, ch), dtype=np.float32)
    for b in buffers:
        x = b.with_channels(ch).data
        acc[:x.shape[0]] += x
    return AudioBuffer(acc, buffers[0].sr)
