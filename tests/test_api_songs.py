import functools
import os
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


def _song_file(path, sr=22050, secs=3.0):
    t = np.arange(int(sr * secs)) / sr
    y = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return str(path)


def _wait_for_terminal(client, job_id, deadline_s=15.0):
    """Poll a job until it reaches done/failed/cancelled.

    A hard deadline rather than a generic timeout wrapper: if this ever hangs,
    the assertion failure names the last status seen, so it reads as a
    diagnosis rather than an unexplained timeout."""
    last_status = None
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        last_status = body["status"]
        if last_status in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(
        f"job {job_id} never reached a terminal status within {deadline_s}s "
        f"— last status seen was {last_status!r}")


def _wait_until(predicate, what, deadline_s=15.0):
    """Block until ``predicate()`` holds, or say which wait never ended."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"waited {deadline_s}s and {what}")


def test_schema_endpoint_returns_config_metadata(client):
    from sleepmix.config import config_schema

    r = client.get("/api/schema")
    assert r.status_code == 200
    assert r.json() == config_schema()


def test_import_song_records_duration_and_rate(client, tmp_path):
    path = _song_file(tmp_path / "a.wav")
    r = client.post("/api/songs", json={"path": path})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "a"
    assert body["sample_rate"] == 22050
    assert abs(body["duration_s"] - 3.0) < 0.05
    assert body["separation_status"] == "pending"


def test_import_rejects_a_missing_file(client, tmp_path):
    r = client.post("/api/songs", json={"path": str(tmp_path / "nope.wav")})
    assert r.status_code == 400
    assert "not found" in r.json()["detail"].lower()


def test_import_rejects_a_file_that_is_not_audio(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not audio")
    r = client.post("/api/songs", json={"path": str(bad)})
    assert r.status_code == 400


def test_list_songs_returns_what_was_imported(client, tmp_path):
    client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")})
    client.post("/api/songs", json={"path": _song_file(tmp_path / "b.wav")})
    titles = {s["title"] for s in client.get("/api/songs").json()["songs"]}
    assert titles == {"a", "b"}


def test_get_song_404s_when_absent(client):
    assert client.get("/api/songs/nope").status_code == 404


def test_setting_and_clearing_a_songs_last_preset(client, tmp_path):
    song = client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")}).json()
    answer = client.put(f"/api/songs/{song['id']}/last-preset",
                        json={"preset_id": "p1"})
    assert answer.status_code == 200
    assert answer.json()["last_preset_id"] == "p1"
    assert client.get(f"/api/songs/{song['id']}").json()["last_preset_id"] == "p1"

    cleared = client.put(f"/api/songs/{song['id']}/last-preset",
                         json={"preset_id": None})
    assert cleared.json()["last_preset_id"] is None


def test_setting_the_last_preset_of_an_unknown_song_is_a_404(client):
    assert client.put("/api/songs/nope/last-preset",
                      json={"preset_id": "p1"}).status_code == 404


def test_peaks_endpoint_returns_the_requested_bucket_count(client, tmp_path):
    song = client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")}).json()
    r = client.get(f"/api/songs/{song['id']}/peaks?buckets=64")
    assert r.status_code == 200
    body = r.json()
    assert len(body["peaks"]) == 64
    assert all(len(p) == 2 for p in body["peaks"])
    assert abs(body["duration_s"] - 3.0) < 0.05


def test_peaks_404s_for_an_unknown_song(client):
    assert client.get("/api/songs/nope/peaks").status_code == 404


def test_peaks_rejects_an_absurd_bucket_count(client, tmp_path):
    """An unbounded bucket count would let one request allocate arbitrarily."""
    song = client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")}).json()
    assert client.get(f"/api/songs/{song['id']}/peaks?buckets=10000000").status_code == 422


def test_peaks_are_finite_for_a_file_containing_nan(client, tmp_path):
    """A single bad sample must not blank the whole waveform in the UI.

    Non-finite floats serialize as JSON `null`, which fails an Elm decoder for
    `list (list float)` and takes the entire waveform with it."""
    import json

    import soundfile as sf

    path = tmp_path / "nan.wav"
    y = np.zeros((2048, 2), dtype=np.float32)
    y[100] = np.nan
    y[200] = np.inf
    sf.write(str(path), y, 22050, subtype="FLOAT")

    song = client.post("/api/songs", json={"path": str(path)}).json()
    body = client.get(f"/api/songs/{song['id']}/peaks?buckets=32").json()
    assert "null" not in json.dumps(body["peaks"])
    assert all(np.isfinite(p).all() for p in body["peaks"])


def test_peaks_404s_when_the_file_has_moved(client, tmp_path):
    path = _song_file(tmp_path / "a.wav")
    song = client.post("/api/songs", json={"path": path}).json()
    import os

    os.remove(path)
    r = client.get(f"/api/songs/{song['id']}/peaks")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()


def test_cancelling_a_separation_leaves_the_song_pending(client, tmp_path, monkeypatch):
    """Cancel used to return success and change nothing — the job ran to the
    end and the operator had to kill the server. The row must come back to
    where it started, not to 'failed': nothing was produced and nothing is
    broken."""
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    monkeypatch.setattr(
        "sleepmix.server.api.songs.run_separation",
        functools.partial(run_separation, worker_module="tests.stub_separation_worker"))

    song = client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")}).json()
    started = client.post(f"/api/songs/{song['id']}/separate")
    assert started.status_code == 202
    job_id = started.json()["id"]

    assert client.post(f"/api/jobs/{job_id}/cancel").json()["cancelled"] is True
    _wait_for_terminal(client, job_id)

    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
    assert client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "pending"


def test_cancelling_a_forced_separation_leaves_the_song_with_no_stems(
        client, tmp_path, monkeypatch):
    """The row must never claim stems the disk does not have.

    Written as a *sequence* rather than a unit, because no single step is
    wrong. ``force=true`` deletes the cached stems before spawning the child —
    correct, that is what force means. A cancel resets the status to
    "pending" — correct, nothing was produced. But between them nothing
    cleared ``songs.stems``, so a cancelled forced retry left the row saying
    "not separated" *and* listing four stems that no longer exist anywhere.

    Both mixer gates (``Page.Song.mixerPanel`` and ``Main``'s ``OpenMixer``)
    read ``song.stems``, not the cache, so that row opens the mixer. The first
    preview then calls the *in-process* ``separation.separate()`` inside
    ``SessionRegistry``'s per-song lock — a full Demucs run with no job, no
    queue row and no Cancel, which is the incident this whole branch exists to
    make impossible — and the stems it finally caches do not match the rows
    the mixer built from the stale list, so ``plan_stem_configs`` discards
    every setting on screen and plays every stem at its default.
    """
    from sleepmix.paths import cache_dir
    from sleepmix.separation import _cache_key, _cache_path

    path = _song_file(tmp_path / "a.wav")
    song = client.post("/api/songs", json={"path": path}).json()

    monkeypatch.setattr(
        "sleepmix.server.api.songs.run_separation",
        functools.partial(run_separation, worker_module="tests.stub_separation_worker"))

    first = client.post(f"/api/songs/{song['id']}/separate")
    _wait_for_terminal(client, first.json()["id"])
    separated = client.get(f"/api/songs/{song['id']}").json()
    assert separated["stems"], "precondition: the song has stems and a cache"
    key = _cache_key(path, client.app.state.separation_model)
    assert os.path.isdir(_cache_path(str(cache_dir()), key))

    # Retry with Demucs — which deletes the cache first — and stop it.
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    forced = client.post(f"/api/songs/{song['id']}/separate?force=true")
    job_id = forced.json()["id"]
    # Waiting for the deletion rather than cancelling straight away is what
    # makes this test about the thing it is about. A job cancelled while still
    # queued never enters the closure at all, so the cache would still be
    # there and the row would be honest for a reason that has nothing to do
    # with the fix — a pass by accident, intermittently.
    _wait_until(lambda: not os.path.isdir(_cache_path(str(cache_dir()), key)),
                "the forced separation never invalidated the cache")
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["cancelled"] is True
    _wait_for_terminal(client, job_id)

    after = client.get(f"/api/songs/{song['id']}").json()
    assert not os.path.isdir(_cache_path(str(cache_dir()), key)), (
        "force deleted the cache; this test is about the row that outlived it")
    assert after["separation_status"] == "pending"
    assert after["stems"] == [], (
        "the cached stems were deleted, so the row must not still list them — "
        "every mixer gate reads this field and would open on a song with "
        "nothing on disk")


def test_a_forced_separation_that_fails_also_leaves_no_stems(
        client, tmp_path, monkeypatch):
    """The same hole, through the other exit.

    ``except Exception`` predates this branch and never touched ``stems``
    either; it was only ever unreachable in practice because a forced
    separation that crashed was rarer than one that is now cancellable with a
    button. The row it leaves is worse, not better: "failed" with a stem list.
    """
    from sleepmix.paths import cache_dir
    from sleepmix.separation import _cache_key, _cache_path

    path = _song_file(tmp_path / "a.wav")
    song = client.post("/api/songs", json={"path": path}).json()

    monkeypatch.setattr(
        "sleepmix.server.api.songs.run_separation",
        functools.partial(run_separation, worker_module="tests.stub_separation_worker"))

    first = client.post(f"/api/songs/{song['id']}/separate")
    _wait_for_terminal(client, first.json()["id"])
    assert client.get(f"/api/songs/{song['id']}").json()["stems"]

    monkeypatch.setenv("STUB_EXIT_CODE", "3")
    forced = client.post(f"/api/songs/{song['id']}/separate?force=true")
    _wait_for_terminal(client, forced.json()["id"])

    after = client.get(f"/api/songs/{song['id']}").json()
    key = _cache_key(path, client.app.state.separation_model)
    assert not os.path.isdir(_cache_path(str(cache_dir()), key))
    assert after["separation_status"] == "failed"
    assert after["stems"] == []
