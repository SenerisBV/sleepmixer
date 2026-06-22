"""Tempo/beat analysis and loop-point selection.

Uses librosa when available to find a musically coherent, beat-aligned segment
to loop. Without librosa it falls back to a fixed-tempo guess so the pipeline
still produces a (rougher) loop.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio import AudioBuffer
from .config import LoopConfig


@dataclass
class LoopPoint:
    start: int          # start frame
    end: int            # end frame (exclusive)
    tempo: float        # estimated BPM


def find_loop(buf: AudioBuffer, cfg: LoopConfig) -> LoopPoint:
    """Pick a ``cfg.bars``-bar loop from the stable middle of the track."""
    try:
        return _librosa_loop(buf, cfg)
    except Exception:
        return _fixed_tempo_loop(buf, cfg)


def _librosa_loop(buf: AudioBuffer, cfg: LoopConfig) -> LoopPoint:
    import librosa

    y = buf.to_mono().data[:, 0]
    sr = buf.sr
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_samples(beats)
    n_beats = cfg.bars * cfg.beats_per_bar

    if len(beat_times) <= n_beats:
        return _fixed_tempo_loop(buf, cfg)

    # Restrict candidate start beats to the configured search window, then pick
    # the segment whose start and end beats are most self-similar (best seam).
    total = buf.n_frames
    lo = cfg.search_start * total
    hi = cfg.search_end * total
    best_i, best_score = None, -np.inf
    for i in range(len(beat_times) - n_beats):
        s = beat_times[i]
        e = beat_times[i + n_beats]
        if s < lo or e > hi:
            continue
        score = _seam_similarity(y, s, e, sr)
        if score > best_score:
            best_score, best_i = score, i
    if best_i is None:
        best_i = len(beat_times) // 3
    s = int(beat_times[best_i])
    e = int(beat_times[best_i + n_beats])
    return LoopPoint(start=s, end=e, tempo=tempo)


def _seam_similarity(y: np.ndarray, start: int, end: int, sr: int) -> float:
    """Higher when the audio just before ``start`` resembles audio at ``end`` —
    i.e. the loop will join cleanly."""
    w = min(int(0.1 * sr), (end - start) // 4)
    if w <= 0 or start + w > len(y) or end + w > len(y):
        return -np.inf
    a = y[start:start + w]
    b = y[end - w:end]
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def _fixed_tempo_loop(buf: AudioBuffer, cfg: LoopConfig, assumed_bpm: float = 120.0) -> LoopPoint:
    sr = buf.sr
    seconds_per_beat = 60.0 / assumed_bpm
    loop_seconds = seconds_per_beat * cfg.bars * cfg.beats_per_bar
    loop_frames = int(loop_seconds * sr)
    start = int(buf.n_frames * cfg.search_start)
    end = min(start + loop_frames, buf.n_frames)
    if end - start < sr:  # track shorter than the window — just use it whole
        start, end = 0, buf.n_frames
    return LoopPoint(start=start, end=end, tempo=assumed_bpm)


def slice_loop(buf: AudioBuffer, lp: LoopPoint) -> AudioBuffer:
    return AudioBuffer(buf.data[lp.start:lp.end], buf.sr)
