"""A separation worker that does no separation.

Everything about supervising a child process — forwarding its phases, killing
it on cancel, telling a crash from a cancellation — is independent of what the
child computes. Testing that against real Demucs would mean minutes per case
and a machine with torch on it. This stub takes the same argv as the real
worker and is told, through the environment, how to misbehave:

    STUB_SLEEP_S         seconds to sleep after printing its phases (default 0)
    STUB_EXIT_CODE       exit with this code instead of 0
    STUB_NO_CACHE        exit 0 without writing any cache
    STUB_STDOUT_NOISE    print an unparseable line first, as torch does
    STUB_IGNORE_SIGTERM  install a SIGTERM handler that ignores it, so only
                         SIGKILL (never installable by a handler) ends this
                         process — for proving the supervisor's terminate()
                         escalates to kill() rather than waiting forever
    STUB_CACHE_THEN_SLEEP  write the cache *before* sleeping instead of after,
                         so a kill mid-sleep lands with the cache already on
                         disk — the worst case in the task's table, where a
                         cancellation must still win over a result that
                         happens to already exist
"""
from __future__ import annotations

import os
import signal
import sys
import time

import numpy as np

from sleepmix.audio import AudioBuffer
from sleepmix.separation import _cache_key, _write_cache


def _stems() -> dict[str, AudioBuffer]:
    return {
        name: AudioBuffer(np.zeros((100, 2), dtype=np.float32), 44100)
        for name in ("vocals", "drums", "bass", "other")
    }


def main(argv: list[str]) -> int:
    input_path, model, cache_dir = argv[1], argv[2], argv[3]
    if os.environ.get("STUB_IGNORE_SIGTERM"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if os.environ.get("STUB_STDOUT_NOISE"):
        print("some torch warning nobody asked for", flush=True)
    print("sleepmix-phase 0.05 Loading the model", flush=True)
    print("sleepmix-phase 0.15 Separating stems", flush=True)

    cache_first = bool(os.environ.get("STUB_CACHE_THEN_SLEEP"))
    no_cache = bool(os.environ.get("STUB_NO_CACHE"))
    if cache_first and not no_cache:
        _write_cache(cache_dir, _cache_key(input_path, model), _stems(), None)

    time.sleep(float(os.environ.get("STUB_SLEEP_S", "0")))

    code = int(os.environ.get("STUB_EXIT_CODE", "0"))
    if code:
        print("stub failing on purpose", file=sys.stderr, flush=True)
        return code
    if not cache_first and not no_cache:
        _write_cache(cache_dir, _cache_key(input_path, model), _stems(), None)
    print("sleepmix-phase 0.90 Writing stems", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
