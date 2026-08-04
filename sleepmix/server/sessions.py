"""Keep a few songs open so previews stay interactive.

A ``RenderSession`` memoizes separation, loop detection and time-stretching.
Building one costs seconds; reusing one makes a preview cost milliseconds. The
registry exists so consecutive requests about the same song hit the same warm
session instead of paying that cost again.

It is capped because a session holds every stem decoded in memory — a
five-minute stereo track is roughly fifty megabytes per stem, so a few hundred
per song once the stretched loops are cached. Two is enough to A/B two songs
without the process ballooning.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from contextlib import contextmanager
from typing import Iterator

from ..config import MixConfig
from ..session import RenderSession


class SessionRegistry:
    """Warm ``RenderSession`` objects, capped and least-recently-used.

    ``self._lock`` protects *the dictionary and nothing else*. It guarantees
    that the bookkeeping — insert, LRU reorder, eviction — is atomic, and that
    two callers asking for the same song id get the same object rather than
    double-building it. It guarantees nothing at all about what happens to
    that object afterwards, and in particular it is **not** held across
    separation: ``RenderSession.__init__`` does no work, ``stems()`` is lazy,
    and the first ``prepared_loop`` call that actually separates runs long
    after ``get`` returned and released the lock.

    Using a returned session concurrently is therefore unsafe on its own —
    ``update_config`` clears caches an in-flight ``render_window`` is reading.
    Callers that render must go through :meth:`session_for`, which adds a
    per-song lock covering the whole use, not just the lookup.
    """

    def __init__(self, max_sessions: int = 2, separate_fn=None) -> None:
        self.max_sessions = max(int(max_sessions), 1)
        self._separate_fn = separate_fn
        self._lock = threading.RLock()
        # song_id -> (input_path, session); ordered least-recently-used first.
        self._sessions: OrderedDict[str, tuple[str, RenderSession]] = OrderedDict()
        # song_id -> lock guarding *use* of that song's session. Keyed by id
        # rather than by session object, and never removed on eviction: a
        # thread can be holding one while another evicts the session out from
        # under it, and dropping the lock there would hand the next arrival a
        # fresh lock and no mutual exclusion at all. They are a few dozen bytes
        # each and bounded by the number of songs ever previewed in a process.
        self._use_locks: dict[str, threading.RLock] = {}

    def get(self, song_id: str, input_path: str, config: MixConfig) -> RenderSession:
        """The warm session for ``song_id``, building one only if needed."""
        with self._lock:
            existing = self._sessions.get(song_id)
            if existing is not None and existing[0] == input_path:
                session = existing[1]
                # update_config invalidates only the stages the change affects,
                # so a tempo tweak keeps the separated stems.
                session.update_config(config)
                self._sessions.move_to_end(song_id)
                return session

            session = RenderSession(input_path, config, separate_fn=self._separate_fn)
            self._sessions[song_id] = (input_path, session)
            self._sessions.move_to_end(song_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return session

    @contextmanager
    def session_for(self, song_id: str, input_path: str,
                    config: MixConfig) -> Iterator[RenderSession]:
        """Yield the warm session for ``song_id``, held against concurrent use.

        The registry's own lock only protects the dictionary. Rendering runs
        unlocked and takes long enough that a second request routinely overlaps
        it — and ``update_config`` clears caches that an in-flight render is
        already reading. The failure is either a KeyError or, worse, a window
        built from two different configs with no error at all.

        Concretely: thread A is inside ``prepared_loop``, has already found the
        stem present, and is about to index ``self._prepared``; thread B calls
        ``get`` with a different tempo, whose ``update_config`` clears that
        dict. A raises ``KeyError`` and the preview 500s. The silent variant is
        the dangerous one — A reads ``session.config`` under the old config and
        then renders against B's newly-stretched loop.

        ``/api/preview`` is a sync ``def`` route, so FastAPI runs it in AnyIO's
        threadpool: two overlapping previews of one song really are two threads
        on one ``RenderSession``, which the Elm scrubber will produce by the
        handful per drag. So the lock covers the whole body — config read and
        render both — not just the lookup.
        """
        with self._lock:
            lock = self._use_locks.get(song_id)
            if lock is None:
                lock = threading.RLock()
                self._use_locks[song_id] = lock
        with lock:
            # Inside the per-song lock: another thread's update_config cannot
            # land between resolving the session and rendering with it.
            yield self.get(song_id, input_path, config)

    def discard(self, song_id: str) -> None:
        with self._lock:
            self._sessions.pop(song_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            # Only place the use-locks are dropped. Shutdown-shaped, so no
            # renderer should still be holding one; and a stale lock kept
            # forever would be the one real leak this dict could cause.
            self._use_locks.clear()

    def song_ids(self) -> list[str]:
        """Live song ids, least-recently-used first."""
        with self._lock:
            return list(self._sessions.keys())
