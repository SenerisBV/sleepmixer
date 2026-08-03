"""Stem separation via Demucs, with caching and a no-ML fallback.

Demucs (Meta) splits a track into ``vocals / drums / bass / other``. The model
and its weights are a multi-GB optional dependency, imported lazily. When it
isn't installed, ``separate`` returns the whole track as a single ``mix`` stem
and warns — so you can still develop and audition the creative layers without
the full ML stack.
"""
from __future__ import annotations

import hashlib
import os
import warnings
from dataclasses import dataclass

import numpy as np

from .audio import AudioBuffer, load_audio, save_audio

STEM_NAMES = ("vocals", "drums", "bass", "other")

_FALLBACK_MARKER = "fallback.txt"


@dataclass
class SeparationResult:
    """Stems, plus why they might not be what you asked for.

    The fallback used to be announced only through ``warnings.warn``, which a
    terminal shows and a UI swallows — leaving someone to configure per-stem
    decay, receive one undifferentiated stem, and get no explanation. The reason
    is data now, and it is cached alongside the stems so a later load still
    knows it is looking at a fallback."""

    stems: dict[str, AudioBuffer]
    fallback_reason: str | None = None


def separate(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> dict[str, AudioBuffer]:
    """Return a dict of stem-name -> AudioBuffer for ``input_path``."""
    return separate_detailed(input_path, model, cache_dir).stems


def separate_detailed(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> SeparationResult:
    """Like ``separate``, but also reports why it fell back, if it did."""
    key = _cache_key(input_path, model)
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return SeparationResult(cached, _load_fallback_reason(cache_dir, key))

    reason: str | None = None
    try:
        stems = _demucs_separate(input_path, model)
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        reason = (
            f"Demucs separation unavailable ({exc}); using the full mix as a "
            f"single 'mix' stem. Install the 'separation' extra for real stems."
        )
        warnings.warn(reason, stacklevel=2)
        stems = {"mix": load_audio(input_path)}

    _save_fallback_reason(cache_dir, key, reason)
    _save_cache(cache_dir, key, stems)
    return SeparationResult(stems, reason)


def _demucs_separate(input_path: str, model: str) -> dict[str, AudioBuffer]:
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio
    from demucs.pretrained import get_model

    mdl = get_model(model)
    mdl.eval()
    wav = load_audio(input_path, sr=mdl.samplerate)
    # demucs wants (channels, samples) and a batch dim.
    x = torch.from_numpy(wav.data.T).float()
    x = convert_audio(x, wav.sr, mdl.samplerate, mdl.audio_channels)
    with torch.no_grad():
        sources = apply_model(mdl, x[None], progress=False)[0]
    out: dict[str, AudioBuffer] = {}
    for name, src in zip(mdl.sources, sources):
        out[name] = AudioBuffer(src.cpu().numpy().T, mdl.samplerate)
    return out


# -- caching ------------------------------------------------------------
def _cache_key(input_path: str, model: str) -> str:
    st = os.stat(input_path)
    raw = f"{os.path.abspath(input_path)}:{st.st_size}:{int(st.st_mtime)}:{model}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _cache_path(cache_dir: str, key: str) -> str:
    return os.path.join(cache_dir, key)


def _load_cache(cache_dir: str, key: str) -> dict[str, AudioBuffer] | None:
    d = _cache_path(cache_dir, key)
    if not os.path.isdir(d):
        return None
    stems: dict[str, AudioBuffer] = {}
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".wav"):
            stems[fn[:-4]] = load_audio(os.path.join(d, fn))
    return stems or None


def _save_cache(cache_dir: str, key: str, stems: dict[str, AudioBuffer]) -> None:
    d = _cache_path(cache_dir, key)
    os.makedirs(d, exist_ok=True)
    for name, buf in stems.items():
        save_audio(buf, os.path.join(d, f"{name}.wav"))


def _fallback_marker_path(cache_dir: str, key: str) -> str:
    return os.path.join(_cache_path(cache_dir, key), _FALLBACK_MARKER)


def _save_fallback_reason(cache_dir: str, key: str, reason: str | None) -> None:
    """Persist why we fell back, so a later cache hit still knows.

    Written before the stems on purpose: if this succeeds and the stems do not,
    the next call finds no ``.wav`` files, recomputes, and overwrites the stale
    marker. The reverse order would leave cached fallback stems with no marker,
    which reads as a successful separation."""
    os.makedirs(_cache_path(cache_dir, key), exist_ok=True)
    path = _fallback_marker_path(cache_dir, key)
    if reason is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w") as fh:
        fh.write(reason)


def _load_fallback_reason(cache_dir: str, key: str) -> str | None:
    path = _fallback_marker_path(cache_dir, key)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return fh.read() or None
