import json

import pytest

from sleepmix.esoterica import manifest as mf
from sleepmix.esoterica.manifest import Manifest, PassageEntry, read_manifest, write_manifest


def make():
    return Manifest(
        id="a-script", show="testimonies", title="A Title", language="en",
        source_character="tape", provider="elevenlabs", model="m1",
        voice_id="v1", made_at="2026-11-03T10:00:00Z",
        passages=[PassageEntry(0, "passage-00.wav", 12.5, "words", "high"),
                  PassageEntry(1, "passage-01.wav", 8.0, "more", "low")])


def test_round_trip(tmp_path):
    m = make()
    path = write_manifest(m, tmp_path)
    assert path == tmp_path / "recording.json"
    back = read_manifest(path)
    assert back == m
    assert back.format_version == 1
    assert isinstance(back.passages[0], PassageEntry)


def test_creates_missing_dir(tmp_path):
    path = write_manifest(make(), tmp_path / "x" / "y")
    assert path.exists()


def test_atomic_write_leaves_nothing_on_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("serialisation failed")
    monkeypatch.setattr(mf.json, "dump", boom)
    with pytest.raises(RuntimeError):
        write_manifest(make(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_failed_rewrite_keeps_previous(tmp_path, monkeypatch):
    write_manifest(make(), tmp_path)
    before = (tmp_path / "recording.json").read_text()
    monkeypatch.setattr(mf.json, "dump", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        write_manifest(make(), tmp_path)
    assert (tmp_path / "recording.json").read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["recording.json"]


def test_rejects_unknown_format_version(tmp_path):
    path = write_manifest(make(), tmp_path)
    d = json.loads(path.read_text())
    d["format_version"] = 99
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="format_version"):
        read_manifest(path)


@pytest.mark.parametrize("content", ["not json", "[]", '{"format_version": 1}',
                                     '{"format_version": 1, "passages": [{"x": 1}]}'])
def test_malformed_manifest_raises_manifest_error(tmp_path, content):
    p = tmp_path / "recording.json"
    p.write_text(content)
    with pytest.raises(mf.ManifestError) as e:
        read_manifest(p)
    assert str(p) in str(e.value)
    assert isinstance(e.value, ValueError)


def test_missing_manifest_names_path(tmp_path):
    with pytest.raises(mf.ManifestError, match="nope.json"):
        read_manifest(tmp_path / "nope.json")
