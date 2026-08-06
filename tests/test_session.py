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
