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
    separate_detailed,
)

_PHASE_PREFIX = "sleepmix-phase "
_POLL_S = 0.1


def _pump(stream, sink: queue.Queue) -> None:
    for line in stream:
        sink.put(line.rstrip("\n"))
    sink.put(None)


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
    if _load_cache(cache_dir, key) is not None:
        # Warm path: no process, no torch import. Roughly every separated song
        # the operator reopens takes this branch.
        return separate_detailed(input_path, model, cache_dir)

    if cancel is not None:
        cancel.check()

    os.makedirs(cache_dir, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", worker_module, input_path, model, cache_dir],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

    lines: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    reader.start()

    # stderr is drained on its own thread rather than read at the end. torch and
    # demucs both write warnings there, and an undrained pipe fills its buffer
    # and blocks the child forever — a separation that hangs instead of
    # finishing, with no error anywhere. Collected into a list so the tail is
    # available for the failure message.
    errs: list[str] = []
    draining = threading.Thread(
        target=lambda: errs.extend(proc.stderr), daemon=True)
    draining.start()

    cancelled = False
    while True:
        if cancel is not None and cancel.cancelled and not cancelled:
            # terminate() first so the child can die tidily; kill() only if it
            # will not. A torch process that ignores SIGTERM is not a reason to
            # keep the operator waiting.
            cancelled = True
            proc.terminate()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            line = lines.get(timeout=_POLL_S)
        except queue.Empty:
            if proc.poll() is not None and lines.empty():
                break
            continue
        if line is None:
            break
        if reporter is not None and line.startswith(_PHASE_PREFIX):
            rest = line[len(_PHASE_PREFIX):]
            fraction, _, message = rest.partition(" ")
            try:
                reporter.emit("separate", message, float(fraction))
            except ValueError:
                pass

    proc.wait()
    reader.join(timeout=timeout_s)
    draining.join(timeout=timeout_s)
    stderr = "".join(errs).strip()

    if cancelled or (cancel is not None and cancel.cancelled):
        raise Cancelled()
    if proc.returncode != 0:
        raise SeparationFailed(
            f"separation worker exited {proc.returncode}: {stderr[-2000:]}")
    if _load_cache(cache_dir, key) is None:
        raise SeparationFailed(
            "separation worker exited cleanly but wrote no stems"
            + (f": {stderr[-2000:]}" if stderr else ""))
    return separate_detailed(input_path, model, cache_dir)
