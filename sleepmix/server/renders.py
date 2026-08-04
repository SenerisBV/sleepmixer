"""Render bookkeeping that is not a route.

Sits beside :mod:`sleepmix.server.jobs` in the same layer and for the same
reason: ``server/api/`` holds request handlers, ``server/`` holds the machinery
two of them need to agree on. This module exists because settling a render that
produced nothing is now reached from two directions, and a second copy of it
would be two answers to one question.
"""
from __future__ import annotations

import os


def abandon_render(store, render_id: str, output_path: str, status: str) -> None:
    """Record a render that produced nothing, and leave no partial file.

    **Reached from two directions, and both matter.**

    The first is the work function in ``server/api/renders.py``: a render that
    was running and then failed or was cancelled comes through here so the row
    can never be left at "running" and a half-written file can never
    masquerade as a finished render.

    The second is ``POST /api/jobs/{id}/cancel`` in ``server/api/jobs.py``, for
    the case the work function cannot cover — a render cancelled while it was
    still *queued*. ``JobManager._run`` short-circuits without calling the work
    function at all when the token is already set, which is deliberate and is
    what stops a cancelled separation from running Demucs anyway. But the work
    function is the only thing that ever writes this row, so nothing settled
    it: the job read "cancelled" while the row read "queued" forever, and
    ``DELETE /api/renders/{id}`` refuses anything at "queued" or "running", so
    the row could not even be removed. Two screens one click apart disagreed
    about the same render, and the operator had no way to clear it.

    Idempotent on purpose, because those two directions can both fire for one
    render: cancelling a running render settles the row through the work
    function, and a second cancel afterwards arrives here again. Re-recording a
    status the row already has is a no-op, and a file that is already gone is
    the outcome this asks for.

    Errors while cleaning up are swallowed deliberately: on the work-function
    path the original exception is the one worth propagating, and on the route
    path a file that will not delete is a disk problem rather than a reason to
    leave the row stranded.
    """
    try:
        store.update_render(render_id, status=status)
    finally:
        try:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass
