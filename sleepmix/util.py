"""Small shared helpers: dB conversions and decay-curve shaping."""
from __future__ import annotations

import numpy as np


def db_to_amp(db: float) -> float:
    """Convert decibels to a linear amplitude multiplier."""
    return float(10.0 ** (db / 20.0))


def amp_to_db(amp: float) -> float:
    """Convert a linear amplitude multiplier to decibels."""
    return float(20.0 * np.log10(max(amp, 1e-12)))


def shape_progress(p: float, curve: str = "linear") -> float:
    """Reshape a linear progress value ``p`` in [0, 1] with a named curve.

    - ``linear``: identity.
    - ``exp``: ease-in (``p**2``) — stays pristine longer, then collapses fast.
    - ``log``: ease-out (``sqrt(p)``) — degrades quickly, then lingers.
    """
    p = float(np.clip(p, 0.0, 1.0))
    if curve == "exp":
        return p * p
    if curve == "log":
        return float(np.sqrt(p))
    return p


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between ``a`` and ``b`` by ``t`` in [0, 1]."""
    return float(a + (b - a) * t)
