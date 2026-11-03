from pathlib import Path

import pytest

from sleepmix.esoterica.cost import estimate
from sleepmix.esoterica.script import load_all, load_script, spoken_text

REAL = Path(__file__).resolve().parents[2] / "esoterica" / "scripts"


def test_estimate_counts_spoken_characters(tmp_path):
    d = tmp_path / "testimonies"
    d.mkdir()
    (d / "one.md").write_text(
        "---\nid: one\nshow: testimonies\ntitle: T\nlanguage: en\nspeaker: x\n"
        "source_character: tape\nvoice:\n---\nabc [pause] def\n\n[passage]\n\nhello\n")
    s = load_script(d / "one.md")
    est = estimate([s], "elevenlabs", {"elevenlabs": 0.5})
    assert est.characters == len("abc def") + len("hello") == 12
    assert est.cost == pytest.approx(6.0)
    assert est.per_recording == {"one": 12}


def test_estimate_real_scripts_matches_sum():
    scripts = load_all(REAL)
    expected = sum(len(spoken_text(p)) for s in scripts for p in s.passages)
    est = estimate(scripts, "cartoon", {"cartoon": 0.0002})
    assert est.characters == expected > 0
    assert est.cost == pytest.approx(expected * 0.0002)
    assert sum(est.per_recording.values()) == expected
    assert set(est.per_recording) == {s.id for s in scripts}


def test_unknown_provider_names_provider():
    with pytest.raises(KeyError, match="nope"):
        estimate([], "nope", {"a": 1.0})
