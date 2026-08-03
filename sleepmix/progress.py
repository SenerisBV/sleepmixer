"""Structured progress reporting and cooperative cancellation.

The pipeline used to take a bare ``Callable[[str], None]`` and print sentences
at it. That is enough for a terminal but not for a UI, which needs to know
*which* stage is running and how far along the whole render is. Events carry
both; the CLI adapts them back to plain strings via ``echo_sink`` so its output
is unchanged.

Cancellation is cooperative: long loops call ``CancelToken.check()`` at points
where abandoning the work is safe.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator


class Cancelled(Exception):
    """Raised by ``CancelToken.check`` once cancellation has been requested."""


@dataclass(frozen=True)
class ProgressEvent:
    stage: str            # separate | loop | stem | soundbed | master
    stem: str | None
    fraction: float       # 0..1 across the whole render
    message: str


Sink = Callable[[ProgressEvent], None]


class CancelToken:
    """A flag the caller can raise and long-running work polls."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def check(self) -> None:
        if self._cancelled:
            raise Cancelled("render cancelled")


class ProgressReporter:
    """Emits :class:`ProgressEvent` to a sink, keeping ``fraction`` sane.

    ``fraction`` is clamped to [0, 1] and never allowed to go backwards, since a
    progress bar that retreats is worse than one that stalls."""

    def __init__(self, sink: Sink | None = None) -> None:
        self._sink = sink
        self._last = 0.0
        self._lo = 0.0
        self._hi = 1.0

    def emit(self, stage: str, message: str, fraction: float,
             stem: str | None = None) -> None:
        local = min(max(float(fraction), 0.0), 1.0)
        overall = self._lo + (self._hi - self._lo) * local
        overall = min(max(overall, self._last), 1.0)
        self._last = overall
        if self._sink is not None:
            self._sink(ProgressEvent(stage=stage, stem=stem,
                                     fraction=overall, message=message))

    @contextmanager
    def stage_range(self, lo: float, hi: float) -> Iterator["ProgressReporter"]:
        """Scope emissions to the ``[lo, hi]`` slice of overall progress.

        Inside the block, ``emit(..., 0.5)`` means "half way through this
        stage", not "half way through the render"."""
        prev = (self._lo, self._hi)
        self._lo, self._hi = lo, hi
        try:
            yield self
        finally:
            self._lo, self._hi = prev


def echo_sink(echo: Callable[[str], None]) -> Sink:
    """Adapt events back to the plain strings the CLI has always printed."""
    def sink(event: ProgressEvent) -> None:
        echo(event.message)
    return sink
