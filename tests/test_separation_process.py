import os
import time

import numpy as np
import pytest

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.progress import CancelToken, Cancelled, ProgressReporter
from sleepmix.separation import SeparationFailed, _cache_key, _write_cache
from sleepmix.separation_process import run_separation

STUB = "tests.stub_separation_worker"


@pytest.fixture
def song(tmp_path):
    path = tmp_path / "song.wav"
    save_audio(AudioBuffer(np.zeros((44100, 2), dtype=np.float32), 44100), str(path))
    return str(path)


def _collect(events):
    return ProgressReporter(lambda e: events.append((e.fraction, e.message)))


def test_a_cache_hit_never_spawns_anything(song, tmp_path, monkeypatch):
    """The warm path must stay warm. Spawning a process to discover we already
    had the answer would put a torch import in front of every separated song."""
    stems = {"vocals": AudioBuffer(np.zeros((10, 2), dtype=np.float32), 44100)}
    _write_cache(str(tmp_path), _cache_key(song, "m"), stems, None)

    def forbidden(*a, **k):
        raise AssertionError("spawned a worker for a cache hit")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    result = run_separation(song, "m", str(tmp_path), worker_module=STUB)
    assert sorted(result.stems) == ["vocals"]


def test_phases_reach_the_reporter(song, tmp_path):
    events = []
    result = run_separation(song, "m", str(tmp_path),
                            reporter=_collect(events), worker_module=STUB)
    assert sorted(result.stems) == ["bass", "drums", "other", "vocals"]
    assert [m for _, m in events][:2] == ["Loading the model", "Separating stems"]


def test_unparseable_output_is_ignored(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_STDOUT_NOISE", "1")
    events = []
    run_separation(song, "m", str(tmp_path), reporter=_collect(events),
                   worker_module=STUB)
    assert all(m for _, m in events), "a noise line became an empty phase"


def test_cancelling_kills_the_child_and_raises(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    token = CancelToken()
    import threading
    threading.Timer(0.4, token.cancel).start()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"took {elapsed:.1f}s — the child was not killed"


def test_a_cancel_that_lands_before_the_spawn_still_raises(song, tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)


def test_a_nonzero_exit_is_a_failure_not_a_fallback(song, tmp_path, monkeypatch):
    """The distinction that matters: a crashed worker must not become a
    one-stem 'mix', which would render and play without complaining."""
    monkeypatch.setenv("STUB_EXIT_CODE", "3")
    with pytest.raises(SeparationFailed) as exc:
        run_separation(song, "m", str(tmp_path), worker_module=STUB)
    assert "3" in str(exc.value)
    assert "stub failing on purpose" in str(exc.value)


def test_exiting_cleanly_without_writing_a_cache_is_a_failure(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_NO_CACHE", "1")
    with pytest.raises(SeparationFailed):
        run_separation(song, "m", str(tmp_path), worker_module=STUB)


@pytest.mark.slow
def test_the_real_worker_speaks_the_same_protocol(song, tmp_path):
    """Without this, every test above proves only that the stub works.

    Runs the real worker on one second of silence. If demucs is not installed
    it takes the unavailable-fallback inside the child and still exits 0 with a
    cache — which is the contract being checked here, not the stem quality."""
    events = []
    result = run_separation(song, "htdemucs_ft", str(tmp_path),
                            reporter=_collect(events))
    assert result.stems
    assert any(m == "Loading the model" for _, m in events)
