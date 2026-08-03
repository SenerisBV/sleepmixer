import threading

import pytest

from sleepmix import paths
from sleepmix.server.store import SEPARATION_STATUSES, Store


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()


def test_database_lives_under_the_data_dir(store):
    assert str(paths.data_dir()) in store.db_path


def test_add_and_get_song_round_trips(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=12.5, sample_rate=44100)
    assert song["id"]
    assert song["separation_status"] == "pending"
    fetched = store.get_song(song["id"])
    assert fetched["title"] == "A"
    assert fetched["duration_s"] == 12.5
    assert fetched["sample_rate"] == 44100


def test_get_song_returns_none_when_absent(store):
    assert store.get_song("nope") is None


def test_list_songs_is_newest_first(store):
    a = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    b = store.add_song(path="/tmp/b.wav", title="B", duration_s=1.0, sample_rate=44100)
    ids = [s["id"] for s in store.list_songs()]
    assert ids.index(b["id"]) < ids.index(a["id"])


def test_update_song_changes_only_named_fields(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    updated = store.update_song(song["id"], separation_status="failed",
                                separation_reason="Demucs not installed")
    assert updated["separation_status"] == "failed"
    assert updated["separation_reason"] == "Demucs not installed"
    assert updated["title"] == "A"


def test_update_song_rejects_unknown_columns(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    with pytest.raises(ValueError):
        store.update_song(song["id"], nonsense="x")


def test_update_song_serializes_stems(store):
    """A list must survive the round trip, not come back as a JSON string."""
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    stems = ["vocals", "drums", "bass", "other"]
    updated = store.update_song(song["id"], stems=stems)
    assert updated["stems"] == stems
    assert store.get_song(song["id"])["stems"] == stems


def test_update_render_serializes_config(store):
    """Nested config must round trip through the update path, not just insert."""
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    r = store.add_render(song_id=song["id"], config={"seed": 1},
                         path="/tmp/o.wav", status="running")
    updated = store.update_render(r["id"], config={"seed": 9, "tempo": {"speed": 0.5}})
    assert updated["config"] == {"seed": 9, "tempo": {"speed": 0.5}}
    assert store.get_render(r["id"])["config"]["tempo"]["speed"] == 0.5


def test_update_with_no_fields_is_a_no_op(store):
    """Calling update with nothing to set must return the row unchanged."""
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    assert store.update_song(song["id"]) == store.get_song(song["id"])


def test_update_song_returns_none_when_absent(store):
    assert store.update_song("nope", title="x") is None


def test_presets_round_trip_config_as_a_dict(store):
    p = store.add_preset("Slow", {"tempo": {"speed": 0.5}})
    assert p["config"] == {"tempo": {"speed": 0.5}}
    assert store.list_presets()[0]["config"]["tempo"]["speed"] == 0.5
    assert store.delete_preset(p["id"]) is True
    assert store.list_presets() == []
    assert store.delete_preset(p["id"]) is False


def test_preset_names_are_unique(store):
    store.add_preset("Slow", {})
    with pytest.raises(ValueError):
        store.add_preset("Slow", {})


def test_renders_round_trip(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    r = store.add_render(song_id=song["id"], config={"seed": 3},
                         path="/tmp/out.wav", status="running")
    assert r["config"] == {"seed": 3}
    assert store.get_render(r["id"])["status"] == "running"
    assert store.update_render(r["id"], status="done")["status"] == "done"
    assert [x["id"] for x in store.list_renders()] == [r["id"]]


def test_default_separation_status_is_in_the_declared_vocabulary(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    assert song["separation_status"] in SEPARATION_STATUSES


def test_concurrent_writers_and_readers_do_not_lose_rows(store):
    """FastAPI runs `def` routes in a threadpool, so this is the real shape.

    Without the lock in `Store`, interleaved execute/commit pairs on one
    `sqlite3.Connection` (opened `check_same_thread=False`) are only safe by
    accident of the platform's `sqlite3.threadsafety`. This asserts the
    contract directly: every insert lands, every read is well-formed, and
    nothing raises on any thread."""
    n_threads, per_thread = 8, 25
    errors: list[BaseException] = []
    start = threading.Barrier(n_threads)

    def worker(t: int) -> None:
        try:
            start.wait(timeout=10)
            for i in range(per_thread):
                store.add_song(path=f"/tmp/{t}-{i}.wav", title=f"{t}-{i}",
                               duration_s=1.0, sample_rate=44100)
                # Interleave reads and a read-modify-write with the inserts.
                for song in store.list_songs():
                    assert song["title"]
                store.update_song(
                    store.list_songs()[0]["id"], separation_status="running")
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "a worker deadlocked — is the lock an RLock?"

    assert errors == []
    titles = {s["title"] for s in store.list_songs()}
    assert len(titles) == n_threads * per_thread


def test_a_second_store_sees_the_first_store_s_data(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    other = Store()
    try:
        assert other.get_song(song["id"])["title"] == "A"
    finally:
        other.close()
