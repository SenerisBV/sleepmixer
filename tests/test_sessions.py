import numpy as np
import pytest

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig
from sleepmix.server.sessions import SessionRegistry


def _song(path, sr=22050, secs=3.0):
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return str(path)


@pytest.fixture
def registry(stub_separation):
    return SessionRegistry(max_sessions=2, separate_fn=stub_separation)


def test_the_same_song_returns_the_same_session(tmp_path, registry):
    path = _song(tmp_path / "a.wav")
    first = registry.get("song-a", path, MixConfig())
    second = registry.get("song-a", path, MixConfig())
    assert first is second


def test_a_config_change_updates_rather_than_rebuilds(tmp_path, registry):
    """Rebuilding would re-run separation — the whole point is to avoid that."""
    path = _song(tmp_path / "a.wav")
    session = registry.get("song-a", path, MixConfig())
    stems = session.stems()

    faster = MixConfig()
    faster.tempo.speed = 0.5
    again = registry.get("song-a", path, faster)

    assert again is session
    assert again.stems() is stems
    assert again.config.tempo.speed == 0.5


def test_least_recently_used_is_evicted(tmp_path, registry):
    a = registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
    registry.get("c", _song(tmp_path / "c.wav"), MixConfig())

    assert registry.song_ids() == ["b", "c"]
    assert registry.get("a", _song(tmp_path / "a.wav"), MixConfig()) is not a


def test_touching_a_session_makes_it_most_recent(tmp_path, registry):
    registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
    registry.get("a", _song(tmp_path / "a.wav"), MixConfig())   # touch a
    registry.get("c", _song(tmp_path / "c.wav"), MixConfig())   # evicts b

    assert registry.song_ids() == ["a", "c"]


def test_discard_and_clear(tmp_path, registry):
    registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    registry.discard("a")
    assert registry.song_ids() == []
    registry.discard("a")  # discarding twice must not raise
    registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
    registry.clear()
    assert registry.song_ids() == []


def test_a_changed_source_path_rebuilds(tmp_path, registry):
    """Re-importing a moved file under the same id must not serve stale audio."""
    first = registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    second = registry.get("a", _song(tmp_path / "moved.wav"), MixConfig())
    assert second is not first


def test_master_gain_survives_a_decay_only_change(tmp_path, registry):
    """A decay slider drag must not invalidate the gain.

    master_gain is measured at progress 0, where apply_decay is a passthrough,
    so decay cannot move it — and recomputing would double the cost of every
    preview during a drag."""
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    gain = master_gain(session)

    changed = MixConfig()
    changed.stems[0].decay.amp_end_db = -30.0
    registry.get("a", path, changed)
    assert session.master_gain == gain, "a decay change must not clear the gain"


def test_master_gain_is_cleared_by_a_reverb_change(tmp_path, registry):
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    master_gain(session)

    changed = MixConfig()
    changed.reverb.wet = 0.1
    registry.get("a", path, changed)
    assert session.master_gain is None


def test_master_gain_is_cleared_by_a_tempo_change(tmp_path, registry):
    """A different stretch means a different loop, so a different peak."""
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    master_gain(session)

    changed = MixConfig()
    changed.tempo.speed = 0.4
    registry.get("a", path, changed)
    assert session.master_gain is None


def test_an_unchanged_config_does_not_clear_the_gain(tmp_path, registry):
    """This is the request-after-request case: the registry calls update_config
    every time, and an identical config must be a no-op."""
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    gain = master_gain(session)
    registry.get("a", path, MixConfig())
    assert session.master_gain == gain
