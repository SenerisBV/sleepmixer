import os
import threading
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


def _a_finished_render(client, tmp_path):
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    job = _await_job(client, body["job"]["id"])
    assert job["status"] == "done", job.get("error")
    return client.get(f"/api/renders/{body['render']['id']}").json()


def _a_running_render(client, tmp_path):
    """Hold a render at status 'running' deterministically.

    A real run_pipeline for even the shortest config still takes real wall
    time, and waiting on that would make the test's outcome depend on how
    fast this machine happens to be. Instead, patch run_pipeline to block on
    an Event this helper controls, then poll the render's own status until it
    actually reports 'running' — so the caller never has to guess a sleep
    long enough to win the race.

    The patch is bounded rather than held open forever: if nobody releases the
    gate, it gives up after one second and, if by then the job's token has
    been cancelled (as happens when the app's lifespan shuts the job manager
    down at the end of the test), lets that cancellation through instead of
    running the real pipeline after the test is already over.
    """
    import sleepmix.server.api.renders as renders_api

    gate = threading.Event()
    original = renders_api.run_pipeline

    def blocked(*args, **kwargs):
        if not gate.wait(timeout=1.0):
            cancel = kwargs.get("cancel")
            if cancel is not None and cancel.cancelled:
                cancel.check()
        return original(*args, **kwargs)

    renders_api.run_pipeline = blocked
    try:
        song = _import_song(client, tmp_path)
        body = client.post("/api/renders",
                           json={"song_id": song["id"], "config": _SHORT}).json()
        render_id = body["render"]["id"]

        deadline = time.time() + 5.0
        while time.time() < deadline:
            render = client.get(f"/api/renders/{render_id}").json()
            if render["status"] == "running":
                return render
            time.sleep(0.02)
        raise AssertionError("render never reached status 'running'")
    finally:
        renders_api.run_pipeline = original


def _blocking_render(client, tmp_path):
    """A render held at 'running', plus the gate that releases it.

    `_a_running_render` restores `run_pipeline` before it returns, which is
    right for a test that only needs a render *at* running. These tests need
    the worker still occupied while they do something else, since there is one
    worker and "queued" is only reachable while it is busy. So the patch stays
    in place and the caller is handed the gate and the restore to run itself.
    """
    import sleepmix.server.api.renders as renders_api

    gate = threading.Event()
    original = renders_api.run_pipeline

    def blocked(*args, **kwargs):
        if not gate.wait(timeout=5.0):
            cancel = kwargs.get("cancel")
            if cancel is not None and cancel.cancelled:
                cancel.check()
        return original(*args, **kwargs)

    renders_api.run_pipeline = blocked

    def restore():
        gate.set()
        renders_api.run_pipeline = original

    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if client.get(f"/api/renders/{body['render']['id']}").json()["status"] == "running":
            return song, body, restore
    restore()
    raise AssertionError("the blocking render never reached status 'running'")


def test_cancelling_a_queued_render_settles_its_row_instead_of_stranding_it(client, tmp_path):
    """The row used to be left at 'queued' forever, and could not be deleted.

    `JobManager._run` short-circuits without calling the work function when the
    token is already set, and the work function is the only thing that writes
    this row — so a render cancelled before it started had its job go
    'cancelled' while the row stayed 'queued'. `DELETE /api/renders/{id}`
    refuses anything at 'queued', so there was no way to clear it: the queue
    screen said the job was cancelled, the renders screen said the render was
    still coming, and neither could be made to agree with the other.
    """
    song, blocker, restore = _blocking_render(client, tmp_path)
    try:
        queued = client.post("/api/renders",
                             json={"song_id": song["id"], "config": _SHORT}).json()
        render_id = queued["render"]["id"]
        assert client.get(f"/api/renders/{render_id}").json()["status"] == "queued"

        answer = client.post(f"/api/jobs/{queued['job']['id']}/cancel").json()
        assert answer["cancelled"] is True
        assert answer["job"]["status"] == "cancelled"

        # No polling: the worker is still inside the blocking render and cannot
        # have touched this one, so the row can only have been settled by the
        # cancel route itself.
        assert client.get(f"/api/renders/{render_id}").json()["status"] == "cancelled"
        assert client.get(f"/api/jobs/{blocker['job']['id']}").json()["status"] == "running", (
            "the blocking render must still hold the worker, or this proves nothing")

        # The assertion the whole fix is for: the row is no longer stranded.
        assert client.delete(f"/api/renders/{render_id}").status_code == 204
        assert client.get(f"/api/renders/{render_id}").status_code == 404
    finally:
        restore()


def test_cancelling_a_running_render_leaves_the_row_to_the_work_function(client, tmp_path):
    """The route must not write a row the worker still owns.

    Racing it from the request thread is how 'cancelled' would end up written
    over a 'done' that landed a moment later. The route's guard is the job's
    own status, which `JobManager.cancel` leaves at 'running' precisely so the
    work function keeps ownership — and the row still ends up 'cancelled',
    through `work`'s `except Cancelled`, which is the point.
    """
    song, blocker, restore = _blocking_render(client, tmp_path)
    try:
        render_id = blocker["render"]["id"]
        answer = client.post(f"/api/jobs/{blocker['job']['id']}/cancel").json()
        assert answer["cancelled"] is True
        assert answer["job"]["status"] == "running", (
            "a running job must not be marked cancelled before it has stopped")
        assert client.get(f"/api/renders/{render_id}").json()["status"] == "running", (
            "the route settled a row the work function still owns")
    finally:
        restore()

    _await_job(client, blocker["job"]["id"])
    assert client.get(f"/api/renders/{render_id}").json()["status"] == "cancelled"


def test_cancelling_a_queued_separation_touches_nothing_render_shaped(client, tmp_path):
    """A separation carries no `render_id`, so the new branch must not fire.

    Asserted rather than assumed: the guard is `job.render_id and ...`, and a
    version of it that only checked the status would go looking for a render
    row keyed on None for every separation anyone cancels.
    """
    song, blocker, restore = _blocking_render(client, tmp_path)
    before = {r["id"]: r["status"] for r in client.get("/api/renders").json()["renders"]}
    try:
        separation = client.post(f"/api/songs/{song['id']}/separate?force=true").json()
        assert client.get(f"/api/jobs/{separation['id']}").json()["status"] == "queued"
        assert separation["render_id"] is None

        answer = client.post(f"/api/jobs/{separation['id']}/cancel").json()
        assert answer["cancelled"] is True
        assert answer["job"]["status"] == "cancelled"
        assert answer["job"]["render_id"] is None

        after = {r["id"]: r["status"] for r in client.get("/api/renders").json()["renders"]}
        assert after == before, "cancelling a separation changed a render row"
    finally:
        restore()


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


def test_a_render_job_names_the_render_it_is_producing(client, tmp_path):
    """The job says which render it is making, in the envelope and in the list.

    Without it the only join between the two is "the render of this song
    started around the same time", and that pairing is wrong exactly where it
    hurts: jobs are held in memory and renders in SQLite, so a server restarted
    mid-render leaves a render row at ``running`` with no job of its own — and
    a by-song pairing hands that dead row the *next* render's job. The
    interface then draws the live render's progress on the dead row and puts
    the live render's job id on its Cancel button, so cancelling something that
    finished hours ago kills the render that is actually running and
    ``_abandon`` deletes its file.

    Asserted on `GET /api/jobs` too, because that is where the renders screen
    reads it from; the envelope alone would leave the field free to be dropped
    by ``as_event``.
    """
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    assert body["job"]["render_id"] == body["render"]["id"]

    _await_job(client, body["job"]["id"])
    listed = {j["id"]: j for j in client.get("/api/jobs").json()["jobs"]}
    assert listed[body["job"]["id"]]["render_id"] == body["render"]["id"]


def test_a_separation_job_names_no_render(client, tmp_path):
    """Null rather than absent: the field is on every job, empty on the ones
    that produce no render. The Elm decoder requires it and allows null, so a
    server that stopped sending it fails loudly instead of decoding to the
    "this render has no job" case it cannot be distinguished from."""
    song = _import_song(client, tmp_path)
    job = client.post(f"/api/songs/{song['id']}/separate").json()
    assert "render_id" in job
    assert job["render_id"] is None


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


def test_a_failure_after_cancellation_is_recorded_as_a_failure(client, tmp_path, monkeypatch):
    """The row must classify by exception type, not by the cancel flag.

    A genuine exception raised while the token happens to be set is a failure,
    not a cancellation. Reading the flag records it as cancelled while the job
    records it as failed — two accounts of one render, disagreeing, with the
    user-facing one wrong."""
    import sleepmix.server.api.renders as renders_api

    def cancel_then_explode(input_path, config, output_path, reporter=None, cancel=None):
        cancel.cancel()
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(renders_api, "run_pipeline", cancel_then_explode)
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    finished = _await_job(client, body["job"]["id"])

    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert finished["status"] == "failed"
    assert render["status"] == "failed", "the row must agree with the job"


def test_deleting_a_render_removes_the_row_and_the_file(client, tmp_path):
    render = _a_finished_render(client, tmp_path)
    path = render["path"]
    assert os.path.isfile(path)

    assert client.delete(f"/api/renders/{render['id']}").status_code == 204
    assert client.get(f"/api/renders/{render['id']}").status_code == 404
    assert not os.path.exists(path)


def test_deleting_an_unknown_render_is_a_404(client):
    assert client.delete("/api/renders/nope").status_code == 404


def test_a_render_that_is_still_running_cannot_be_deleted(client, tmp_path):
    """Deleting the file out from under a running pipeline would leave the job
    writing to a path nobody will look at, and the row it would update gone."""
    render = _a_running_render(client, tmp_path)
    response = client.delete(f"/api/renders/{render['id']}")
    assert response.status_code == 409
    assert "cancel" in response.json()["detail"].lower()
