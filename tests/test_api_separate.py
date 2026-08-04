import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
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


def test_separate_records_status_and_stems(client, tmp_path, monkeypatch):
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)
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

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
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

    from sleepmix.audio import load_audio

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
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
