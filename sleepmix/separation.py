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

import numpy as np

from .audio import AudioBuffer, load_audio, save_audio

STEM_NAMES = ("vocals", "drums", "bass", "other")


def separate(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> dict[str, AudioBuffer]:
    """Return a dict of stem-name -> AudioBuffer for ``input_path``."""
    key = _cache_key(input_path, model)
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return cached

    try:
        stems = _demucs_separate(input_path, model)
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        warnings.warn(
            f"Demucs separation unavailable ({exc}); using the full mix as a "
            f"single 'mix' stem. Install the 'separation' extra for real stems.",
            stacklevel=2,
        )
        stems = {"mix": load_audio(input_path)}

    _save_cache(cache_dir, key, stems)
    return stems


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
