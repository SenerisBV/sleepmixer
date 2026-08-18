"""The expensive half of the ghost, done whenever it suits you.

Separation takes minutes and spins a laptop's fans up; loop detection and
time-stretching are seconds each. All of it happens here, in a command you run
when you are awake, so that ``sleepmix night`` can start instantly and in
silence. **Nothing on the playback path may import this module** — there is a
test asserting exactly that, because the failure it prevents is a fan running
next to a bed.

What comes out is a ``SourceProfile``: paths, frame counts and frequencies.
What goes in is whatever is in the sources folder.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Callable

from ..analysis import find_loop, slice_loop
from ..audio import resample, save_audio, sum_buffers
from ..config import LoopConfig
from ..looping import make_seamless
from ..separation import separate
from ..timestretch import slow_and_pitch
from .pitch import pitch_set
from .sources import (
    PROFILE_SUFFIX, SourceProfile, load_profiles, profiles_directory,
    sources_directory, write_profile,
)

_log = logging.getLogger(__name__)

# How many loops one song contributes. Enough that a stretch of the night has
# internal variety without any one recurring often. A placeholder.
LOOPS_PER_SOURCE = 3

# Short enough to carry no phrase. Four bars is roughly eight seconds at 120
# BPM, and moves with the detected tempo. A placeholder.
LOOP_BARS = 4

# Slower than played, which pulls gesture below the rate the ear tracks
# phrasing at. A placeholder.
STRETCH_SPEED = 0.6

# A drum kit looping under you at 2 AM is what `sleepmix render`'s shipped
# defaults already turn off by hand.
DROP_STEMS = ("drums",)

_MEDIA_SUFFIXES = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aif", ".aiff")

# Where in the track each loop is looked for, as fractions. Spread out so the
# three loops are genuinely different passages rather than three readings of
# one chorus.
_SEARCH_WINDOWS = ((0.20, 0.40), (0.40, 0.60), (0.60, 0.80))


def source_id_for(path: str) -> str:
    """A stable, filesystem-safe identifier for a source path.

    Folds in the file's size and modification time when they can be read, not
    only the path. A song edited in place — same filename, different content
    — must not read as "already prepared" forever: ``prepare_all`` skips a
    path whose id is already in the profiles directory, and a purely
    path-based id would make that skip permanent even after the audio
    underneath it changed. ``separation._cache_key`` uses the same
    ``size:mtime`` pairing for the same reason.

    A path that cannot be ``stat``'d — including one that does not exist at
    all, which is how the id-stability tests exercise this function — falls
    back to hashing the path alone, which is what made this function
    deterministic before the size/mtime were added.

    The trade this makes: hashing the file's *contents* would catch every
    edit and nothing else, but costs a full read of every song on every
    ``prepare_all`` sweep just to answer "did this change?". ``size:mtime``
    is the cheap proxy instead — right in the common case (an edit changes
    at least one of them), wrong in the uncommon one (a ``touch``, a backup
    restore, or a copy that loses timestamps triggers a needless
    re-separation of unchanged audio). Wasted minutes, not wrong output.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:40]

    identity = os.path.abspath(path)
    try:
        st = os.stat(path)
        identity = f"{identity}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        pass

    digest = hashlib.sha256(identity.encode()).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else digest


def _kept_stems(stems: dict) -> dict:
    """Everything separation returned except the ones a night does not want.

    Factored out so a test can watch what survives — the drums-dropped rule is
    the one decision here with an audible consequence.
    """
    kept = {k: v for k, v in stems.items() if k not in DROP_STEMS}
    # Separation with no Demucs returns a single `mix` stem; dropping nothing
    # from it is correct, and dropping everything would be silence.
    return kept or dict(stems)


