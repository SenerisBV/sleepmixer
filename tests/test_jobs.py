import asyncio
import inspect
import threading
import time

import pytest

from sleepmix.server.jobs import JOB_STATUSES, TERMINAL_STATUSES, JobManager


@pytest.fixture
def manager():
    m = JobManager()
    yield m
    m.shutdown(wait=True)


def _wait_for(predicate, timeout=5.0):
    """Poll ``predicate`` every 20ms until true, or fail after ``timeout``.

    The failure message names the predicate's own source rather than a generic
    "timed out", so a hang reads as a diagnosis of what never happened rather
    than just a timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    try:
        desc = inspect.getsource(predicate).strip()
    except (OSError, TypeError):
        desc = repr(predicate)
    raise AssertionError(f"condition never became true: {desc}")


def _wait_for_status(manager, job_id, statuses, timeout=5.0):
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

    done = _wait_for_status(manager, job.id, ("done",))
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
    done = _wait_for_status(manager, job.id, ("done",))
    assert done.fraction == 1.0


def test_a_raising_job_is_failed_not_lost(manager):
    def work(reporter, cancel):
        raise ValueError("boom")

    job = manager.submit("test", work)
    failed = _wait_for_status(manager, job.id, ("failed",))
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
    cancelled = _wait_for_status(manager, job.id, ("cancelled",))
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
        _wait_for_status(manager, job_id, ("done",))
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


def test_terminal_statuses_are_declared_and_partition_the_set():
    """Adding a status must force a decision about whether it ends a stream.

    The SSE generator returns on TERMINAL_STATUSES. A new status that belongs
    there but is forgotten leaves the stream running forever, holding a
    connection and a queue for the life of the process."""
    from sleepmix.server.jobs import JOB_STATUSES, TERMINAL_STATUSES

    assert set(TERMINAL_STATUSES) <= set(JOB_STATUSES)
    assert set(JOB_STATUSES) - set(TERMINAL_STATUSES) == {"queued", "running"}


def test_a_job_cancelled_before_it_starts_never_runs():
    """It used to run anyway: _run flipped the status to 'running' and called
    the work function without ever looking at the token."""
    manager = JobManager(max_workers=1)
    ran = []
    gate = threading.Event()

    def blocker(reporter, cancel):
        gate.wait(timeout=5)
        return {}

    def second(reporter, cancel):
        ran.append(True)
        return {}

    first = manager.submit("test", blocker)
    queued = manager.submit("test", second)
    assert manager.cancel(queued.id) is True
    gate.set()
    _wait_for(lambda: manager.get(queued.id).status in TERMINAL_STATUSES)

    assert ran == [], "the work function ran for a job that was cancelled"
    assert manager.get(queued.id).status == "cancelled"
    manager.shutdown(wait=True)


def test_cancelling_a_queued_job_ends_it_now_rather_than_when_the_worker_gets_there():
    """A cancel nobody can see is a cancel that did not happen.

    ``cancel`` used to only set the token, which is technically enough —
    ``_run`` checks it before doing any work — but the pool does not reach a
    queued job until the one ahead of it finishes, and there is one worker. So
    the status stayed "queued" for as long as the job in front took, and the
    queue screen went on drawing the row as waiting with its Cancel button
    still on it.

    That is exactly the case the queue screen was built for: a very long
    separation running, a render queued behind it, and an operator trying to
    get the render out of the way. Measured in the shape that matters here —
    the job ahead is still blocked when the assertions run, so this can only
    pass if the flip happened synchronously inside ``cancel``.
    """
    manager = JobManager(max_workers=1)
    gate = threading.Event()
    started = threading.Event()
    ran = []

    def blocker(reporter, cancel):
        started.set()
        gate.wait(timeout=5)
        return {}

    def second(reporter, cancel):
        ran.append(True)
        return {}

    try:
        first = manager.submit("test", blocker)
        assert started.wait(timeout=5), "the blocking job never started"
        queued = manager.submit("test", second)
        assert manager.get(queued.id).status == "queued"

        assert manager.cancel(queued.id) is True
        # No _wait_for, deliberately: the worker is still inside `blocker` and
        # cannot have touched this job at all.
        assert manager.get(queued.id).status == "cancelled"
        assert manager.get(queued.id).message == "Cancelled"
        assert manager.get(first.id).status == "running", (
            "the job ahead must still be blocked, or this proves nothing")

        # And it stays cancelled once the worker does reach it, rather than
        # being walked back to "running" by `_run`.
        gate.set()
        _wait_for(lambda: manager.get(first.id).status in TERMINAL_STATUSES)
        assert ran == []
        assert manager.get(queued.id).status == "cancelled"

        # Nothing left to stop, and the caller can tell that apart from
        # "asked to stop" — the UI says different things for the two.
        assert manager.cancel(queued.id) is False
    finally:
        gate.set()
        manager.shutdown(wait=True)


def test_cancelling_a_running_job_leaves_the_status_to_the_work_function():
    """Only the *queued* case is decided by `cancel`.

    A running job is genuinely still running when the token is set — the work
    function stops at its next `check()` — so writing "cancelled" over it here
    would claim an outcome that has not happened yet, and would race `_run`'s
    own terminal update.
    """
    manager = JobManager(max_workers=1)
    started = threading.Event()
    proceed = threading.Event()

    def work(reporter, cancel):
        started.set()
        # Held here rather than looping on `check()`, so the assertion below
        # is not racing the work function: without this gate the job could
        # legitimately reach `cancelled` in the microseconds after `cancel`
        # returns, and the test would flake for the right reason.
        proceed.wait(timeout=5)
        for _ in range(2000):
            cancel.check()
            time.sleep(0.001)
        return {}

    try:
        job = manager.submit("test", work)
        assert started.wait(timeout=5)
        assert manager.cancel(job.id) is True
        assert manager.get(job.id).status == "running", (
            "a running job must not be marked cancelled before it has stopped")
        proceed.set()
        assert _wait_for_status(manager, job.id, ("cancelled",)).result is None
    finally:
        proceed.set()
        manager.shutdown(wait=True)


def test_terminal_jobs_are_evicted_but_live_ones_never_are():
    manager = JobManager(max_workers=1, keep_terminal=3)
    done = [manager.submit("test", lambda r, c: {}) for _ in range(6)]
    for job in done:
        # A job this old may already have finished *and* been evicted by the
        # time we get here — these are near-instant no-ops on a single
        # worker, so the pool can easily race ahead of this loop. Eviction
        # only ever happens after a job goes terminal, so "gone" is as valid
        # a wait-condition here as "terminal": either way it is no longer
        # in flight.
        _wait_for(lambda job=job: manager.get(job.id) is None
                  or manager.get(job.id).status in TERMINAL_STATUSES)

    remaining = [j.id for j in manager.list()]
    assert len(remaining) == 3
    assert remaining == [j.id for j in done[-3:]], "evicted the newest, not the oldest"
    manager.shutdown(wait=True)


def test_a_job_carries_when_it_was_created():
    manager = JobManager(max_workers=1)
    job = manager.submit("test", lambda r, c: {})
    assert job.as_event()["created_at"]
    manager.shutdown(wait=True)
