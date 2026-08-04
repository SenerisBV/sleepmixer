import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _import(client, tmp_path, secs=8.0, sr=22050):
    path = tmp_path / "a.wav"
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def test_loop_reports_a_region_inside_the_song(client, tmp_path):
    song = _import(client, tmp_path)
    body = client.get(f"/api/songs/{song['id']}/loop").json()
    assert 0 <= body["start_s"] < body["end_s"] <= song["duration_s"] + 0.01
    assert body["tempo"] > 0


def test_loop_404s_for_an_unknown_song(client):
    assert client.get("/api/songs/nope/loop").status_code == 404


def test_loop_404s_when_the_file_has_moved(client, tmp_path):
    import os

    song = _import(client, tmp_path)
    os.remove(song["path"])
    r = client.get(f"/api/songs/{song['id']}/loop")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()


def test_loop_honours_explicit_config_overrides(client, tmp_path):
    """The UI will send back a dragged region; the same endpoint must echo it."""
    song = _import(client, tmp_path)
    body = client.get(
        f"/api/songs/{song['id']}/loop?start_s=2.0&end_s=5.0").json()
    assert abs(body["start_s"] - 2.0) < 0.01
    assert abs(body["end_s"] - 5.0) < 0.01
