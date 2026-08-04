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
import shutil
import tempfile
import warnings
from dataclasses import dataclass

import numpy as np

from .audio import AudioBuffer, load_audio, save_audio

STEM_NAMES = ("vocals", "drums", "bass", "other")

_FALLBACK_MARKER = "fallback.txt"


class SeparationFailed(RuntimeError):
    """The separation did not run to completion for a reason that is not a
    cancellation and not Demucs being unavailable.

    Distinct from the unavailable-fallback on purpose. ``separate_detailed``
    answers "demucs is not installed" with the whole song as a single ``mix``
    stem, which is the right answer to that question and the wrong answer to
    every other one — a crashed or killed worker must not quietly become a
    one-stem mix that then renders and plays without complaining."""


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
    except MemoryError:
        # Not a statement about whether Demucs is installed — running out of
        # memory inside the worker must surface as a crash (SeparationFailed,
        # via the process exiting non-zero), not as a one-stem 'mix' that the
        # parent cannot tell apart from "the separation extra isn't there".
        raise
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        reason = (
            f"Demucs separation unavailable ({exc}); using the full mix as a "
            f"single 'mix' stem. Install the 'separation' extra for real stems."
        )
        warnings.warn(reason, stacklevel=2)
        stems = {"mix": load_audio(input_path)}

    _write_cache(cache_dir, key, stems, reason)
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


def _write_cache(cache_dir: str, key: str, stems: dict[str, AudioBuffer],
                  reason: str | None) -> None:
    """Publish a separation: the fallback marker and every stem, together.

    Everything is written into a sibling staging directory and renamed into
    place once it is all on disk, so an interrupted write leaves either the
    previous cache or nothing — never a subset. ``_load_cache`` returns
    whatever ``.wav`` files it finds, so a subset would read back as a smaller
    but perfectly valid separation, and the song would render missing half its
    content with nothing to say so.

    This supersedes an earlier arrangement where the marker was written first
    and the stems second, chosen so that a failure between them left no stems
    and a stale marker (recoverable) rather than fallback stems and no marker
    (which reads as a successful separation). That ordering was the best
    available while the write could not be made atomic. It can be now.

    A killed writer (Task 2 makes separation killable) can also leave a
    staging directory behind with no process left to clean it up. Those are
    swept here, scoped to this ``key`` only — sweeping the whole cache
    directory would race a concurrent write of a different song, but a single
    worker only ever has one write in flight for a given key at a time."""
    final = _cache_path(cache_dir, key)
    os.makedirs(cache_dir, exist_ok=True)
    prefix = f".{key}."
    for entry in os.listdir(cache_dir):
        if entry.startswith(prefix):
            shutil.rmtree(os.path.join(cache_dir, entry), ignore_errors=True)
    staging = tempfile.mkdtemp(prefix=prefix, dir=cache_dir)
    try:
        if reason is not None:
            with open(os.path.join(staging, _FALLBACK_MARKER), "w") as fh:
                fh.write(reason)
        for name, buf in stems.items():
            save_audio(buf, os.path.join(staging, f"{name}.wav"))
        # Rename-then-remove, not remove-then-rename: `shutil.rmtree(final,
        # ignore_errors=True)` does not abort on the first error, it swallows
        # each one and keeps walking, so a permission error or a locked handle
        # partway through can leave `final` holding some but not all of the
        # *old* stems. `os.replace` onto that non-empty leftover then fails,
        # and the old cache is left as a subset — exactly the state this
        # function exists to make impossible. Renaming first means `final` is
        # only ever swapped between two complete directories (the rename
        # itself is atomic), and the old one is deleted only after it has
        # already been replaced. A crash between the two renames leaves no
        # cache at all, which recomputes — the one outcome that is always
        # safe.
        doomed = os.path.join(cache_dir, f".{key}.replacing")
        shutil.rmtree(doomed, ignore_errors=True)  # a leftover from an earlier crash
        replaced = os.path.isdir(final)
        if replaced:
            os.replace(final, doomed)
        os.replace(staging, final)
        if replaced:
            shutil.rmtree(doomed, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _fallback_marker_path(cache_dir: str, key: str) -> str:
    return os.path.join(_cache_path(cache_dir, key), _FALLBACK_MARKER)


def _load_fallback_reason(cache_dir: str, key: str) -> str | None:
    path = _fallback_marker_path(cache_dir, key)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return fh.read() or None


def invalidate_cache(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> bool:
    """Delete the cached separation for ``input_path``. True if there was one.

    The cache key is ``(path, size, mtime, model)`` and deliberately says
    nothing about whether Demucs was importable at the time. That is fine for
    a successful separation and wrong for a fallback: without this, a track
    separated before the ``separation`` extra was installed would report itself
    as a fallback forever."""
    directory = _cache_path(cache_dir, _cache_key(input_path, model))
    if not os.path.isdir(directory):
        return False
    shutil.rmtree(directory)
    return True
