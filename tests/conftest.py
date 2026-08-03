"""Keep the whole test suite off the operator's real data directory.

``autouse`` means every test gets an isolated SLEEPMIX_DATA_DIR whether it asks
for one or not — the separation cache and (later) the library database must
never touch real files during a test run.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "sleepmix-data"))
    yield


import numpy as np

from sleepmix.audio import AudioBuffer, load_audio

STUB_STEM_NAMES = ("vocals", "drums", "bass", "other")


def fake_separate(input_path, model="htdemucs_ft", cache_dir=None):
    """A stand-in for Demucs.

    Real separation takes about ten seconds per call and the on-disk cache keys
    on file path, size and mtime — so every test using a fresh ``tmp_path`` song
    would miss the cache and run the model for real. These stems are synthetic,
    deterministic, and distinct from each other so solo/sum behaviour is
    observable."""
    src = load_audio(str(input_path))
    t = np.arange(src.n_frames) / src.sr
    stems = {}
    for i, name in enumerate(STUB_STEM_NAMES):
        y = (0.2 * np.sin(2 * np.pi * 110 * (i + 1) * t)).astype(np.float32)
        stems[name] = AudioBuffer(np.stack([y, y], axis=1), src.sr)
    return stems


@pytest.fixture
def stub_separation(monkeypatch):
    """Replace Demucs wherever the pipeline reaches for it.

    Both ``sleepmix/pipeline.py`` and ``sleepmix/session.py`` do
    ``from .separation import separate``, which binds the name on each of those
    modules — so patching ``sleepmix.separation.separate`` alone would miss
    both. Every module that holds its own reference is patched here, because
    the promise in this docstring is one a caller will rely on: a
    ``RenderSession(path, cfg)`` constructed without an explicit
    ``separate_fn`` would otherwise quietly run real Demucs inside a test that
    took this fixture and believed itself isolated.

    Returns the stub so tests can also inject it directly (``RenderSession``
    takes a ``separate_fn``)."""
    import sleepmix.pipeline
    import sleepmix.session

    monkeypatch.setattr(sleepmix.pipeline, "separate", fake_separate)
    monkeypatch.setattr(sleepmix.session, "separate", fake_separate)
    return fake_separate
