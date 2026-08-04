import threading

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
    assert session.master_gain[True] == gain, "a decay change must not clear the gain"


def test_master_gain_is_cleared_by_a_reverb_change(tmp_path, registry):
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    master_gain(session)

    changed = MixConfig()
    changed.reverb.wet = 0.1
    registry.get("a", path, changed)
    assert session.master_gain == {}


def test_master_gain_is_cleared_by_a_tempo_change(tmp_path, registry):
    """A different stretch means a different loop, so a different peak."""
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    master_gain(session)

    changed = MixConfig()
    changed.tempo.speed = 0.4
    registry.get("a", path, changed)
    assert session.master_gain == {}


def test_an_unchanged_config_does_not_clear_the_gain(tmp_path, registry):
    """This is the request-after-request case: the registry calls update_config
    every time, and an identical config must be a no-op."""
    from sleepmix.preview import master_gain

    path = _song(tmp_path / "a.wav")
    session = registry.get("a", path, MixConfig())
    gain = master_gain(session)
    registry.get("a", path, MixConfig())
    assert session.master_gain[True] == gain


def test_session_for_serializes_renders_against_a_config_swap(tmp_path, registry):
    """Concurrent previews of one song must not tear on a config change.

    `/api/preview` is a sync `def` route, so FastAPI runs it in AnyIO's
    threadpool — a scrubber drag really does put several `render_window` calls
    on one `RenderSession` at once, and the Elm frontend is built to do exactly
    that. `SessionRegistry._lock` protects only the dictionary and releases
    before the render begins, so with `get` alone the interleaving is: thread A
    is inside `prepared_loop`, has found the stem present, and is about to
    index `self._prepared`; thread B's `get` calls `update_config` with a
    different tempo, which clears that dict; A raises `KeyError` and the
    preview 500s. The silent variant is worse — A reads `session.config` under
    one config and renders against another's stretched loop, producing a window
    from two configs with no error at all.

    Every thread here asks for a *different* tempo, so every pass through
    `session_for` really does invalidate the prepared-loop cache the others are
    reading. Nothing may escape, and every window must be a real buffer.

    Modelled on `tests/test_store.py`'s concurrent-writer test, and load-bearing
    in the same way: remove the per-song lock from `session_for` and this fails
    (`KeyError` out of `prepared_loop`) rather than merely getting slower.
    """
    import sys

    from sleepmix.preview import render_window

    path = _song(tmp_path / "a.wav")
    speeds = [0.5, 0.55, 0.6, 0.65, 0.7]

    def one(speed: float):
        cfg = MixConfig()
        cfg.output.duration_min = 1.0
        cfg.tempo.speed = speed
        return cfg

    # A stretched loop's length is a function of tempo, so the frame count is a
    # fingerprint of *which config a window was actually built from*. Measured
    # serially first, where no interleaving is possible.
    expected = {}
    for speed in speeds:
        with registry.session_for("a", path, one(speed)) as session:
            expected[speed] = render_window(
                session, 0.5, stems=session.stem_names()[:1], reverb=False).n_frames
    assert len(set(expected.values())) == len(speeds), \
        "the speeds chosen must give distinguishable window lengths"

    n_threads, per_thread = 6, 8
    errors: list[BaseException] = []
    frames: list[int] = []
    guard = threading.Lock()
    start = threading.Barrier(n_threads)

    def worker(t: int) -> None:
        try:
            start.wait(timeout=30)
            for i in range(per_thread):
                speed = speeds[(t + i) % len(speeds)]
                with registry.session_for("a", path, one(speed)) as session:
                    # Both halves inside the lock: reading the config and
                    # rendering against it are one operation, not two.
                    assert session.config.tempo.speed == speed
                    window = render_window(session, ((t + i) % 7) / 6.0,
                                           stems=session.stem_names()[:1],
                                           reverb=False)
                assert window.n_frames == expected[speed], (
                    f"speed {speed} produced {window.n_frames} frames, expected "
                    f"{expected[speed]} — this window was built from another "
                    f"thread's config")
                with guard:
                    frames.append(window.n_frames)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            with guard:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    # Force the interpreter to preempt often: the unsynchronized window between
    # `_prepared`'s store and its read is a couple of bytecodes wide, and at the
    # 5 ms default it is hit rarely enough to make this test useless as a guard.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
            assert not t.is_alive(), "a worker deadlocked — is the use lock an RLock?"
    finally:
        sys.setswitchinterval(previous_interval)

    assert errors == [], f"{len(errors)} thread(s) raised: {errors[:3]}"
    assert len(frames) == n_threads * per_thread


def test_session_for_yields_the_same_object_get_would(tmp_path, registry):
    path = _song(tmp_path / "a.wav")
    direct = registry.get("a", path, MixConfig())
    with registry.session_for("a", path, MixConfig()) as held:
        assert held is direct


def test_the_use_lock_is_reentrant(tmp_path, registry):
    """Nesting must not deadlock — `get` reaches for the registry lock inside it."""
    path = _song(tmp_path / "a.wav")
    with registry.session_for("a", path, MixConfig()) as outer:
        with registry.session_for("a", path, MixConfig()) as inner:
            assert inner is outer


def test_clear_drops_the_use_locks(tmp_path, registry):
    """The lock dict is the one structure here that could grow without bound."""
    path = _song(tmp_path / "a.wav")
    with registry.session_for("a", path, MixConfig()):
        pass
    assert registry._use_locks
    registry.clear()
    assert registry._use_locks == {}


def test_evicting_a_session_does_not_strand_a_held_lock(tmp_path, registry):
    """A lock outlives the session it guarded, deliberately.

    Dropping it on eviction would hand the next caller a fresh lock while a
    thread still holds the old one — no mutual exclusion, and no error to say
    so. Keying by song id and clearing only in `clear()` avoids reference
    counting for a dict of a few dozen bytes per song."""
    path = _song(tmp_path / "a.wav")
    with registry.session_for("a", path, MixConfig()):
        registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
        registry.get("c", _song(tmp_path / "c.wav"), MixConfig())   # evicts a
        assert registry.song_ids() == ["b", "c"]
    lock = registry._use_locks["a"]
    with registry.session_for("a", path, MixConfig()):
        assert registry._use_locks["a"] is lock
