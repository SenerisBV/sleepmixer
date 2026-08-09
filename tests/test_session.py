import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig
from sleepmix.preview import master_gain
from sleepmix.session import RenderSession


def _song(path, sr=22050, secs=6.0):
    t = np.arange(int(sr * secs)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0
    save_audio(AudioBuffer(np.stack([y, y], axis=1).astype(np.float32), sr), str(path))


def _level_cfg():
    """The narrowest configuration in which "the preview is at the render's
    level" is a well-posed question — see the fuller rationale in
    ``test_preview.py``, whose copy of this helper this mirrors."""
    cfg = MixConfig()
    cfg.output.duration_min = 0.5
    cfg.output.sample_rate = 22050
    cfg.output.fade_in_s = 0.0
    cfg.output.fade_out_s = 0.0
    return cfg


def _with_bed(cfg, enabled=True):
    """A copy of cfg with the bed switched on and given something audible."""
    import copy
    out = copy.deepcopy(cfg)
    out.soundbed.enabled = enabled
    out.soundbed.noise_gain_db = -12.0
    return out


def test_stems_are_computed_once(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)

    calls = []
    def counting(*a, **k):
        calls.append(1)
        return stub_separation(*a, **k)

    s = RenderSession(str(song), MixConfig(), separate_fn=counting)
    s.stems()
    s.stems()
    assert len(calls) == 1


def test_changing_tempo_invalidates_prepared_loop_but_not_stems(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    s = RenderSession(str(song), cfg, separate_fn=stub_separation)

    stems_before = s.stems()
    name = s.stem_names()[0]
    loop_before = s.prepared_loop(name)

    faster = MixConfig()
    faster.tempo.speed = 0.5
    s.update_config(faster)

    assert s.stems() is stems_before, "separation must survive a tempo change"
    assert s.prepared_loop(name).n_frames != loop_before.n_frames


def test_changing_decay_invalidates_nothing_cached(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    s = RenderSession(str(song), MixConfig(), separate_fn=stub_separation)
    name = s.stem_names()[0]
    loop_before = s.prepared_loop(name)

    changed = MixConfig()
    changed.stems[0].decay.amp_end_db = -30.0
    s.update_config(changed)

    assert s.prepared_loop(name) is loop_before, "decay must not touch the loop"


def test_loop_point_respects_explicit_config(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.loop.start_s = 1.0
    cfg.loop.end_s = 3.0
    s = RenderSession(str(song), cfg, separate_fn=stub_separation)
    lp = s.loop_point()
    assert lp.start == int(1.0 * 22050)


def test_the_master_gain_notices_the_bed(tmp_path, stub_separation):
    """The test Plan 3f's sample_rate change should have had and did not: it
    asserted two tuples differ, which is true by construction. What matters is
    whether the value at the far end of the invalidation chain moves."""
    song = tmp_path / "s.wav"
    _song(song)
    quiet = RenderSession(str(song), _with_bed(_level_cfg(), enabled=False),
                          separate_fn=stub_separation)
    loud = RenderSession(str(song), _with_bed(_level_cfg(), enabled=True),
                         separate_fn=stub_separation)
    assert master_gain(quiet, reverb=True) != master_gain(loud, reverb=True)


def test_toggling_the_bed_clears_the_memoised_gain(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    session = RenderSession(str(song), _with_bed(_level_cfg(), enabled=False),
                            separate_fn=stub_separation)
    before = master_gain(session, reverb=True)
    assert session.master_gain  # memoised
    session.update_config(_with_bed(_level_cfg(), enabled=True))
    assert not session.master_gain, "a bed change must not serve a stale factor"
    assert master_gain(session, reverb=True) != before


def test_changing_the_gap_clears_the_memoised_gain(tmp_path, stub_separation):
    """The arrangement decides which window gets measured, so it belongs in
    the key — the same test ``_master_key``'s docstring applies to the sound
    bed: not whether a render reads the field, but whether the calibration
    window's own output depends on it."""
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    session.master_gain[True] = 0.5

    changed = MixConfig()
    changed.arrangement.gap_start_s = -2.0
    session.update_config(changed)
    assert session.master_gain == {}


def test_changing_the_crossfade_clears_the_memoised_gain_when_repeats_overlap(
        tmp_path, stub_separation):
    """``cycle_crossfade_ms`` decides ``xfade``, which now decides which
    overlaps ``densest_frame``/``concurrent_placements`` treat as an ordinary
    seam versus genuine stacking — so it can move which placement dominates
    the densest frame and how many are concurrent there. That was not true
    before ``densest_frame`` existed, when ``master_gain`` always measured
    placement 0 regardless of the crossfade, which is why this field used to
    be safely excluded from the key. On a negative-gap config, where the
    crossfade width genuinely changes the density ratio, a stale memo must
    not survive a crossfade change."""
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    cfg.arrangement.gap_start_s = -3.0
    cfg.arrangement.gap_end_s = -3.0
    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    before = master_gain(session, reverb=False)
    assert session.master_gain  # memoised

    changed = MixConfig()
    changed.output.duration_min = 2.0
    changed.arrangement.gap_start_s = -3.0
    changed.arrangement.gap_end_s = -3.0
    changed.output.cycle_crossfade_ms = 3000.0
    session.update_config(changed)
    assert session.master_gain == {}, \
        "a crossfade change must not serve a stale factor once it can move the gain"
    assert master_gain(session, reverb=False) != before


def _overlapping_cfg(gap=-4.0):
    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    cfg.arrangement.gap_start_s = gap
    cfg.arrangement.gap_end_s = gap
    return cfg


def test_changing_a_decay_setting_clears_the_memoised_gain(tmp_path, stub_separation):
    """The invariant this key was built on, and the day it stopped holding.

    ``_master_key``'s docstring used to open by saying the gain is measured
    from iteration 0, where ``apply_decay`` returns the loop untouched, so no
    decay setting could move it — which is why every stem's ``decay`` was left
    out. ``master_gain`` stopped measuring iteration 0 when it started asking
    ``densest_frame`` which window to measure, and it now weights that
    measurement by ``concurrent_amplitude``, which reads the amplitude arc
    directly.

    Measured on this configuration before the fix: computing the gain,
    changing only ``amp_start_db`` through ``update_config``, and comparing
    against a session built fresh on the new config gave a stale factor
    6.00 dB off. ``server/sessions.py`` calls ``update_config`` on every
    ``POST /api/preview``, so that error persisted for as long as the session
    lived, with nothing to hear but a preview at the wrong loudness.

    A negative gap, because that is what makes ``densest_frame`` leave frame 0
    and gives ``concurrent_amplitude`` more than one placement to weigh —
    asserted below rather than assumed."""
    song = tmp_path / "s.wav"
    _song(song)
    session = RenderSession(str(song), _overlapping_cfg(),
                            separate_fn=stub_separation)
    before = master_gain(session, reverb=False)
    assert session.master_gain  # memoised

    changed = _overlapping_cfg()
    for sc in changed.stems:
        sc.decay.amp_start_db = -40.0
    session.update_config(changed)
    assert session.master_gain == {}, \
        "a decay change must not serve a stale factor once it can move the gain"

    after = master_gain(session, reverb=False)
    fresh = RenderSession(str(song), changed, separate_fn=stub_separation)
    assert after == master_gain(fresh, reverb=False), \
        "the recomputed gain must match a session built fresh on the new config"
    assert after != before, \
        "test setup produced a decay change that cannot move the gain"


def test_changing_the_seed_clears_the_memoised_gain(tmp_path, stub_separation):
    """``render_window`` seeds the calibration window's sound bed from
    ``cfg.seed``, so a re-seeded bed measures a different peak. Small — +0.02
    dB on the default bed, +0.343 dB measured on a louder one — but the same
    kind of staleness as the decay settings above, and pre-existing rather
    than introduced by the arrangement work.

    The bed is switched on and given something audible, because with
    ``soundbed.enabled = False`` nothing on the preview path reads the seed at
    all and this would assert nothing."""
    song = tmp_path / "s.wav"
    _song(song)
    session = RenderSession(str(song), _with_bed(_level_cfg()),
                            separate_fn=stub_separation)
    before = master_gain(session, reverb=False)
    assert session.master_gain  # memoised

    changed = _with_bed(_level_cfg())
    changed.seed = 12345
    session.update_config(changed)
    assert session.master_gain == {}, "a seed change must not serve a stale factor"
    assert master_gain(session, reverb=False) != before
