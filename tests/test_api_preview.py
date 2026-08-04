import io
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client(stub_separation):
    # stub_separation patches sleepmix.session.separate, which RenderSession
    # resolves at construction — so the registry picks up the stub without
    # anything being injected into it.
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, sr=22050, secs=3.0):
    path = tmp_path / "a.wav"
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def test_preview_returns_playable_wav(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/preview", json={"song_id": song["id"], "progress": 0.5})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content), dtype="float32", always_2d=True)
    assert data.shape[0] > 0
    assert np.all(np.isfinite(data))


def test_preview_is_fast_once_the_session_is_warm(client, tmp_path):
    song = _import_song(client, tmp_path)
    client.post("/api/preview", json={"song_id": song["id"], "progress": 0.5})
    start = time.perf_counter()
    client.post("/api/preview", json={"song_id": song["id"], "progress": 0.6})
    assert time.perf_counter() - start < 3.0


def test_different_points_in_the_arc_sound_different(client, tmp_path):
    song = _import_song(client, tmp_path)
    early = client.post("/api/preview",
                        json={"song_id": song["id"], "progress": 0.0}).content
    late = client.post("/api/preview",
                       json={"song_id": song["id"], "progress": 1.0}).content
    assert early != late


def test_soloing_a_stem_changes_the_result(client, tmp_path):
    song = _import_song(client, tmp_path)
    everything = client.post("/api/preview",
                             json={"song_id": song["id"], "progress": 0.5}).content
    one = client.post("/api/preview",
                      json={"song_id": song["id"], "progress": 0.5,
                            "stems": ["vocals"]}).content
    assert everything != one


def test_preview_honours_a_supplied_config(client, tmp_path):
    song = _import_song(client, tmp_path)
    default = client.post("/api/preview",
                          json={"song_id": song["id"], "progress": 0.5}).content
    slower = client.post("/api/preview",
                         json={"song_id": song["id"], "progress": 0.5,
                               "config": {"tempo": {"speed": 0.4}}}).content
    assert default != slower


def test_preview_rejects_a_negative_seed(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/preview",
                    json={"song_id": song["id"], "progress": 0.5,
                          "config": {"seed": -5}})
    assert r.status_code == 400
    assert "seed" in r.json()["detail"].lower()


def test_preview_rejects_out_of_range_progress(client, tmp_path):
    song = _import_song(client, tmp_path)
    for progress in (-1.0, 2.0):
        r = client.post("/api/preview",
                        json={"song_id": song["id"], "progress": progress})
        assert r.status_code == 422


def test_preview_404s_for_an_unknown_song(client):
    r = client.post("/api/preview", json={"song_id": "nope", "progress": 0.5})
    assert r.status_code == 404
