import functools
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.separation_process import run_separation
from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, name="a.wav", sr=22050, secs=2.0):
    path = tmp_path / name
    t = np.arange(int(sr * secs)) / sr
    y = (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def _await_job(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("job never finished")


def _a_running_separation(client, monkeypatch, song, force=False):
    """Post a separation and wait until it genuinely holds status 'running'.

    Uses the real subprocess worker path (``run_separation``), pointed at the
    stub worker module instead of real Demucs, and told through
    ``STUB_SLEEP_S`` to sit in its child process for a couple of seconds —
    real subprocess supervision, no torch involved. The wait for 'running' is
    a poll on the song's own status, not a sleep: that field is set at the
    top of the job's work() closure before the subprocess is even spawned, so
    polling for it is exact regardless of how long the child takes to start.
    """
    import sleepmix.server.api.songs as songs_api

    monkeypatch.setenv("STUB_SLEEP_S", "2")
    monkeypatch.setattr(
        songs_api, "run_separation",
        functools.partial(run_separation, worker_module="tests.stub_separation_worker"))

    body = client.post(f"/api/songs/{song['id']}/separate",
                       params={"force": "true"} if force else {}).json()

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "running":
            return body
        time.sleep(0.02)
    raise AssertionError("separation never reached status 'running'")


def _inline_separation(path, model, cache_dir, reporter=None, cancel=None):
    """Stand in for ``run_separation`` without spawning its worker subprocess.

    These tests predate the supervisor and drive behaviour by monkeypatching
    ``sleepmix.separation._demucs_separate`` in-process. A real subprocess
    would import a fresh, unpatched ``sleepmix.separation`` and — since Demucs
    is actually installed in this environment — would run a real separation
    instead of honouring the test double. Calling ``separate_detailed``
    directly keeps these tests exercising the same cache/fallback semantics
    they always have, without the process boundary."""
    from sleepmix.separation import separate_detailed

    return separate_detailed(path, model, cache_dir)


def test_separate_records_status_and_stems(client, tmp_path, monkeypatch):
    import sleepmix.separation as sep
    import sleepmix.server.api.songs as songs_api

    from sleepmix.audio import load_audio

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)
    monkeypatch.setattr(songs_api, "run_separation", _inline_separation)
    song = _import_song(client, tmp_path)

    r = client.post(f"/api/songs/{song['id']}/separate")
    assert r.status_code == 202
    _await_job(client, r.json()["id"])

    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "done"
    assert updated["separation_reason"] is None
    assert set(updated["stems"]) == {"vocals", "drums", "bass", "other"}


def test_separate_records_the_fallback_reason(client, tmp_path, monkeypatch):
    """This is the whole point: a UI must be able to say why there is one stem."""
    import sleepmix.separation as sep
    import sleepmix.server.api.songs as songs_api

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    monkeypatch.setattr(songs_api, "run_separation", _inline_separation)
    song = _import_song(client, tmp_path)

    job = client.post(f"/api/songs/{song['id']}/separate").json()
    _await_job(client, job["id"])

    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "fallback"
    assert "no torch" in updated["separation_reason"]
    assert updated["stems"] == ["mix"]


def test_separate_404s_for_an_unknown_song(client):
    assert client.post("/api/songs/nope/separate").status_code == 404


def test_separate_404s_when_the_file_has_moved(client, tmp_path):
    import os

    song = _import_song(client, tmp_path)
    os.remove(song["path"])
    r = client.post(f"/api/songs/{song['id']}/separate")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()


def test_force_reseparates_after_a_fallback(client, tmp_path, monkeypatch):
    import sleepmix.separation as sep
    import sleepmix.server.api.songs as songs_api

    from sleepmix.audio import load_audio

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    monkeypatch.setattr(songs_api, "run_separation", _inline_separation)
    song = _import_song(client, tmp_path)
    _await_job(client, client.post(f"/api/songs/{song['id']}/separate").json()["id"])
    assert client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "fallback"

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)

    # Without force the cached fallback wins, which is exactly the bug.
    _await_job(client, client.post(f"/api/songs/{song['id']}/separate").json()["id"])
    assert client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "fallback"

    _await_job(client, client.post(
        f"/api/songs/{song['id']}/separate?force=true").json()["id"])
    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "done"
    assert updated["separation_reason"] is None


