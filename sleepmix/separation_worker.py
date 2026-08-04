"""One separation, in its own process, so it can be killed.

Demucs is a single opaque call — ``apply_model`` returns when it returns, and
no cancel token gets a look in. Before this existed, cancelling a running
separation set a flag nobody would read until the work was already done, which
meant a large file blocked everything behind it until the server was killed by
hand.

The handoff to the parent is the stem cache, which already existed: this writes
it, the parent reads it. No arrays cross the process boundary.

Run as ``python -m sleepmix.separation_worker <input> <model> <cache_dir>``.
"""
from __future__ import annotations

import sys

from .separation import separate_detailed


def _phase(fraction: float, message: str) -> None:
    # Flushed per line: the parent reads these as they arrive, and a buffered
    # phase is a progress bar that stalls for the length of the separation.
    print(f"sleepmix-phase {fraction} {message}", flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: python -m sleepmix.separation_worker "
              "<input> <model> <cache_dir>", file=sys.stderr)
        return 2
    input_path, model, cache_dir = argv[1], argv[2], argv[3]
    _phase(0.05, "Loading the model")
    _phase(0.15, "Separating stems")
    # Demucs-unavailable is handled in here, writing the one-stem 'mix'
    # fallback and its marker, and exiting 0. That keeps the fallback attached
    # to the one question it answers; every other way of ending is a failure
    # the parent must not paper over.
    separate_detailed(input_path, model, cache_dir)
    _phase(0.90, "Writing stems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
