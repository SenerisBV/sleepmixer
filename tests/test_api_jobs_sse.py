import json
import time

import pytest
from fastapi.testclient import TestClient

from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _events(raw: str) -> list[dict]:
    return [json.loads(line[len("data: "):])
            for line in raw.splitlines() if line.startswith("data: ")]


def test_stream_delivers_events_and_closes_on_completion(client):
    def work(reporter, cancel):
        reporter.emit("stage", "working", 0.5)
        return {"ok": True}

    job = client.app.state.jobs.submit("test", work)
    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = "".join(response.iter_text())

    events = _events(body)
    assert events, "stream produced no events"
    assert events[-1]["status"] == "done"


def test_stream_for_a_finished_job_returns_its_final_state(client):
    """A client that connects after the job finished must not hang."""
    job = client.app.state.jobs.submit("test", lambda reporter, cancel: {"ok": True})
    deadline = time.time() + 5.0
    while client.app.state.jobs.get(job.id).status != "done" and time.time() < deadline:
        time.sleep(0.01)

    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        body = "".join(response.iter_text())
    events = _events(body)
    assert events[-1]["status"] == "done"


def test_stream_404s_for_an_unknown_job(client):
    assert client.get("/api/jobs/nope/events").status_code == 404


def test_a_failed_job_closes_the_stream_with_its_error(client):
    def work(reporter, cancel):
        raise ValueError("boom")

    job = client.app.state.jobs.submit("test", work)
    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        body = "".join(response.iter_text())
    events = _events(body)
    assert events[-1]["status"] == "failed"
    assert "boom" in events[-1]["error"]
