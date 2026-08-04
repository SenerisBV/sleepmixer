import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client(stub_separation):
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, sr=22050, secs=3.0):
    path = tmp_path / "a.wav"
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def _await_job(client, job_id, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("render never finished")


_SHORT = {"output": {"duration_min": 0.05, "sample_rate": 22050,
                     "fade_in_s": 0.0, "fade_out_s": 0.0}}


def test_render_produces_a_downloadable_file(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/renders", json={"song_id": song["id"], "config": _SHORT})
    assert r.status_code == 202
    body = r.json()
    job = _await_job(client, body["job"]["id"])
    assert job["status"] == "done", job.get("error")

    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["status"] == "done"

    audio = client.get(f"/api/renders/{body['render']['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


def test_render_records_the_config_that_made_it(client, tmp_path):
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    _await_job(client, body["job"]["id"])
    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["config"]["output"]["duration_min"] == 0.05


def test_listing_renders(client, tmp_path):
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    _await_job(client, body["job"]["id"])
    ids = [r["id"] for r in client.get("/api/renders").json()["renders"]]
    assert body["render"]["id"] in ids


def test_render_404s_for_an_unknown_song(client):
    r = client.post("/api/renders", json={"song_id": "nope"})
    assert r.status_code == 404


def test_audio_404s_before_the_render_finishes(client, tmp_path):
    """The row exists from the moment the job is queued; the file does not."""
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    render_id = body["render"]["id"]
    early = client.get(f"/api/renders/{render_id}/audio")
    _await_job(client, body["job"]["id"])
    assert early.status_code in (404, 409)


def test_a_cancelled_render_is_marked_cancelled(client, tmp_path):
    song = _import_song(client, tmp_path)
    long_config = {"output": {"duration_min": 30.0, "sample_rate": 22050}}
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": long_config}).json()
    job_id = body["job"]["id"]

    deadline = time.time() + 10.0
    while client.get(f"/api/jobs/{job_id}").json()["status"] == "queued":
        if time.time() > deadline:
            raise AssertionError("render never started")
        time.sleep(0.02)

    client.post(f"/api/jobs/{job_id}/cancel")
    finished = _await_job(client, job_id)
    assert finished["status"] == "cancelled"
    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["status"] == "cancelled"


def test_render_rejects_a_negative_seed(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/renders",
                    json={"song_id": song["id"], "config": {"seed": -3}})
    assert r.status_code == 400


def test_a_failed_render_is_marked_failed_even_after_a_cancel(client, tmp_path, monkeypatch):
    """The row must agree with the job about what happened.

    Classifying by a cancel flag rather than by exception type mislabels a
    genuine failure as a cancellation whenever the token happens to be set."""
    import sleepmix.server.api.renders as renders_api

    def boom(*_a, **_k):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(renders_api, "run_pipeline", boom)
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    finished = _await_job(client, body["job"]["id"])
    assert finished["status"] == "failed"

    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["status"] == "failed"
    assert client.get(f"/api/renders/{body['render']['id']}/audio").status_code == 404
