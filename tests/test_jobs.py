import asyncio
import threading
import time

import pytest

from sleepmix.server.jobs import JOB_STATUSES, JobManager


@pytest.fixture
def manager():
    m = JobManager()
    yield m
    m.shutdown(wait=True)


def _wait_for(manager, job_id, statuses, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.status in statuses:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job stayed {manager.get(job_id).status}")


def _wait_for_fraction(manager, job_id, fraction, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.fraction == fraction:
            return job
        time.sleep(0.01)
    raise AssertionError(f"fraction stayed {manager.get(job_id).fraction}")


def test_a_submitted_job_runs_and_reports_its_result(manager):
    release = threading.Event()

    def work(reporter, cancel):
        release.wait(timeout=5.0)
        return {"answer": 42}

    job = manager.submit("test", work)
    assert manager.get(job.id).status in ("queued", "running")
    release.set()

    done = _wait_for(manager, job.id, ("done",))
    assert done.result == {"answer": 42}
    assert done.fraction == 1.0
    assert done.error is None


def test_progress_events_update_the_job(manager):
    """Hold the job open at 0.5 so the reported value is observable.

    Without the gate this could only assert the final 1.0, which completion
    sets regardless of whether any progress event was ever delivered."""
    release = threading.Event()

    def work(reporter, cancel):
        reporter.emit("stage-a", "half way", 0.5)
        release.wait(timeout=5.0)
        return {}

    job = manager.submit("test", work)
    midway = _wait_for_fraction(manager, job.id, 0.5)
    assert midway.message == "half way"
    release.set()
    done = _wait_for(manager, job.id, ("done",))
    assert done.fraction == 1.0


def test_a_raising_job_is_failed_not_lost(manager):
    def work(reporter, cancel):
        raise ValueError("boom")

    job = manager.submit("test", work)
    failed = _wait_for(manager, job.id, ("failed",))
    assert "boom" in failed.error
    assert failed.result is None


def test_cancelling_stops_the_work(manager):
    started = []

    def work(reporter, cancel):
        started.append(1)
        for _ in range(2000):
            cancel.check()
            time.sleep(0.001)
        return {"finished": True}

    job = manager.submit("test", work)
    while not started:
        time.sleep(0.01)
    assert manager.cancel(job.id) is True
    cancelled = _wait_for(manager, job.id, ("cancelled",))
    assert cancelled.result is None


def test_cancelling_an_unknown_job_is_false(manager):
    assert manager.cancel("nope") is False


def test_jobs_run_one_at_a_time(manager):
    """Serial by design — two renders would halve each other's speed."""
    concurrent = []
    running = []

    def work(reporter, cancel):
        running.append(1)
        concurrent.append(len(running))
        time.sleep(0.05)
        running.pop()
        return {}

    ids = [manager.submit("test", work).id for _ in range(3)]
    for job_id in ids:
        _wait_for(manager, job_id, ("done",))
    assert max(concurrent) == 1


def test_every_status_is_declared():
    assert set(JOB_STATUSES) == {"queued", "running", "done", "cancelled", "failed"}


@pytest.mark.asyncio
async def test_subscribers_receive_progress_events():
    loop = asyncio.get_running_loop()
    manager = JobManager(loop=loop)
    release = threading.Event()
    try:
        def work(reporter, cancel):
            # Held here until the test has subscribed, so the event below
            # cannot fire before there is anyone listening for it.
            release.wait(timeout=5.0)
            reporter.emit("stage-a", "working", 0.5)
            return {}

        job = manager.submit("test", work)
        queue = manager.subscribe(job.id)
        assert queue is not None
        release.set()

        seen = []
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=5.0)
            seen.append(event)
            if event["status"] in ("done", "failed", "cancelled"):
                break
        assert any(e["message"] == "working" for e in seen)
        assert seen[-1]["status"] == "done"
    finally:
        release.set()
        manager.shutdown(wait=True)


@pytest.mark.asyncio
async def test_subscribing_to_a_finished_job_yields_its_final_state():
    """A client that connects late must not hang waiting for an event that
    already happened."""
    loop = asyncio.get_running_loop()
    manager = JobManager(loop=loop)
    try:
        job = manager.submit("test", lambda reporter, cancel: {"ok": True})
        deadline = time.time() + 5.0
        while manager.get(job.id).status != "done" and time.time() < deadline:
            time.sleep(0.01)
        queue = manager.subscribe(job.id)
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["status"] == "done"
    finally:
        manager.shutdown(wait=True)
