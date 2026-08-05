import subprocess
import threading
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


def _wait_until_dead(proc: subprocess.Popen, timeout: float = 2.0) -> int | None:
    """Poll until the OS has reaped ``proc``, or give up and return None."""
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return proc.poll()


class _ExplodingReporter:
    """A stand-in for a caller's progress sink that blows up mid-separation —
    a UI callback raising is exactly as capable of leaving Popen out of scope
    with the child still running as a cancellation or a Ctrl-C is. This is
    the "simpler" proof that the try/finally around the child guards every
    kind of exit, not just the cancel path: nothing about it is cancel- or
    subprocess-specific."""

    def emit(self, stage, message, fraction, stem=None):
        raise RuntimeError("boom from the caller's sink")


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


def test_a_cached_fallback_still_reports_itself_as_a_fallback(song, tmp_path, monkeypatch):
    """A warm fallback must not read as a proper separation.

    The warm path returns `SeparationResult(_load_cache(...),
    _load_fallback_reason(...))` directly rather than going through
    `separate_detailed`, which is deliberate — it exists so four
    multi-hundred-megabyte stems are not decoded twice on every reopen — but it
    is a second place that has to remember to carry the reason, and nothing
    proved it did.

    What the forgetting looks like: a song separated before the `separation`
    extra was installed has one `mix` stem and a marker saying so. Drop the
    reason here and it comes back as `Separated` with a single stem, the song
    screen stops offering "Retry with Demucs", and the mixer builds one row out
    of the whole track while the operator configures a decay per instrument
    that does not exist.
    """
    stems = {"mix": AudioBuffer(np.zeros((10, 2), dtype=np.float32), 44100)}
    _write_cache(str(tmp_path), _cache_key(song, "m"), stems,
                 "Demucs separation unavailable (no torch)")

    def forbidden(*a, **k):
        raise AssertionError("spawned a worker for a cache hit")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    result = run_separation(song, "m", str(tmp_path), worker_module=STUB)
    assert sorted(result.stems) == ["mix"]
    assert result.fallback_reason is not None
    assert "unavailable" in result.fallback_reason


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
    messages = [m for _, m in events]
    # Exact, not "all truthy": a tautology here would pass even if the noise
    # line's text leaked through as a phase message, which is the one thing
    # this test exists to rule out.
    assert messages == ["Loading the model", "Separating stems", "Writing stems"]
    assert "some torch warning nobody asked for" not in messages


def test_cancelling_kills_the_child_and_raises(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    token = CancelToken()
    threading.Timer(0.4, token.cancel).start()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"took {elapsed:.1f}s — the child was not killed"


def test_cancelling_actually_kills_the_child_not_just_the_wait(song, tmp_path, monkeypatch):
    """Raising Cancelled proves the parent stopped watching, not that the
    child is dead. A supervisor rewritten to `raise Cancelled()` without
    touching the process would pass the timing test above unchanged — the
    exception fires fast either way. Capture the real Popen object and check
    the OS's own view of it after the call returns."""
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen] = []

    def spy(*a, **k):
        p = real_popen(*a, **k)
        spawned.append(p)
        return p

    monkeypatch.setattr("subprocess.Popen", spy)
    token = CancelToken()
    threading.Timer(0.4, token.cancel).start()

    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)

    assert spawned, "no child was spawned"
    exit_code = _wait_until_dead(spawned[0])
    assert exit_code is not None, "child is still running after cancellation"


