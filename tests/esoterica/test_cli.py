import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from sleepmix.cli import main
from sleepmix.esoterica import cli as ecli
from sleepmix.esoterica.script import load_all, spoken_text

from .fakes import FakeProvider

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "esoterica" / "scripts"
VOICES = ROOT / "esoterica" / "voices.yaml"


@pytest.fixture
def fakes(monkeypatch):
    """Every provider the CLI builds is a FakeProvider; record them."""
    made: list[FakeProvider] = []

    def factory(name, cfg, env_path):
        p = FakeProvider()
        p.name = name
        made.append(p)
        return p

    monkeypatch.setattr(ecli, "make_provider", factory)
    return made


def calls(made):
    return sum(len(p.calls) for p in made)


def voices_with_chosen(tmp_path, chosen):
    data = yaml.safe_load(VOICES.read_text())
    data["chosen"] = chosen
    p = tmp_path / "voices.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True))
    return p


def all_chosen(tmp_path):
    scripts = load_all(REAL)
    slots = sorted({s.id if s.show in ("testimonies", "addresses") else s.show
                    for s in scripts})
    return voices_with_chosen(tmp_path, {
        slot: {"provider": "elevenlabs", "model": "eleven_v4", "voice_id": f"v-{slot}"}
        for slot in slots})


def run(args):
    return CliRunner().invoke(main, ["esoterica", *args], catch_exceptions=False)


def test_estimate_prints_characters_and_cost(fakes):
    r = run(["estimate", "--scripts", str(REAL), "--voices", str(VOICES)])
    assert r.exit_code == 0, r.output
    total = sum(len(spoken_text(p)) for s in load_all(REAL) for p in s.passages)
    assert f"{total:,}" in r.output
    assert "elevenlabs" in r.output and "cartesia" in r.output
    assert "$" in r.output
    assert calls(fakes) == 0 and fakes == []


def test_voice_all_without_yes_spends_nothing(fakes, tmp_path):
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    r = run(["voice", "--all", "--scripts", str(REAL), "--voices", str(v),
             "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert "re-run with --yes" in r.output
    assert re.search(r"elevenlabs.*[\d,]+ characters.*\$", r.output)
    assert calls(fakes) == 0
    assert not lib.exists() or not any(lib.rglob("*.wav"))


def test_voice_one_with_yes_writes_library(fakes, tmp_path):
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    r = run(["voice", "the-corridors", "--yes", "--scripts", str(REAL), "--voices", str(v),
             "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert (lib / "the-corridors" / "recording.json").exists()
    assert calls(fakes) > 0
    # second run: nothing left to voice, estimate is zero, no calls
    before = calls(fakes)
    r = run(["voice", "the-corridors", "--yes", "--scripts", str(REAL), "--voices", str(v),
             "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert calls(fakes) == before
    assert re.search(r"\b0 characters", r.output)


def test_voice_without_chosen_fails_before_spend(fakes, tmp_path):
    lib = tmp_path / "library"
    r = CliRunner().invoke(main, ["esoterica", "voice", "--all", "--yes", "--scripts", str(REAL),
                                  "--voices", str(VOICES), "--library", str(lib)])
    assert r.exit_code != 0
    assert "chosen" in r.output and "the-corridors" in r.output
    assert fakes == [] and not lib.exists()


def test_voice_unknown_id(fakes, tmp_path):
    r = CliRunner().invoke(main, ["esoterica", "voice", "nope", "--scripts", str(REAL),
                                  "--voices", str(all_chosen(tmp_path))])
    assert r.exit_code != 0 and "nope" in r.output


def test_audition_without_yes_prints_estimate_and_spends_nothing(fakes, tmp_path):
    out = tmp_path / "audition"
    r = run(["audition", "--all", "--scripts", str(REAL), "--voices", str(VOICES),
             "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert "re-run with --yes" in r.output
    assert re.search(r"elevenlabs.*[\d,]+ characters", r.output)
    assert re.search(r"cartesia.*[\d,]+ characters", r.output)
    assert calls(fakes) == 0 and not out.exists()


def test_audition_slot_with_yes_writes_files_and_index(fakes, tmp_path):
    out = tmp_path / "audition"
    r = run(["audition", "--slot", "the-corridors", "--yes", "--scripts", str(REAL),
             "--voices", str(VOICES), "--out", str(out)])
    assert r.exit_code == 0, r.output
    files = sorted(p.name for p in (out / "the-corridors").iterdir())
    assert files == sorted(["elevenlabs-blue.wav", "elevenlabs-empress.wav",
                            "elevenlabs-julie.wav", "cartesia-edith.wav",
                            "cartesia-loretta.wav"])
    index = (out / "index.md").read_text()
    assert "the-corridors" in index and "elevenlabs-blue.wav" in index
    # the excerpt is ~120 words from the first passage
    texts = [c[0] for p in fakes for c in p.calls]
    assert 60 <= sum(len(t.split()) for t in texts) / 5 <= 180
    before = calls(fakes)
    run(["audition", "--slot", "the-corridors", "--yes", "--scripts", str(REAL),
         "--voices", str(VOICES), "--out", str(out)])
    assert calls(fakes) == before  # resumable


def test_audition_show_selects_its_slots(fakes, tmp_path):
    r = run(["audition", "--show", "testimonies", "--scripts", str(REAL),
             "--voices", str(VOICES), "--out", str(tmp_path / "a")])
    assert r.exit_code == 0, r.output
    assert "the-corridors" in r.output and "the-orchard-light" in r.output
    assert "sideline" not in r.output


def test_audition_continues_past_a_failing_voice(fakes, monkeypatch, tmp_path):
    def factory(name, cfg, env_path):
        p = FakeProvider(fail_when=(lambda t: True) if name == "cartesia" else None)
        p.name = name
        fakes.append(p)
        return p
    monkeypatch.setattr(ecli, "make_provider", factory)
    out = tmp_path / "audition"
    r = CliRunner().invoke(main, ["esoterica", "audition", "--slot", "the-corridors", "--yes",
                                  "--scripts", str(REAL), "--voices", str(VOICES),
                                  "--out", str(out)])
    assert r.exit_code != 0
    assert "cartesia" in r.output and "failed" in r.output
    assert (out / "the-corridors" / "elevenlabs-blue.wav").exists()
    assert (out / "index.md").exists()


def test_audition_needs_exactly_one_selector(fakes, tmp_path):
    r = CliRunner().invoke(main, ["esoterica", "audition", "--scripts", str(REAL),
                                  "--voices", str(VOICES), "--out", str(tmp_path)])
    assert r.exit_code != 0
