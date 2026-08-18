"""The expensive half, and the promise that it never runs at bedtime.

Demucs on a laptop spins the fans for minutes, next to the bed. Everything
here exists so that `sleepmix night` can be instant and silent about it, and
the last test in this file is the one that keeps that true.
"""
import json
import os
import time

import numpy as np
import pytest
import soundfile as sf

from sleepmix.night import prepare as prepare_mod
from sleepmix.night.prepare import (
    LOOPS_PER_SOURCE, prepare_all, prepare_source, source_id_for,
)
from sleepmix.night.sources import (
    PROFILE_SUFFIX, SourceProfile, load_profiles, profiles_directory,
    sources_directory, write_profile,
)

SR = 22050


def _write_song(path, seconds=30.0, sr=SR, freqs=(110.0, 164.81)):
    t = np.arange(int(seconds * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in freqs)
    y = (y / np.abs(y).max() * 0.5).astype(np.float32)
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return str(path)


@pytest.fixture(autouse=True)
def _stub_separation(monkeypatch):
    """Demucs is not installed here and must never be needed by a test."""
    from sleepmix.audio import load_audio

    def fake_separate(input_path, model="htdemucs_ft", cache_dir=None):
        src = load_audio(str(input_path))
        return {"other": src, "drums": src}

    monkeypatch.setattr(prepare_mod, "separate", fake_separate)


def test_a_source_id_is_stable_for_a_path():
    assert source_id_for("/a/b/Song.wav") == source_id_for("/a/b/Song.wav")


def test_a_source_id_differs_between_paths():
    assert source_id_for("/a/one.wav") != source_id_for("/a/two.wav")


def test_a_source_id_is_filesystem_safe():
    ident = source_id_for("/a/b/Weird Name (mix) #2.wav")
    assert ident and all(c.isalnum() or c in "-_" for c in ident)


def test_preparing_a_song_produces_loops_and_pitches(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav")
    profile = prepare_source(song, sr=SR)
    assert profile is not None
    assert len(profile.loop_paths) == LOOPS_PER_SOURCE
    assert len(profile.loop_frames) == LOOPS_PER_SOURCE
    assert profile.pitch_set
    assert profile.sr == SR


def test_the_loop_files_actually_exist_and_match_their_frame_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    for path, frames in zip(profile.loop_paths, profile.loop_frames):
        assert os.path.exists(path)
        info = sf.info(path)
        assert info.frames == frames


def test_the_loops_are_short_enough_to_carry_no_phrase(tmp_path, monkeypatch):
    """Pins the plan's stated 4-12 s band, not the loose 1-40 s bound that
    used to stand in for it. That bound was wide enough to pass while
    LOOP_BARS=4 produced ~13.2 s loops — four bars of source material, which
    is a phrase, defeating this test's own name. See LOOP_BARS in
    night/prepare.py for the formula the two constants share."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    for frames in profile.loop_frames:
        assert 4.0 <= frames / profile.sr <= 12.0


def test_a_prepared_loop_does_not_click_at_the_wrap(tmp_path, monkeypatch):
    """night/palette.py's `_source` tiles a loop end-to-end with
    ``np.tile`` and applies no crossfade of its own — it depends entirely on
    `prepare_source` handing back material whose tail already meets its head
    cleanly. `looping.make_seamless` exists for exactly this, and
    `prepare_source` calls it, but calling it *before* `slow_and_pitch`
    let the time-stretcher (a phase vocoder, or the resample fallback) undo
    the seam it had just been given: neither knows the first and last
    samples were built to meet, and both are free to touch either end.

    Regression test for that ordering: tile a real prepared loop the way
    `_source` does, and the sample-to-sample step across the wrap must not
    stand out from the steps found anywhere else in the tiled signal. Before
    the fix (seam, then stretch) the wrap step measured ~0.33 against a
    typical in-body step of ~0.0067 — roughly 50x, an audible click every
    loop repeat. After the fix (stretch, then seam) the wrap step is smaller
    than the loop's own largest in-body step.
    """
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    assert profile is not None

    from sleepmix.audio import load_audio
    loop = load_audio(profile.loop_paths[0])
    n = loop.n_frames
    tiled = np.tile(loop.data, (4, 1))

    steps = np.abs(np.diff(tiled, axis=0)).max(axis=1)
    wrap_indices = [k * n - 1 for k in range(1, 4)]
    mask = np.ones(len(steps), dtype=bool)
    mask[wrap_indices] = False

    wrap_step = steps[wrap_indices].max()
    body_step = steps[mask].max()
    assert wrap_step <= body_step, (
        f"wrap step {wrap_step} exceeds the loop's own largest in-body step "
        f"{body_step} — the tiled loop clicks at the seam")


def test_dropped_stems_do_not_reach_the_loops(tmp_path, monkeypatch):
    """Drums looping under you at 2 AM is what the render defaults already
    turn off by hand."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    seen = {}

    real = prepare_mod._kept_stems

    def spy(stems):
        kept = real(stems)
        seen["names"] = sorted(kept)
        return kept

    monkeypatch.setattr(prepare_mod, "_kept_stems", spy)
    prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    assert "drums" not in seen["names"]
    assert "other" in seen["names"]


def test_preparing_writes_a_profile_that_loads_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    loaded = load_profiles()
    assert len(loaded) == 1
    assert loaded[0].pitch_set


def test_prepare_all_walks_the_sources_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    _write_song(os.path.join(sources_directory(), "two.wav"), freqs=(146.83,))
    assert len(prepare_all()) == 2
    assert len(load_profiles()) == 2


def test_prepare_all_on_an_empty_folder_is_an_empty_tuple(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    assert prepare_all() == ()


def test_prepare_all_is_idempotent(tmp_path, monkeypatch):
    """Re-running costs nothing for an unchanged source."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    first = prepare_all()
    calls = {"n": 0}
    real = prepare_mod.prepare_source

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(prepare_mod, "prepare_source", counted)
    second = prepare_all()
    assert calls["n"] == 0
    assert [p.source_id for p in first] == [p.source_id for p in second]


def test_a_file_that_will_not_decode_costs_one_source_not_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "good.wav"))
    with open(os.path.join(sources_directory(), "bad.wav"), "w") as fh:
        fh.write("not audio")
    assert len(prepare_all()) == 1


def test_prepare_reports_progress_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    lines = []
    prepare_all(progress=lines.append)
    assert lines


def test_prepare_source_resamples_to_the_requested_rate(tmp_path, monkeypatch):
    """``sr`` is the promised output rate, not a value that only happens to
    match if the source file was already at it. A source recorded at some
    other rate must still come out (and be saved) at the one requested."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav", sr=8000)
    profile = prepare_source(song, sr=22050)
    assert profile is not None
    assert profile.sr == 22050
    for path in profile.loop_paths:
        assert sf.info(path).samplerate == 22050


def test_a_bad_source_id_from_write_profile_is_not_swallowed(tmp_path, monkeypatch):
    """``write_profile`` raises ``ValueError`` for an unsafe id on purpose —
    that is a programming error, not an ordinary per-file condition, and
    ``prepare_source``'s broad ``except Exception`` must not turn it back
    into a quiet ``None``."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav")

    def bad_write_profile(profile):
        raise ValueError("unsafe source_id: '..'")

    monkeypatch.setattr(prepare_mod, "write_profile", bad_write_profile)
    with pytest.raises(ValueError):
        prepare_source(song, sr=SR)


def test_editing_a_source_in_place_causes_reprocessing(tmp_path, monkeypatch):
    """Same path, new content: prepare_all must not read a stale profile as
    'already prepared' forever."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    path = os.path.join(sources_directory(), "one.wav")
    _write_song(path, freqs=(110.0,))
    prepare_all()

    _write_song(path, freqs=(146.83, 220.0))
    future = time.time() + 5
    os.utime(path, (future, future))

    calls = {"n": 0}
    real = prepare_mod.prepare_source

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(prepare_mod, "prepare_source", counted)
    prepare_all()
    assert calls["n"] == 1


def test_loops_per_source_beyond_search_windows_fails_loudly(tmp_path, monkeypatch):
    """A drift between LOOPS_PER_SOURCE and _SEARCH_WINDOWS is a programming
    error; it must not silently hand back fewer loops than promised."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(prepare_mod, "LOOPS_PER_SOURCE", 99)
    song = _write_song(tmp_path / "song.wav")
    with pytest.raises(RuntimeError):
        prepare_source(song, sr=SR)


def test_a_disk_error_writing_the_profile_costs_one_source_not_the_batch(
        tmp_path, monkeypatch):
    """``write_profile`` can fail from a genuine disk fault, not just a bad
    id. Unlike the bad-id ``ValueError``, that must not abort the rest of a
    ``prepare_all`` batch."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    _write_song(os.path.join(sources_directory(), "two.wav"), freqs=(146.83,))

    real = prepare_mod.write_profile
    calls = {"n": 0}

    def flaky(profile):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(profile)

    monkeypatch.setattr(prepare_mod, "write_profile", flaky)
    profiles = prepare_all()
    assert len(profiles) == 1


def test_editing_a_source_supersedes_the_old_profile(tmp_path, monkeypatch):
    """Not just reprocessed: the old profile (and its loop files) must not
    also survive an edit, or a night could schedule two versions of the same
    song as though they were unrelated sources."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    path = os.path.join(sources_directory(), "one.wav")
    _write_song(path, freqs=(110.0,))
    prepare_all()
    before = load_profiles()
    assert len(before) == 1
    old_loop_paths = before[0].loop_paths
    old_json = os.path.join(
        profiles_directory(), before[0].source_id + PROFILE_SUFFIX)

    _write_song(path, freqs=(146.83, 220.0))
    future = time.time() + 5
    os.utime(path, (future, future))
    prepare_all()

    after = load_profiles()
    assert len(after) == 1
    assert after[0].source_id != before[0].source_id
    assert not os.path.exists(old_json)
    for p in old_loop_paths:
        assert not os.path.exists(p)


def test_supersession_matches_the_full_source_path_not_a_prefix(
        tmp_path, monkeypatch):
    """This deletes files, so the match must be exact. A prefix match would
    let a similarly-named but genuinely different source delete a profile
    that is still current."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    old_loop = os.path.join(profiles_directory(), "old-0.wav")
    open(old_loop, "w").close()
    old = SourceProfile(source_id="old", source_path="/x/song.wav",
                        loop_paths=(old_loop,), loop_frames=(1,),
                        pitch_set=(55.0,), sr=44100)
    write_profile(old)
    old_json = os.path.join(profiles_directory(), "old" + PROFILE_SUFFIX)

    # "/x/song.wav" is a strict prefix of "/x/song.wav.bak" -- a different
    # file, not an edit of the same one.
    new = SourceProfile(source_id="new", source_path="/x/song.wav.bak",
                        loop_paths=(), loop_frames=(), pitch_set=(55.0,),
                        sr=44100)
    prepare_mod._delete_superseded(new, (old,))

    assert os.path.exists(old_loop)
    assert os.path.exists(old_json)


def test_supersession_refuses_to_escape_the_profiles_directory_via_source_id(
        tmp_path, monkeypatch):
    """A profile's ``source_id`` is never validated on the way in when it is
    *read* from disk: unlike ``write_profile``, which refuses ``"../victim"``
    outright, ``_read_profile`` deliberately tolerates a hand-edited or
    foreign-written ``.night.json``. Built here by writing the malicious JSON
    directly -- not through ``write_profile``, which correctly rejects this
    id -- and reached through the ordinary ``prepare_all()`` flow, so this is
    the exploit actually being reachable, not a hypothetical."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    path = os.path.join(sources_directory(), "one.wav")
    _write_song(path, freqs=(110.0,))
    prepare_all()
    original = load_profiles()[0]

    # Hand-edit the on-disk profile to carry an unsafe source_id.
    profile_json = os.path.join(
        profiles_directory(), original.source_id + PROFILE_SUFFIX)
    with open(profile_json) as fh:
        raw = json.load(fh)
    raw["source_id"] = "../victim"
    with open(profile_json, "w") as fh:
        json.dump(raw, fh)

    # Where source_id="../victim" would resolve the deletion target to: one
    # directory above profiles_directory().
    victim = os.path.join(profiles_directory(), "..", "victim" + PROFILE_SUFFIX)
    with open(victim, "w") as fh:
        fh.write("do not delete me")

    # Edit the source so it is reprocessed: prepare_all tries to supersede
    # the now-malicious old profile.
    _write_song(path, freqs=(146.83, 220.0))
    future = time.time() + 5
    os.utime(path, (future, future))
    prepare_all()

    assert os.path.exists(victim)
    with open(victim) as fh:
        assert fh.read() == "do not delete me"

    # The refusal to clean up the old profile must not cost the new one.
    new_profiles = [p for p in load_profiles()
                    if p.source_path == os.path.abspath(path)
                    and p.source_id not in (original.source_id, "../victim")]
    assert len(new_profiles) == 1


def test_supersession_refuses_to_delete_a_loop_path_outside_profiles_directory(
        tmp_path, monkeypatch):
    """Same shape as the ``source_id`` exploit, for the other field
    ``_delete_superseded`` reads off disk: ``loop_paths``. Built by writing
    the malicious JSON directly, since ``write_profile`` only validates
    ``source_id`` and never inspects where ``loop_paths`` point."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    path = os.path.join(sources_directory(), "one.wav")
    _write_song(path, freqs=(110.0,))
    prepare_all()
    original = load_profiles()[0]

    victim = os.path.join(str(tmp_path), "elsewhere.wav")
    with open(victim, "w") as fh:
        fh.write("do not delete me")

    profile_json = os.path.join(
        profiles_directory(), original.source_id + PROFILE_SUFFIX)
    with open(profile_json) as fh:
        raw = json.load(fh)
    raw["loop_paths"] = [victim]
    raw["loop_frames"] = [1]
    with open(profile_json, "w") as fh:
        json.dump(raw, fh)

    _write_song(path, freqs=(146.83, 220.0))
    future = time.time() + 5
    os.utime(path, (future, future))
    prepare_all()

    assert os.path.exists(victim)
    with open(victim) as fh:
        assert fh.read() == "do not delete me"

    new_profiles = [p for p in load_profiles()
                    if p.source_path == os.path.abspath(path)
                    and p.source_id != original.source_id]
    assert len(new_profiles) == 1


def test_prepare_all_computes_source_id_once_per_file(tmp_path, monkeypatch):
    """The skip check and ``prepare_source`` used to hash and ``stat`` the
    same file separately; ``prepare_all`` now computes the id once and
    passes it through."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    calls = {"n": 0}
    real = prepare_mod.source_id_for

    def counted(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(prepare_mod, "source_id_for", counted)
    prepare_all()
    assert calls["n"] == 1


# Every file in sleepmix/night/ is on the live playback path except these
# two, and the guard below sweeps the directory rather than naming files —
# a hand-picked list silently stops covering a file the moment someone adds
# a module here and forgets to add it there too. Whoever adds the next
# night/*.py file is guarded by default, not by remembering.
_AUDIO_SIDE_MODULES = {
    "prepare.py",  # this is the module being forbidden; it cannot forbid itself
    "pitch.py",    # audio-touching by design, but only ever imported by prepare.py
}


def test_the_night_module_never_imports_prepare():
    """The promise that bedtime is silent: nothing on the playback path may
    reach the module that runs Demucs.

    Swept over every file in the package rather than a hand-picked list —
    see `_AUDIO_SIDE_MODULES`. A prior version of this test named seven
    files and silently missed two (`speech.py`, `sky.py`), both reachable
    from `sleepmix night`: `player.py` imports `speech.py`, `context.py`
    imports `sky.py`. `forbidden_imports` only checks the one file it is
    given, not what that file transitively pulls in, so a hand-picked list
    has to be exhaustive by construction to mean what it claims.
    """
    import pathlib
    from .import_guard import forbidden_imports
    root = pathlib.Path(__file__).resolve().parent.parent
    forbidden = {"sleepmix.night.prepare", "sleepmix.separation",
                 "sleepmix.separation_process", "sleepmix.analysis",
                 "sleepmix.timestretch"}
    night_dir = root / "sleepmix" / "night"
    swept = sorted(p for p in night_dir.glob("*.py")
                   if p.name not in _AUDIO_SIDE_MODULES)
    # A glob that silently matched nothing (a moved directory, a typo`'d
    # pattern) would make every assertion below vacuously true.
    assert len(swept) > 5, f"expected several night modules, found {swept}"
    for path in swept:
        offenders = forbidden_imports(path, root, forbidden)
        assert offenders == set(), f"{path.name} reaches preparation: {offenders}"
