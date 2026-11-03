"""Segment cutting and station export: synthetic takes only, in tmp dirs."""
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sleepmix.esoterica.script import Passage, Script
from sleepmix.esoterica.segments import cut_times, export_station, find_pauses

SR = 44100


def take(bursts, total, sr=SR):
    """220 Hz tone bursts at the given (start, end) seconds, silence elsewhere."""
    x = np.zeros(int(total * sr), dtype=np.float32)
    for a, b in bursts:
        t = np.arange(int(a * sr), int(b * sr)) / sr
        x[int(a * sr):int(b * sr)] = 0.3 * np.sin(2 * np.pi * 220 * t)
    return x


def in_burst(t, bursts):
    return any(a < t < b for a, b in bursts)


def test_find_pauses_finds_inner_silences():
    x = take([(0, 2), (2.6, 5), (5.3, 8)], 8.0)
    got = find_pauses(x, SR)
    assert len(got) == 2
    for (s, e), (es, ee) in zip(got, [(2.0, 2.6), (5.0, 5.3)]):
        assert s == pytest.approx(es, abs=0.03) and e == pytest.approx(ee, abs=0.03)


def test_find_pauses_ignores_edges_and_short_gaps():
    x = take([(1, 3), (3.1, 6)], 8.0)  # leading 1 s, trailing 2 s, 0.1 s gap
    assert find_pauses(x, SR) == []


def test_cut_prefers_long_pause_near_expected():
    x = take([(0, 3), (3.3, 4), (5, 8)], 8.0)
    # expected 0.4125 * 8 = 3.3 s; window 3.3 +- 1.6; pause scores ~0.297 vs ~0.976
    [cut] = cut_times(x, SR, [0.4125])
    assert cut == pytest.approx(4.5, abs=0.03)


def test_cut_moves_to_nearest_pause():
    bursts = [(0, 1), (1.5, 8)]
    x = take(bursts, 8.0)
    [cut] = cut_times(x, SR, [0.75])  # expected 6.0 s, window 4.4..7.6: no pause
    assert cut == pytest.approx(1.25, abs=0.03)
    assert not in_burst(cut, bursts)


def test_cut_times_are_increasing_pause_midpoints():
    bursts = [(0, 2), (3, 5), (6, 8), (9, 11), (12, 14)]
    x = take(bursts, 14.0)
    cuts = cut_times(x, SR, [0.2, 0.5, 0.8])
    assert cuts == sorted(set(cuts))
    assert all(not in_burst(c, bursts) for c in cuts)


def _script(tmp_path):
    p1 = "One one one.\n\nTwo two two.\n\nThree three three."
    p2 = "Four four four."
    return Script(id="demo", show="stations", title="Demo", language="en",
                  speaker="x", source_character="clean", voice_profile=None,
                  voice=None, path=tmp_path / "demo.md",
                  passages=(Passage(0, p1, "medium", (0, 2)),
                            Passage(1, p2, "medium", (0,))))


def test_export_station_writes_bundle(tmp_path):
    lib, out = tmp_path / "lib", tmp_path / "out"
    d = lib / "demo"
    d.mkdir(parents=True)
    # passage 1: 12 s, a long pause at 6-7 s (fraction of paragraph 3 is 24/42 -> ~6.9 s)
    sf.write(d / "p01.raw.wav", take([(0, 6), (7, 12)], 12.0), SR, subtype="FLOAT")
    sf.write(d / "p02.raw.wav", take([(0, 4)], 4.0), SR, subtype="FLOAT")
    before = {f.name: f.read_bytes() for f in d.glob("*.raw.wav")}

    st = export_station(_script(tmp_path), lib, out)

    files = sorted(f.name for f in (out / "demo").glob("*.wav"))
    assert files == ["s01.wav", "s02.wav", "s03.wav"]
    on_disk = json.loads((out / "demo" / "station.json").read_text())
    assert on_disk == st
    assert st["id"] == "demo" and st["title"] == "Demo"
    assert [s["file"] for s in st["segments"]] == files
    for seg in st["segments"]:
        info = sf.info(str(out / "demo" / seg["file"]))
        assert (info.samplerate, info.channels, info.subtype) == (22050, 1, "PCM_16")
        assert seg["seconds"] == pytest.approx(info.frames / info.samplerate, abs=0.01)
    # the cut falls in the 6-7 s pause (the first segment is about 6.5 s long)
    assert st["segments"][0]["seconds"] == pytest.approx(6.5, abs=0.05)
    assert {f.name: f.read_bytes() for f in d.glob("*.raw.wav")} == before


def test_bundle_command_refuses_stale_and_flags_short(tmp_path):
    from click.testing import CliRunner
    from sleepmix.esoterica.cli import esoterica
    scripts, lib, out = tmp_path / "scripts", tmp_path / "lib", tmp_path / "out"
    (scripts / "stations").mkdir(parents=True)
    (scripts / "stations" / "demo.md").write_text(
        "---\nid: demo\nshow: stations\ntitle: Demo\nlanguage: en\nspeaker: x\n"
        "source_character: clean\nvoice:\n---\n\nHello there.\n")
    d = lib / "demo"
    d.mkdir(parents=True)
    sf.write(d / "p01.raw.wav", take([(0, 3)], 3.0), SR, subtype="FLOAT")
    (d / "p01.raw.json").write_text(json.dumps({"index": 0, "text_sha256": "bad"}))
    args = ["bundle", "demo", "--out", str(out), "--library", str(lib),
            "--scripts", str(scripts)]
    r = CliRunner().invoke(esoterica, args)
    assert r.exit_code != 0 and "no longer match" in r.output
    assert not out.exists()
    (d / "p01.raw.json").unlink()
    r = CliRunner().invoke(esoterica, args)
    assert r.exit_code != 0  # no sidecar and no manifest: no record of the text
    from sleepmix.esoterica.script import load_script
    from sleepmix.esoterica.voicing import text_sha256
    p = load_script(scripts / "stations" / "demo.md").passages[0]
    (d / "p01.raw.json").write_text(json.dumps(
        {"index": 0, "text_sha256": text_sha256(p.text), "speed": None, "delivery": None}))
    r = CliRunner().invoke(esoterica, args)
    assert r.exit_code == 0, r.output
    assert "s01.wav" in r.output and "under 20s" in r.output