def prepare_source(path: str, sr: int = 44100,
                   *, source_id: str | None = None) -> SourceProfile | None:
    """Separate, loop, stretch and analyse one song. ``None`` if it will not.

    Every failure is one fewer source rather than a raised exception: a
    directory a person drops files into will contain things that are not
    songs, and finding one is ordinary. The one exception is ``write_profile``
    below, which is deliberately called partly outside that net — see its
    comment.

    ``source_id`` is computed from ``path`` if not given. ``prepare_all``
    already has to compute it once to decide whether to call this function at
    all; passing it through here saves a second `stat` and hash of the same
    file rather than silently redoing work its caller already did.
    """
    # LOOPS_PER_SOURCE and _SEARCH_WINDOWS are both constants defined a few
    # lines apart in this file, and nothing enforces that they stay in step.
    # `_SEARCH_WINDOWS[:LOOPS_PER_SOURCE]` would silently hand back fewer
    # loops than promised if they drifted apart — a programming error, not a
    # fact about any particular song, so it fails loudly here rather than
    # blending into the broad `except Exception` below.
    if LOOPS_PER_SOURCE > len(_SEARCH_WINDOWS):
        raise RuntimeError(
            f"LOOPS_PER_SOURCE={LOOPS_PER_SOURCE} exceeds the "
            f"{len(_SEARCH_WINDOWS)} search windows defined in "
            f"_SEARCH_WINDOWS; add more windows or lower LOOPS_PER_SOURCE."
        )

    if source_id is None:
        source_id = source_id_for(path)
    try:
        stems = _kept_stems(separate(path))
        # `sr` is the profile's promised sample rate, not merely a display
        # default: without resampling here, a source whose file (or whose
        # separation backend) happens to run at some other rate would report
        # a `profile.sr` that silently disagreed with what the caller asked
        # for, and every source `prepare_all` produces would need to agree on
        # one rate for `night` to mix them together.
        stems = {name: resample(buf, sr) for name, buf in stems.items()}
        reference = sum_buffers(list(stems.values()))

        loop_paths: list[str] = []
        loop_frames: list[int] = []
        analysed = []

        for i, (lo, hi) in enumerate(_SEARCH_WINDOWS[:LOOPS_PER_SOURCE]):
            cfg = LoopConfig(bars=LOOP_BARS, search_start=lo, search_end=hi)
            point = find_loop(reference, cfg)
            raw = slice_loop(reference, point)
            seamless = make_seamless(raw, cfg.crossfade_ms)
            stretched = slow_and_pitch(seamless, STRETCH_SPEED, 0.0)
            if stretched.n_frames <= 0:
                continue

            out = os.path.join(profiles_directory(), f"{source_id}-{i}.wav")
            save_audio(stretched, out)
            loop_paths.append(out)
            loop_frames.append(stretched.n_frames)
            analysed.append(stretched)

        if not loop_paths:
            return None

        # One pooled set per source rather than one per loop: a ghost of *this
        # song* is the more useful object, and the handover preference reasons
        # at song level too.
        pooled = sum_buffers(analysed)
        profile = SourceProfile(
            source_id=source_id,
            source_path=os.path.abspath(path),
            loop_paths=tuple(loop_paths),
            loop_frames=tuple(loop_frames),
            pitch_set=pitch_set(pooled),
            sr=analysed[0].sr,
        )
    except Exception:
        return None

    # `write_profile` can fail two genuinely different ways, and they are not
    # treated the same. Its own docstring is explicit that an unsafe
    # `source_id` — the ``ValueError`` case — is "a programming error to be
    # caught at the source, not a fact about the world to route around," so
    # that one is left to propagate rather than being caught here; every
    # `source_id` this module hands it comes from `source_id_for`, so seeing
    # one anyway means that function is broken, not that this song is
    # unusable. An `OSError` (disk full, permissions, a failed `os.replace`)
    # says nothing about whether the id was safe — it is the same kind of
    # ordinary environmental failure every other line in the `try` above is
    # allowed to have, and losing the other nineteen songs in a batch to one
    # disk hiccup on the twentieth would be exactly backwards. So only
    # `OSError` is caught here; a bad id still surfaces loudly.
    try:
        write_profile(profile)
    except OSError:
        return None
    return profile


def _is_inside_profiles_directory(path: str) -> bool:
    """True if ``path`` resolves to a file directly inside
    ``profiles_directory()`` — the one check standing between a stale
    profile's fields and ``os.remove``.

    ``_delete_superseded`` deletes paths it read out of a profile on disk,
    and ``_read_profile`` — deliberately — tolerates a profile "written by an
    older version, half written, or naming a file that has since moved."
    Nothing upstream of this function guarantees ``old.source_id`` is free of
    ``..`` or that ``old.loop_paths`` names anything under
    ``profiles_directory()`` at all; `write_profile` enforces that on the way
    *in*, but a hand-edited or foreign-written ``.night.json`` skips that
    gate entirely and reaches this function anyway. So the check happens
    here, at the one step that is irreversible, rather than trusting the read
    path to have already ruled it out.

    ``realpath``, not ``abspath``: ``abspath`` collapses a lexical ``..`` but
    does not follow symlinks, so a symlinked profiles directory or a
    symlinked loop file would still resolve outside it undetected.  The
    resolved *parent directory* is compared for equality, not with
    ``startswith`` — a prefix match would also accept a sibling directory
    that merely shares a name prefix (``profiles-old`` starting with
    ``profiles``).
    """
    resolved_dir = os.path.realpath(profiles_directory())
    resolved_path = os.path.realpath(path)
    return os.path.dirname(resolved_path) == resolved_dir