def test_a_failed_separation_does_not_strand_the_song(client, tmp_path, monkeypatch):
    """A row stuck at "running" cannot be rescued — force re-enters the same job."""
    import sleepmix.server.api.songs as songs_api

    def boom(*_a, **_k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(songs_api, "run_separation", boom)
    song = _import_song(client, tmp_path)

    job = client.post(f"/api/songs/{song['id']}/separate").json()
    finished = _await_job(client, job["id"])
    assert finished["status"] == "failed"

    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "failed"
    assert "disk gone" in updated["separation_reason"]


def test_a_cancelled_separation_returns_the_song_to_pending(client, tmp_path, monkeypatch):
    """Cancelling produced nothing, so the row must not claim the song failed."""
    import sleepmix.server.api.songs as songs_api

    from sleepmix.progress import Cancelled

    def cancelled(*_a, **_k):
        raise Cancelled("cancelled")

    monkeypatch.setattr(songs_api, "run_separation", cancelled)
    song = _import_song(client, tmp_path)

    job = client.post(f"/api/songs/{song['id']}/separate").json()
    finished = _await_job(client, job["id"])
    assert finished["status"] == "cancelled"

    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "pending"
    assert updated["separation_reason"] is None


def test_a_cancelled_force_does_not_destroy_the_cache(client, tmp_path, monkeypatch):
    """Cancelling a forced re-separation must leave the cached stems alone.

    `force=true` deletes the cache first so the model really runs again. If the
    cancel check sits *after* that delete, a job cancelled before it ever ran
    still destroys the cache on its way out — the song is left with nothing,
    having been asked to stop. So the check goes first.

    Made deterministic by occupying the single worker: the forced job is still
    queued when the cancel lands, so when it finally runs the token is already
    set and `cancel.check()` fires on the first line of the closure."""
    import threading

    import sleepmix.server.api.songs as songs_api

    deleted: list[str] = []
    monkeypatch.setattr(
        songs_api, "invalidate_cache",
        lambda path, model, cache_dir=None: deleted.append(path))

    song = _import_song(client, tmp_path)

    release = threading.Event()
    occupied = threading.Event()

    def blocker(reporter, cancel) -> dict:
        occupied.set()
        release.wait(timeout=30)
        return {}

    jobs = client.app.state.jobs
    jobs.submit("test-blocker", blocker)
    assert occupied.wait(timeout=10), "the worker never picked up the blocker"

    job_id = client.post(f"/api/songs/{song['id']}/separate?force=true").json()["id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code in (200, 202, 204)
    release.set()

    body = _await_job(client, job_id)
    assert body["status"] == "cancelled"
    assert deleted == [], "a cancelled force deleted the cache anyway"
    assert client.get(f"/api/songs/{song['id']}").json()[
        "separation_status"] == "pending"


def test_submitting_separate_twice_reuses_the_in_flight_job(client, tmp_path, monkeypatch):
    """A reload — or a second tab — has no memory of a separation already in
    flight. Without this, clicking Separate again stacks a second job behind
    the first instead of attaching to it, which is exactly the queue-stacking
    this whole plan exists to prevent."""
    song = _import_song(client, tmp_path)
    first = _a_running_separation(client, monkeypatch, song)

    second = client.post(f"/api/songs/{song['id']}/separate").json()
    assert second["id"] == first["id"]

    jobs = client.app.state.jobs
    separate_jobs = [j for j in jobs.list()
                     if j.kind == "separate" and j.song_id == song["id"]]
    assert len(separate_jobs) == 1

    _await_job(client, first["id"])


def test_submitting_separate_twice_with_force_reuses_the_in_flight_job(client, tmp_path, monkeypatch):
    """force=true must not bypass the guard: invalidating the cache underneath
    a separation that is already reading from it is worse than making the
    caller wait for, or cancel, the one already running."""
    song = _import_song(client, tmp_path)
    first = _a_running_separation(client, monkeypatch, song, force=True)

    second = client.post(f"/api/songs/{song['id']}/separate",
                         params={"force": "true"}).json()
    assert second["id"] == first["id"]

    jobs = client.app.state.jobs
    separate_jobs = [j for j in jobs.list()
                     if j.kind == "separate" and j.song_id == song["id"]]
    assert len(separate_jobs) == 1

    _await_job(client, first["id"])


def test_submitting_separate_after_the_first_finished_makes_a_new_job(
        client, tmp_path, monkeypatch):
    """The guard must not wedge the song forever once its job is done."""
    import sleepmix.separation as sep
    import sleepmix.server.api.songs as songs_api

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    monkeypatch.setattr(songs_api, "run_separation", _inline_separation)
    song = _import_song(client, tmp_path)

    first = client.post(f"/api/songs/{song['id']}/separate").json()
    _await_job(client, first["id"])

    second = client.post(f"/api/songs/{song['id']}/separate").json()
    assert second["id"] != first["id"]
