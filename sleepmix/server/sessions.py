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

from ..config import MixConfig
from ..session import RenderSession


class SessionRegistry:
    def __init__(self, max_sessions: int = 2, separate_fn=None) -> None:
        self.max_sessions = max(int(max_sessions), 1)
        self._separate_fn = separate_fn
        self._lock = threading.RLock()
        # song_id -> (input_path, session); ordered least-recently-used first.
        self._sessions: OrderedDict[str, tuple[str, RenderSession]] = OrderedDict()

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

    def discard(self, song_id: str) -> None:
        with self._lock:
            self._sessions.pop(song_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def song_ids(self) -> list[str]:
        """Live song ids, least-recently-used first."""
        with self._lock:
            return list(self._sessions.keys())
