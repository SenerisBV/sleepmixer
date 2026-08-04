import io
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client(stub_separation):
    # stub_separation patches sleepmix.session.separate, which RenderSession
    # resolves at construction — so the registry picks up the stub without
    # anything being injected into it.
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, sr=22050, secs=3.0):
    path = tmp_path / "a.wav"
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def test_preview_returns_playable_wav(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/preview", json={"song_id": song["id"], "progress": 0.5})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content), dtype="float32", always_2d=True)
    assert data.shape[0] > 0
    assert np.all(np.isfinite(data))


def test_preview_is_fast_once_the_session_is_warm(client, tmp_path):
    song = _import_song(client, tmp_path)
    client.post("/api/preview", json={"song_id": song["id"], "progress": 0.5})
    start = time.perf_counter()
    client.post("/api/preview", json={"song_id": song["id"], "progress": 0.6})
    assert time.perf_counter() - start < 3.0


def test_different_points_in_the_arc_sound_different(client, tmp_path):
    song = _import_song(client, tmp_path)
    early = client.post("/api/preview",
                        json={"song_id": song["id"], "progress": 0.0})
    late = client.post("/api/preview",
                       json={"song_id": song["id"], "progress": 1.0})
    assert (early.status_code, late.status_code) == (200, 200)
    assert early.content != late.content


def test_soloing_a_stem_changes_the_result(client, tmp_path):
    song = _import_song(client, tmp_path)
    everything = client.post("/api/preview",
                             json={"song_id": song["id"], "progress": 0.5})
    one = client.post("/api/preview",
                      json={"song_id": song["id"], "progress": 0.5,
                            "stems": ["vocals"]})
    # Both statuses, because `!=` on `.content` alone passes on a 422: a JSON
    # error body differs from WAV bytes as surely as one mix differs from
    # another, so this test used to hold against an endpoint that rejected
    # everything it was sent.
    assert (everything.status_code, one.status_code) == (200, 200)
    assert everything.content != one.content


def test_preview_honours_a_supplied_config(client, tmp_path):
    song = _import_song(client, tmp_path)
    default = client.post("/api/preview",
                          json={"song_id": song["id"], "progress": 0.5})
    slower = client.post("/api/preview",
                         json={"song_id": song["id"], "progress": 0.5,
                               "config": {"tempo": {"speed": 0.4}}})
    assert (default.status_code, slower.status_code) == (200, 200)
    assert default.content != slower.content


def test_preview_rejects_a_negative_seed(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/preview",
                    json={"song_id": song["id"], "progress": 0.5,
                          "config": {"seed": -5}})
    assert r.status_code == 400
    assert "seed" in r.json()["detail"].lower()


def test_preview_rejects_out_of_range_progress(client, tmp_path):
    song = _import_song(client, tmp_path)
    for progress in (-1.0, 2.0):
        r = client.post("/api/preview",
                        json={"song_id": song["id"], "progress": progress})
        assert r.status_code == 422


def test_preview_404s_for_an_unknown_song(client):
    r = client.post("/api/preview", json={"song_id": "nope", "progress": 0.5})
    assert r.status_code == 404


# -- the seam: a body shaped exactly as the mixer builds one ---------------
#
# `Config.encode` (ui/src/Config.elm) is the only thing that produces a real
# preview body, and until these tests existed nothing on this side had ever
# seen one: every route test here posted a hand-written dict with no `stems`
# key at all, and `ui/tests/ConfigTest.elm` round-trips the encoder through an
# *Elm* decoder — self-consistency, not agreement with `MixConfig.from_dict`.
# That gap is where the all-stems-off bug lived undetected through seven task
# reviews.


def _ui_body(song_id, stem_specs, progress=0.5, **overrides):
    """A request body with the shape `Config.encode` emits.

    Mirrors `ui/tests/Fixtures.elm`'s trimmed schema rather than the whole of
    `config_schema()`: what is being pinned is the *shape* — scalars at the top
    level, one object per section, and a `stems` list whose elements carry
    `name` beside their own fields and a nested `decay` object — not the
    current field inventory, which the schema endpoint is free to grow."""
    config = {
        "seed": 0,
        "separation_model": "htdemucs_ft",
        "loop": {"bars": 8, "crossfade_ms": 120.0, "search_start": 0.2},
        "tempo": {"speed": 0.7, "pitch_semitones": -2.0},
        "output": {"duration_min": 2.0, "sample_rate": 44100, "channels": 2},
        "soundbed": {"enabled": False, "noise_type": "pink"},
        "stems": [
            {"name": name,
             "enabled": enabled,
             "gain_db": gain_db,
             "reverb_send": 1.0,
             "decay": {"enabled": True, "curve": "linear",
                       "lowpass_start_hz": 18000.0, "amp_end_db": -9.0}}
            for name, enabled, gain_db in stem_specs
        ],
    }
    body = {"song_id": song_id, "progress": progress, "config": config}
    body.update(overrides)
    return body


def _rms(response):
    data, _ = sf.read(io.BytesIO(response.content), dtype="float32", always_2d=True)
    return float(np.sqrt(np.mean(data ** 2)))


ALL_ON = [(name, True, 0.0) for name in ("vocals", "drums", "bass", "other")]


def test_preview_reads_the_stems_list_the_mixer_actually_sends(client, tmp_path):
    """A per-stem edit in a `Config.encode`-shaped body reaches the audio.

    Gain rather than `enabled`, because a gain change cannot be produced by any
    other part of the request: if the `stems` list were being dropped on the
    floor, both of these would render identically."""
    song = _import_song(client, tmp_path)

    loud = client.post("/api/preview", json=_ui_body(song["id"], ALL_ON))
    quiet = client.post(
        "/api/preview",
        json=_ui_body(song["id"], [(name, True, -24.0) for name, _, _ in ALL_ON]))

    assert (loud.status_code, quiet.status_code) == (200, 200)
    # Both are mastered to the same peak, so the difference shows in the shape
    # of the window rather than its ceiling — but it must show.
    assert loud.content != quiet.content
    assert _rms(loud) > 0.0 and _rms(quiet) > 0.0


def test_disabling_stems_in_that_body_changes_what_plays(client, tmp_path):
    song = _import_song(client, tmp_path)

    everything = client.post("/api/preview", json=_ui_body(song["id"], ALL_ON))
    vocals_only = client.post(
        "/api/preview",
        json=_ui_body(song["id"],
                      [(name, name == "vocals", 0.0) for name, _, _ in ALL_ON]))

    assert (everything.status_code, vocals_only.status_code) == (200, 200)
    assert everything.content != vocals_only.content


def test_unchecking_every_stem_is_refused_rather_than_played(client, tmp_path):
    """Four clicks in the mixer, and it used to play the full default mix.

    `plan_stem_configs`' fallback could not tell "the config describes none of
    these stems" from "every one of them is switched off", so an all-off config
    came back as every available stem at defaults — at the ceiling, because
    `master_gain` recalibrates from that same fallback set."""
    song = _import_song(client, tmp_path)

    default = client.post("/api/preview", json=_ui_body(song["id"], ALL_ON))
    all_off = client.post(
        "/api/preview",
        json=_ui_body(song["id"], [(name, False, 0.0) for name, _, _ in ALL_ON]))

    assert default.status_code == 200
    assert all_off.status_code == 400
    assert "stem" in all_off.json()["detail"].lower()
    # On the audio, not only the status: whatever came back is not a mix.
    assert all_off.content != default.content
    assert not all_off.content.startswith(b"RIFF")


def test_soloing_a_stem_that_is_switched_off_is_refused(client, tmp_path):
    """Solo a stem, then uncheck its Enabled box — the reachable order.

    A 200 and a 48-byte one-frame WAV is the same silent failure wearing a
    different hat; the browser plays it and nothing says why."""
    song = _import_song(client, tmp_path)

    r = client.post(
        "/api/preview",
        json=_ui_body(song["id"],
                      [(name, name != "vocals", 0.0) for name, _, _ in ALL_ON],
                      stems=["vocals"]))

    assert r.status_code == 400
    assert "vocals" in r.json()["detail"]
