import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
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


def test_peaks_404s_when_the_file_has_moved(client, tmp_path):
    path = _song_file(tmp_path / "a.wav")
    song = client.post("/api/songs", json={"path": path}).json()
    import os

    os.remove(path)
    r = client.get(f"/api/songs/{song['id']}/peaks")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()
