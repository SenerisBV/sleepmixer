"""Force librosa's just-in-time compilation before a user can trigger it.

librosa leans on numba, which compiles on first call. Cold, that first call can
take minutes; warm, it is under a second. A UI that stalls for two minutes the
first time you open a song reads as broken, so the server pays that cost at
startup instead, on a throwaway buffer.

Silent when librosa is not installed — it is an optional dependency and the
pipeline degrades to a fixed-tempo loop guess without it.
"""
from __future__ import annotations

import threading

import numpy as np

_warmed = False
_lock = threading.Lock()


def is_warm() -> bool:
    return _warmed


def warm_analysis() -> None:
    """Run a tiny beat-track so the JIT compiles now rather than on first use."""
    global _warmed
    with _lock:
        if _warmed:
            return
        try:
            import librosa

            sr = 22050
            t = np.arange(sr) / sr
            y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
            librosa.beat.beat_track(y=y, sr=sr)
        except Exception:  # noqa: BLE001 - librosa is optional; warming is best-effort
            pass
        _warmed = True
