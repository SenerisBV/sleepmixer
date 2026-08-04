"""Run a separation in a child process and be able to stop it.

The parent's whole job is to forward the child's phases, kill it when asked,
and be exact about how it ended — because the three ways it can end need three
different answers and two of them are silent if confused. A cancelled
separation must leave the song exactly as it was; a crashed one must say so;
and only "demucs is not installed", which the child handles itself, may fall
back to treating the whole song as a single stem.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading

from .progress import CancelToken, Cancelled, ProgressReporter
from .separation import (
    SeparationFailed, SeparationResult, _cache_key, _load_cache,
    _load_fallback_reason,
)

_PHASE_PREFIX = "sleepmix-phase "
_POLL_S = 0.1
# Only ever used as a tail for a failure message (`stderr[-2000:]`), so keeping
# a bound well past that is enough — a chatty child must not be able to grow
# this without limit just because nobody is reading it.
_STDERR_KEEP = 8192


class _StderrTail:
    """Drains a pipe on a background thread, retaining only the tail.

    torch and demucs both write warnings to stderr, and an undrained pipe
    fills its OS buffer and blocks the child forever — a separation that
    hangs instead of finishing, with no error anywhere. Draining alone isn't
    enough to make reading it safe: a plain list a thread appends to, read by
    another thread after a ``join(timeout=...)`` that expired, is a data race
    on the exact word "expired" describes — the drain thread can still be
    mid-append while the tail is read. The lock makes that read safe.
    """

    def __init__(self, stream) -> None:
        self._buf = ""
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._drain, args=(stream,), daemon=True)

    def _drain(self, stream) -> None:
        for line in stream:
            with self._lock:
                self._buf = (self._buf + line)[-_STDERR_KEEP:]

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def tail(self) -> str:
        with self._lock:
            return self._buf


def _pump(stream, sink: queue.Queue) -> None:
    for line in stream:
        sink.put(line.rstrip("\n"))
    sink.put(None)


def _wait_bounded(proc: subprocess.Popen, timeout_s: float) -> None:
    """Wait for the child, escalating to a kill it cannot ignore.

    An unbounded ``proc.wait()`` after the read loop breaks is normally a
    no-op (the loop only breaks once ``poll()`` is not ``None``), but "the
    child has already exited" is an assumption, not a guarantee enforced by
    this function's caller — and an assumption that fails silently turns into
    the parent hanging with no cancel token left to poll. Bounding it and
    escalating to ``kill()`` (which, unlike ``terminate()``, the child cannot
    install a handler to ignore) means that assumption failing costs at most
    two timeouts, not forever.
    """
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout_s)


def run_separation(
    input_path: str,
    model: str,
    cache_dir: str,
    reporter: ProgressReporter | None = None,
    cancel: CancelToken | None = None,
    worker_module: str = "sleepmix.separation_worker",
    timeout_s: float = 5.0,
) -> SeparationResult:
    key = _cache_key(input_path, model)
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        # Warm path: no process, no torch import — and the stems already read
        # to answer that question are returned directly rather than reloaded.
        # separate_detailed() would decode every stem a second time purely to
        # rediscover what _load_cache just proved; for a half-hour song, four
        # multi-hundred-megabyte stems decoded twice on every reopen is the
        # "warm path must stay warm" promise broken in the one place it looks
        # like it's being kept.
        return SeparationResult(cached, _load_fallback_reason(cache_dir, key))

    if cancel is not None:
        # Checked before anything is spawned: a request that was already
        # cancelled still raises Cancelled if this line is deleted (the read
        # loop below catches it a poll cycle later), but only after paying
        # for a process spawn that was doomed before it started.
        cancel.check()

    os.makedirs(cache_dir, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", worker_module, input_path, model, cache_dir],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        lines: queue.Queue = queue.Queue()
        reader = threading.Thread(
            target=_pump, args=(proc.stdout, lines), daemon=True)
        reader.start()

        stderr_tail = _StderrTail(proc.stderr)
        stderr_tail.start()

        cancelled = False
        while True:
            if cancel is not None and cancel.cancelled and not cancelled:
                # terminate() first so the child can die tidily; kill() only
                # if it will not. A torch process that ignores SIGTERM is not
                # a reason to keep the operator waiting.
                cancelled = True
                proc.terminate()
                try:
                    proc.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=timeout_s)
            try:
                line = lines.get(timeout=_POLL_S)
            except queue.Empty:
                if proc.poll() is not None and lines.empty():
                    break
                continue
            if line is None:
                break
            if line.startswith(_PHASE_PREFIX):
                rest = line[len(_PHASE_PREFIX):]
                fraction_s, _, message = rest.partition(" ")
                try:
                    fraction = float(fraction_s)
                except ValueError:
                    # A malformed phase line, not a reason to swallow an
                    # exception the caller's own sink raises below — that one
                    # must propagate, not be mistaken for this.
                    continue
                if reporter is not None:
                    reporter.emit("separate", message, fraction)

        _wait_bounded(proc, timeout_s)
        reader.join(timeout=timeout_s)
        stderr_tail.join(timeout=timeout_s)
        stderr = stderr_tail.tail().strip()

        if cancelled or (cancel is not None and cancel.cancelled):
            # Unconditional, and checked before the cache or the exit code:
            # a child that reached _write_cache before it was killed — the
            # worst case in the brief's table — must not have that cache
            # read back as a quiet success just because it happens to be on
            # disk. The operator asked to stop; a result appearing anyway is
            # the wrong answer even when the stems are technically fine.
            raise Cancelled()
        if proc.returncode != 0:
            raise SeparationFailed(
                f"separation worker exited {proc.returncode}: {stderr[-2000:]}")
        result_cache = _load_cache(cache_dir, key)
        if result_cache is None:
            raise SeparationFailed(
                "separation worker exited cleanly but wrote no stems"
                + (f": {stderr[-2000:]}" if stderr else ""))
        return SeparationResult(result_cache, _load_fallback_reason(cache_dir, key))
    finally:
        # Belt and braces: whatever unwound this frame — Ctrl-C reaching the
        # parent mid-separation, the caller's progress sink raising, a
        # MemoryError, a thread failing to start — the child must not be
        # left running. Before this, only the ordinary cancel branch above
        # killed it; every other exit from this function orphaned a live
        # Demucs process: a multi-gigabyte child the operator has to kill by
        # hand, which is the exact incident this task exists to prevent,
        # reached through a different door.
        if proc.poll() is None:
            proc.kill()
            proc.wait()
