import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig
from sleepmix.session import RenderSession


def _song(path, sr=22050, secs=6.0):
    t = np.arange(int(sr * secs)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0
    save_audio(AudioBuffer(np.stack([y, y], axis=1).astype(np.float32), sr), str(path))


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


def test_changing_the_output_rate_changes_the_master_key():
    """run_pipeline resamples before normalizing, so a gain measured at one
    output rate does not describe a render at another. Without this the
    memoized factor survives the change and the session keeps serving it."""
    base = MixConfig()
    other = MixConfig()
    other.output.sample_rate = 22050
    assert RenderSession._master_key(base) != RenderSession._master_key(other)


def test_loop_point_respects_explicit_config(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.loop.start_s = 1.0
    cfg.loop.end_s = 3.0
    s = RenderSession(str(song), cfg, separate_fn=stub_separation)
    lp = s.loop_point()
    assert lp.start == int(1.0 * 22050)