def _delete_superseded(new_profile: SourceProfile,
                       prior: tuple[SourceProfile, ...]) -> None:
    """Remove any profile in ``prior`` that names the same source file as
    ``new_profile`` but under a different id.

    That combination — same ``source_path``, different ``source_id`` — is
    exactly what a source edited in place produces: `source_id_for` folds in
    size and mtime, so the edit earns a new id, and without this the old
    profile would simply sit alongside the new one, both loadable, both
    schedulable, as though they were two different songs rather than two
    versions of one.

    Matched on the *full* ``source_path``, never a prefix — this deletes
    files, and a prefix match would treat an unrelated song whose path merely
    starts the same way as the same source.

    Every path this removes is checked with `_is_inside_profiles_directory`
    first, independently for the constructed ``.night.json`` path and for
    each entry in ``old.loop_paths`` — a profile can be malformed in either
    field alone, and one bad entry must not block cleanup of the others. A
    path that fails the check is skipped and logged, not raised on: this runs
    inside `prepare_all`, and one unremovable orphan must not cost the batch.

    Wrapped in its own ``try``/``except OSError``: failing to clean up an old
    profile must not cost the new one that is already written and valid on
    disk. Best-effort, not load-bearing.
    """
    for old in prior:
        if old.source_path != new_profile.source_path:
            continue
        if old.source_id == new_profile.source_id:
            continue
        try:
            old_json = os.path.join(
                profiles_directory(), old.source_id + PROFILE_SUFFIX)
            if not _is_inside_profiles_directory(old_json):
                _log.warning(
                    "refusing to delete profile json outside "
                    "profiles_directory(): %r", old_json)
            elif os.path.exists(old_json):
                os.remove(old_json)

            for loop_path in old.loop_paths:
                if not _is_inside_profiles_directory(loop_path):
                    _log.warning(
                        "refusing to delete loop file outside "
                        "profiles_directory(): %r", loop_path)
                    continue
                if os.path.exists(loop_path):
                    os.remove(loop_path)
        except OSError:
            pass


def prepare_all(progress: Callable[[str], None] | None = None
                ) -> tuple[SourceProfile, ...]:
    """Prepare everything in the sources folder that is not prepared already.

    Idempotent by design: a source whose profile already exists is skipped, so
    running this again after adding one song costs one song. "Already exists"
    is decided by `source_id_for`, which folds in the file's size and mtime —
    so a song replaced in place, not just a song newly added, is picked up
    again rather than skipped forever. Its old profile is then deleted, not
    left behind — see `_delete_superseded`.
    """
    def say(line: str) -> None:
        if progress is not None:
            progress(line)

    try:
        names = sorted(os.path.join(sources_directory(), n)
                       for n in os.listdir(sources_directory())
                       if n.lower().endswith(_MEDIA_SUFFIXES))
    except OSError:
        return ()

    # Snapshotted once: every candidate for "this is the stale profile of a
    # source being reprocessed right now" already existed before this sweep
    # started. A profile this same sweep writes for a *different* file always
    # has a different `source_path` (distinct paths from the directory
    # listing above), so it can never be mistaken for one of these.
    prior_profiles = load_profiles()
    existing_ids = {p.source_id for p in prior_profiles}
    for path in names:
        source_id = source_id_for(path)
        if source_id in existing_ids:
            say(f"already prepared: {os.path.basename(path)}")
            continue
        say(f"preparing: {os.path.basename(path)}")
        new_profile = prepare_source(path, source_id=source_id)
        if new_profile is None:
            say(f"  skipped (could not prepare): {os.path.basename(path)}")
            continue
        _delete_superseded(new_profile, prior_profiles)

    return load_profiles()
