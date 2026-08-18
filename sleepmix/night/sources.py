"""What the planner is allowed to know about a song.

A ``SourceProfile`` is the whole of the interface between the expensive half
of this feature and the cheap half. ``prepare`` separates, finds loops,
stretches and analyses; everything after that reads a path, a frame count and
a list of frequencies.

**This module imports no audio, and that is load-bearing rather than tidy.**
``night/plan.py`` imports it, and `plan.py` is under an AST guard that keeps an
eight-hour night plannable in microseconds. A profile is data about audio, not
audio.

Every failure here is a skip. A profile written by an older version, half
written, or naming a file that has since moved is an ordinary thing to find in
a directory a person drops files into — and the correct response is one fewer
source, not a night that will not start.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass

from ..paths import data_dir

PROFILE_SUFFIX = ".night.json"

# One octave. Two pitch sets cannot be further apart than this after folding,
# so it is also what an empty or entirely-unusable pitch set is scored as: a
# pitchless source is maximally distant from everything, which puts it last
# in the running rather than crashing the comparison. Defined ahead of
# ``pitch_distance`` — the function that reads it — on purpose; Python
# resolves a module-level name at call time either way, but a reader
# shouldn't have to know that to trust the value is already there.
_MAX_DISTANCE_CENTS = 1200.0


@dataclass(frozen=True)
class SourceProfile:
    """One prepared song, as numbers and paths."""

    source_id: str
    loop_paths: tuple[str, ...]
    loop_frames: tuple[int, ...]
    pitch_set: tuple[float, ...]
    sr: int


def sources_directory() -> str:
    """Where songs are dropped. Created on demand."""
    path = os.path.join(str(data_dir()), "sources")
    os.makedirs(path, exist_ok=True)
    return path


def profiles_directory() -> str:
    """Where ``prepare`` writes what it worked out. Created on demand."""
    path = os.path.join(str(data_dir()), "profiles")
    os.makedirs(path, exist_ok=True)
    return path


def write_profile(profile: SourceProfile) -> str:
    """Write ``profile`` and return its path.

    Written to a temporary name and renamed, so a `prepare` interrupted here
    leaves either the previous profile or none — the same discipline
    ``separation._write_cache`` uses for the same reason.
    """
    final = os.path.join(profiles_directory(),
                         profile.source_id + PROFILE_SUFFIX)
    staging = final + ".partial"
    with open(staging, "w") as fh:
        json.dump(asdict(profile), fh, indent=2, sort_keys=True)
    os.replace(staging, final)
    return final


def _read_profile(path: str) -> SourceProfile | None:
    """One profile, or ``None`` if it is unusable for any reason."""
    try:
        with open(path) as fh:
            raw = json.load(fh)
        profile = SourceProfile(
            source_id=str(raw["source_id"]),
            loop_paths=tuple(str(p) for p in raw["loop_paths"]),
            loop_frames=tuple(int(n) for n in raw["loop_frames"]),
            pitch_set=tuple(float(f) for f in raw["pitch_set"]),
            sr=int(raw["sr"]),
        )
    except Exception:
        return None

    # A profile naming no material cannot produce a voice, and one whose
    # paths and lengths disagree would index off the end of one of them.
    if not profile.loop_paths:
        return None
    if len(profile.loop_paths) != len(profile.loop_frames):
        return None
    if any(n <= 0 for n in profile.loop_frames):
        return None
    # A non-positive sample rate is meaningless (JSON's ``json.load`` also
    # happily parses "NaN"/"Infinity" into float, and ``int()`` of those
    # raises and is already caught above) and everything downstream that
    # turns a frame count into a duration divides by it.
    if profile.sr <= 0:
        return None
    return profile


def load_profiles() -> tuple[SourceProfile, ...]:
    """Every usable profile, in a stable order. Never raises.

    Order is by ``source_id`` rather than by directory order, so the same set
    of files produces the same night on two machines.
    """
    try:
        names = sorted(n for n in os.listdir(profiles_directory())
                       if n.endswith(PROFILE_SUFFIX))
    except OSError:
        return ()

    found = []
    for name in names:
        profile = _read_profile(os.path.join(profiles_directory(), name))
        if profile is not None:
            found.append(profile)
    return tuple(sorted(found, key=lambda p: p.source_id))


def pitch_distance(a: SourceProfile, b: SourceProfile) -> float:
    """How far apart two profiles sit tonally, in cents.

    Used by the planner to choose which source takes the stage next, so that
    the overlap during a handover is consonant rather than a collision. For
    each pitch in ``a``, the distance to its nearest neighbour in ``b``;
    averaged — not symmetric in general, since ``pitch_distance(a, b)`` walks
    ``a``'s pitches against ``b`` while ``pitch_distance(b, a)`` walks ``b``'s
    against ``a``. An empty set on either side is maximally distant rather
    than an error, which puts a pitchless source last in the running.

    Pitches are filtered to finite, positive values before anything is
    compared: ``math.log2(hz / other)`` is undefined at zero and negative, and
    a profile carrying such a value is not hypothetical — ``_read_profile``
    validates ``loop_frames`` and ``sr`` but nothing stops an older or hand
    edited profile from naming a zero or negative pitch, and this is the
    function that would otherwise raise on it instead of skipping it.
    """
    a_valid = tuple(hz for hz in a.pitch_set if math.isfinite(hz) and hz > 0)
    b_valid = tuple(hz for hz in b.pitch_set if math.isfinite(hz) and hz > 0)
    if not a_valid or not b_valid:
        return _MAX_DISTANCE_CENTS

    total = 0.0
    for hz in a_valid:
        total += min(abs(1200.0 * math.log2(hz / other))
                     for other in b_valid)
    return total / len(a_valid)
