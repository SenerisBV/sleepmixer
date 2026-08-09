"""Small shared helpers: dB conversions and decay-curve shaping."""
from __future__ import annotations

import hashlib

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


def iteration_rng(seed: int, key: str, iteration: int) -> np.random.Generator:
    """A generator determined solely by ``(seed, key, iteration)``.

    Deriving randomness per iteration rather than drawing from one shared stream
    is what lets a preview of a single point in the decay arc reproduce exactly
    what the full render produces there. With a shared generator, iteration i's
    noise depends on every draw before it, so nothing can be previewed in
    isolation.

    ``key`` is any string naming *which voice* this iteration belongs to; this
    function only hashes it. The parameter used to be called ``stem``, and was
    a bare stem name, which stopped being the whole story once the arrangement
    landed: ``disintegration.decayed_iteration`` is the single place the key is
    composed and it passes ``f"{source_id}:{index}:{stem}"``, so two segments
    of the same stem from the same source draw different noise. Nothing else
    may build that string — see ``decayed_iteration``'s docstring for what
    happened the one time two code paths composed it separately."""
    h = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    return np.random.default_rng([int(seed), h, int(iteration)])