def test_cancelling_escalates_to_kill_when_terminate_is_ignored(song, tmp_path, monkeypatch):
    """terminate() alone is not enough if the child ignores SIGTERM. The stub
    can be told to do exactly that, which is the only way to exercise the
    kill() escalation and timeout_s honestly — the plain stub dies on the
    first SIGTERM, so that branch never runs and a `kill()` replaced with
    `pass` would still pass every other test here."""
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    monkeypatch.setenv("STUB_IGNORE_SIGTERM", "1")
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen] = []

    def spy(*a, **k):
        p = real_popen(*a, **k)
        spawned.append(p)
        return p

    monkeypatch.setattr("subprocess.Popen", spy)
    token = CancelToken()
    threading.Timer(0.4, token.cancel).start()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token,
                       worker_module=STUB, timeout_s=0.5)
    elapsed = time.monotonic() - started
    # Bounded by timeout_s (the terminate() grace period) plus the kill()
    # itself, not by STUB_SLEEP_S — proves escalation actually ran.
    assert elapsed < 5, f"took {elapsed:.1f}s — kill() escalation did not run"
    assert spawned, "no child was spawned"
    exit_code = _wait_until_dead(spawned[0])
    assert exit_code is not None, "child ignored SIGTERM and was never killed"


def test_cancelling_after_the_cache_is_already_written_still_raises(song, tmp_path, monkeypatch):
    """The worst case in the task's table: a child killed after it already
    wrote a cache but before it exited. The cache existing on disk must not
    turn a cancellation into a quiet result — the operator asked to stop,
    and a stem set appearing anyway is wrong even when it's technically
    fine. STUB_SLEEP_S alone can't express this (the stub writes its cache
    after sleeping); STUB_CACHE_THEN_SLEEP flips the order."""
    monkeypatch.setenv("STUB_CACHE_THEN_SLEEP", "1")
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    token = CancelToken()
    threading.Timer(0.4, token.cancel).start()

    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)


def test_an_exception_from_the_callers_sink_still_kills_the_child(song, tmp_path, monkeypatch):
    """The critical fix, proved directly: any exception unwinding the frame
    between Popen and the end of the function — not only a cancellation —
    must not orphan the child. Before the try/finally around the child, this
    left a live process with no reference to it left anywhere, which for
    real Demucs is a multi-gigabyte process the operator has to kill by
    hand: the exact incident this task exists to prevent, reached through a
    door that has nothing to do with cancel()."""
    monkeypatch.setenv("STUB_SLEEP_S", "5")
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen] = []

    def spy(*a, **k):
        p = real_popen(*a, **k)
        spawned.append(p)
        return p

    monkeypatch.setattr("subprocess.Popen", spy)
    with pytest.raises(RuntimeError, match="boom"):
        run_separation(song, "m", str(tmp_path),
                       reporter=_ExplodingReporter(), worker_module=STUB)

    assert spawned, "no child was spawned"
    exit_code = _wait_until_dead(spawned[0])
    assert exit_code is not None, "child is still running after the sink raised"


def test_a_cancel_that_lands_before_the_spawn_still_raises(song, tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)


def test_a_cancel_that_lands_before_the_spawn_never_spawns_anything(song, tmp_path, monkeypatch):
    """An already-cancelled request must be caught before paying for a
    process spawn, not one poll cycle later. Deleting the pre-spawn
    `cancel.check()` still raises Cancelled eventually — the read loop
    catches it — but only after spawning a worker that was doomed before it
    started. Forbidding Popen pins the check in place."""
    token = CancelToken()
    token.cancel()

    def forbidden(*a, **k):
        raise AssertionError("spawned a worker for an already-cancelled request")

    monkeypatch.setattr("subprocess.Popen", forbidden)
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

    Runs the real worker on one second of silence and requires demucs to
    actually be installed (`importorskip`, rather than letting an
    uninstalled/broken demucs take the child's own unavailable-fallback and
    pass anyway) — `assert result.stems` alone is satisfied by a one-stem
    'mix', which is exactly the silent failure this plan ranks first.
    Asserting the four real stem names and `fallback_reason is None` is what
    actually tells "real separation ran" apart from "the fallback quietly
    took over".
    """
    pytest.importorskip("demucs")
    events = []
    result = run_separation(song, "htdemucs_ft", str(tmp_path),
                            reporter=_collect(events))
    assert sorted(result.stems) == ["bass", "drums", "other", "vocals"]
    assert result.fallback_reason is None
    assert any(m == "Loading the model" for _, m in events)
