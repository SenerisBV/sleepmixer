"""Cut recordings into 1-2 minute segments and export a station bundle.

A station is `<out>/<id>/s01.wav, s02.wav, …` (numbered across the whole
recording, 22050 Hz mono PCM_16) plus `station.json`. Each segment is a slice
of one raw take (never spanning two passages), cut at the middle of a pause,
then put through the same chain as `render_character`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .character import apply_character
from .script import Passage, Script, spoken_text
from .voicing import (PAUSE_THRESHOLD_DB, PAUSE_WIN_S, RENDER_EDGE_S, SR, _edges,
                      _to_sr, character_seed, normalise, raw_passage_file,
                      stretch_pauses, _write_json_atomic)

OUT_SR = 22050
CUT_MIN_PAUSE_S = 0.25   # PLACEHOLDER: a silence this long can be a cut
CUT_WINDOW = 0.20        # PLACEHOLDER: a cut within +-20% of the take of the expected time
CUT_DISTANCE_PENALTY = 0.02  # PLACEHOLDER: seconds of pause given up per second of distance

_PARAGRAPH = re.compile(r"\n\s*\n")


def find_pauses(x: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """(start, end) seconds of the inner silences of at least CUT_MIN_PAUSE_S
    (leading and trailing silence excluded)."""
    win = max(1, int(PAUSE_WIN_S * sr))
    n = len(x) // win
    if n == 0:
        return []
    frames = np.asarray(x[: n * win], dtype=np.float64).reshape(n, win)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-20)
    quiet = 20 * np.log10(rms) < PAUSE_THRESHOLD_DB
    out: list[tuple[float, float]] = []
    i = 0
    while i < n:
        j = i
        while j < n and quiet[j] == quiet[i]:
            j += 1
        if quiet[i] and i > 0 and j < n and (j - i) * win / sr >= CUT_MIN_PAUSE_S:
            out.append((i * win / sr, j * win / sr))
        i = j
    return out


def cut_times(x: np.ndarray, sr: int, fractions: list[float]) -> list[float]:
    """For each expected fraction of the take, the midpoint of the chosen pause.

    Expected time = fraction * duration. Each pause scores its length minus
    CUT_DISTANCE_PENALTY * |midpoint - expected|; the best within CUT_WINDOW of
    the duration of the expected time wins, else the pause nearest it. Cuts
    only come from pauses after the previous cut, so they strictly increase;
    when no pause is left the remaining fractions yield no cut.
    """
    dur = len(x) / sr
    pauses = find_pauses(x, sr)
    cuts: list[float] = []
    for f in fractions:
        expected = f * dur
        avail = [(s, e) for s, e in pauses if not cuts or (s + e) / 2 > cuts[-1]]
        if not avail:
            break
        near = [(s, e) for s, e in avail if abs((s + e) / 2 - expected) <= CUT_WINDOW * dur]
        if near:
            s, e = max(near, key=lambda p: (p[1] - p[0])
                       - CUT_DISTANCE_PENALTY * abs((p[0] + p[1]) / 2 - expected))
        else:
            s, e = min(avail, key=lambda p: abs((p[0] + p[1]) / 2 - expected))
        cuts.append((s + e) / 2)
    return cuts


def segment_fractions(p: Passage) -> list[float]:
    """Share of the passage's spoken characters before each segment after the first."""
    paras = [q for q in _PARAGRAPH.split(p.text.strip()) if q.strip()]
    sizes = [len(spoken_text(Passage(p.index, q, p.intensity))) for q in paras]
    total = sum(sizes)
    return [sum(sizes[:k]) / total for k in p.segment_starts[1:] if 0 < k < len(paras)]


def _write_pcm16(x: np.ndarray, path: Path) -> None:
    sf.write(str(path), np.clip(x, -1.0, 1.0), OUT_SR, subtype="PCM_16")


def export_station(script: Script, library: Path, out: Path) -> dict:
    """Write `<out>/<id>/sNN.wav` and `station.json`; return the JSON dict."""
    d = Path(library) / script.id
    dest = Path(out) / script.id
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("s[0-9][0-9]*.wav"):  # a shorter re-cut must not leave stale files
        old.unlink()
    segments: list[dict] = []
    n = 0
    for p in script.passages:
        raw, sr = sf.read(str(d / raw_passage_file(p.index)), dtype="float32")
        raw = _to_sr(raw, sr)
        edges = [0.0] + cut_times(raw, SR, segment_fractions(p)) + [len(raw) / SR]
        for k in range(len(edges) - 1):
            part = raw[int(round(edges[k] * SR)):int(round(edges[k + 1] * SR))]
            x = stretch_pauses(part, SR, script.pause_stretch)
            y = apply_character(x, SR, script.source_character,
                                character_seed(script.id, p.index * 100 + k))
            y = normalise(_edges(y, RENDER_EDGE_S))
            y = resample_poly(y, OUT_SR, SR).astype(np.float32)
            n += 1
            name = f"s{n:02d}.wav"
            _write_pcm16(y, dest / name)
            segments.append({"file": name, "seconds": round(len(y) / OUT_SR, 3)})
    station = {"id": script.id, "title": script.title, "segments": segments}
    _write_json_atomic(station, dest / "station.json")
    return station
