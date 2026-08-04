import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _click_track(path, bpm=120.0, secs=40.0, sr=22050):
    """A signal with real beats, so beat tracking has something to detect.

    A constant tone gives librosa nothing to lock onto, so it falls back to a
    fixed-tempo guess and then to the whole buffer — and a test written against
    that path passes no matter what the detector does."""
    n = int(sr * secs)
    y = np.zeros(n, dtype=np.float32)
    period = int(sr * 60.0 / bpm)
    click = np.exp(-np.arange(int(sr * 0.02)) / (sr * 0.004)).astype(np.float32)
    for start in range(0, n - len(click), period):
        y[start:start + len(click)] += click
    # A quiet tone underneath, so the file is not pure impulses.
    t = np.arange(n) / sr
    y += (0.05 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return str(path)


def _import(client, tmp_path, **kwargs):
    path = _click_track(tmp_path / "a.wav", **kwargs)
    return client.post("/api/songs", json={"path": path}).json()


def test_loop_is_a_detected_region_not_the_whole_song(client, tmp_path):
    """The region must come from detection, not from the whole-buffer fallback.

    Eight bars of four beats at 120 BPM is 16 seconds; the fallback would
    return the entire 40-second track, so a strict subset is the thing that
    distinguishes a real detection from a silent failure."""
    song = _import(client, tmp_path)
    body = client.get(f"/api/songs/{song['id']}/loop").json()

    length = body["end_s"] - body["start_s"]
    assert 0 <= body["start_s"] < body["end_s"] <= song["duration_s"] + 0.01
    assert length < song["duration_s"] - 1.0, (
        f"got the whole track ({length:.1f}s) — detection fell back")
    assert 8.0 < length < 24.0, f"expected roughly 16s of loop, got {length:.1f}s"


def test_loop_reports_a_plausible_tempo(client, tmp_path):
    """Allowing the octave error on purpose — beat trackers routinely report
    half or double the true tempo, and pinning 120 exactly would be flaky
    without testing anything more."""
    song = _import(client, tmp_path)
    tempo = client.get(f"/api/songs/{song['id']}/loop").json()["tempo"]
    assert any(abs(tempo - t) < 10.0 for t in (60.0, 120.0, 240.0)), tempo


def test_loop_404s_for_an_unknown_song(client):
    r = client.get("/api/songs/nope/loop")
    assert r.status_code == 404
    assert r.json()["detail"] == "No such song", "a missing route also 404s"


def test_loop_404s_when_the_file_has_moved(client, tmp_path):
    import os

    song = _import(client, tmp_path)
    os.remove(song["path"])
    r = client.get(f"/api/songs/{song['id']}/loop")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()


def test_loop_honours_explicit_config_overrides(client, tmp_path):
    """The UI will send back a dragged region; the same endpoint must echo it."""
    song = _import(client, tmp_path)
    body = client.get(
        f"/api/songs/{song['id']}/loop?start_s=2.0&end_s=5.0").json()
    assert abs(body["start_s"] - 2.0) < 0.01
    assert abs(body["end_s"] - 5.0) < 0.01
