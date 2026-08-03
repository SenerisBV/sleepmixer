import pytest

from sleepmix import paths
from sleepmix.server.store import Store


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


def test_a_second_store_sees_the_first_store_s_data(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    other = Store()
    try:
        assert other.get_song(song["id"])["title"] == "A"
    finally:
        other.close()
