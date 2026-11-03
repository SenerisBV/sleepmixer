import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from sleepmix.cli import main
from sleepmix.esoterica import cli as ecli
from sleepmix.esoterica.providers import Cartesia, ElevenLabs
from sleepmix.esoterica.script import load_all
from sleepmix.esoterica.voicing import billed_chars, shuffle_billed_chars, shuffle_lines

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


@pytest.fixture
def no_keys(monkeypatch):
    """Any attempt to read a key fails the test loudly."""
    def boom(*a, **k):
        raise AssertionError("an API key was read without --yes")
    monkeypatch.setattr(ecli, "api_key", boom)


def sent_chars(cls):
    total = 0
    for s in load_all(REAL):
        for p in s.passages:
            if s.show == "shuffles":
                total += shuffle_billed_chars(shuffle_lines(p.text), cls.translate_cues)
            else:
                total += billed_chars(p.text, cls.translate_cues)
    return total


def run(args):
    return CliRunner().invoke(main, ["esoterica", *args], catch_exceptions=False)


def test_estimate_prints_characters_and_cost(fakes, no_keys):
    r = run(["estimate", "--scripts", str(REAL), "--voices", str(VOICES)])
    assert r.exit_code == 0, r.output
    el, ca = sent_chars(ElevenLabs), sent_chars(Cartesia)
    assert ca > el  # Cartesia's <break> tags are longer than the neutral cues
    assert re.search(rf"elevenlabs .*{el:,} characters", r.output)
    assert re.search(rf"cartesia .*{ca:,} characters", r.output)
    assert "elevenlabs" in r.output and "cartesia" in r.output
    assert "$" in r.output
    assert calls(fakes) == 0 and fakes == []


def test_voice_all_without_yes_spends_nothing(fakes, no_keys, tmp_path):
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    r = run(["voice", "--all", "--scripts", str(REAL), "--voices", str(v),
             "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert "re-run with --yes" in r.output
    assert re.search(r"elevenlabs.*[\d,]+ characters.*\$", r.output)
    assert re.search(rf"elevenlabs .*{sent_chars(ElevenLabs):,} characters", r.output)
    assert calls(fakes) == 0
    assert fakes == []  # no provider was even built
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
    data = yaml.safe_load(VOICES.read_text())
    data["chosen"] = {k: v for k, v in data["chosen"].items() if k != "the-corridors"}
    voices = tmp_path / "voices.yaml"
    voices.write_text(yaml.safe_dump(data))
    r = CliRunner().invoke(main, ["esoterica", "voice", "--all", "--yes", "--scripts", str(REAL),
                                  "--voices", str(voices), "--library", str(lib)])
    assert r.exit_code != 0
    assert "chosen" in r.output and "the-corridors" in r.output
    assert fakes == [] and not lib.exists()


def test_voice_unknown_id(fakes, tmp_path):
    r = CliRunner().invoke(main, ["esoterica", "voice", "nope", "--scripts", str(REAL),
                                  "--voices", str(all_chosen(tmp_path))])
    assert r.exit_code != 0 and "nope" in r.output


def test_audition_without_yes_prints_estimate_and_spends_nothing(fakes, no_keys, tmp_path):
    out = tmp_path / "audition"
    r = run(["audition", "--all", "--scripts", str(REAL), "--voices", str(VOICES),
             "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert "re-run with --yes" in r.output
    assert re.search(r"elevenlabs.*[\d,]+ characters", r.output)
    assert re.search(r"cartesia.*[\d,]+ characters", r.output)
    assert calls(fakes) == 0 and not out.exists()
    assert fakes == []  # no provider was even built


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


# --- review round 1 ---------------------------------------------------------------

def test_missing_second_key_costs_nothing(monkeypatch, tmp_path):
    """Every provider (key) is resolved before the first request."""
    made = []

    def factory(name, cfg, env_path):
        if name == "elevenlabs":
            raise ecli.click.ClickException("ELEVENLABS_API_KEY is not set")
        p = FakeProvider()
        p.name = name
        made.append(p)
        return p

    monkeypatch.setattr(ecli, "make_provider", factory)
    out = tmp_path / "audition"
    r = CliRunner().invoke(main, ["esoterica", "audition", "--slot", "the-corridors", "--yes",
                                  "--scripts", str(REAL), "--voices", str(VOICES),
                                  "--out", str(out)])
    assert r.exit_code != 0 and "ELEVENLABS_API_KEY" in r.output
    assert calls(made) == 0
    assert not out.exists() or not any(out.rglob("*.wav"))


def test_make_provider_reports_missing_key_without_spending(monkeypatch, tmp_path):
    monkeypatch.setattr(ecli, "api_key", lambda name, env: (_ for _ in ()).throw(KeyError(name)))
    with pytest.raises(ecli.click.ClickException, match="CARTESIA_API_KEY"):
        ecli.make_provider("cartesia", {"max_chars": 10}, tmp_path / ".env")


def test_audition_index_written_even_when_a_run_crashes(monkeypatch, tmp_path):
    made = []

    def factory(name, cfg, env_path):
        p = FakeProvider()
        p.name = name
        if name == "cartesia":
            def crash(*a, **k):
                raise RuntimeError("disk full")
            p.synthesize = crash
        made.append(p)
        return p

    monkeypatch.setattr(ecli, "make_provider", factory)
    out = tmp_path / "audition"
    r = CliRunner().invoke(main, ["esoterica", "audition", "--slot", "the-corridors", "--yes",
                                  "--scripts", str(REAL), "--voices", str(VOICES),
                                  "--out", str(out)])
    assert r.exit_code != 0 and isinstance(r.exception, RuntimeError)
    index = (out / "index.md").read_text()
    assert "the-corridors" in index


def test_audition_estimate_counts_translated_characters(fakes, tmp_path):
    r = run(["audition", "--slot", "the-corridors", "--scripts", str(REAL),
             "--voices", str(VOICES), "--out", str(tmp_path / "a")])
    s = next(x for x in load_all(REAL) if x.id == "the-corridors")
    ex = ecli.audition_excerpt(s)
    el = billed_chars(ex, ElevenLabs.translate_cues)
    ca = billed_chars(ex, Cartesia.translate_cues)
    assert re.search(rf"elevenlabs .*{3 * el:,} characters", r.output)
    assert re.search(rf"cartesia .*{2 * ca:,} characters", r.output)


def test_voice_refuses_to_resume_with_a_different_voice(fakes, tmp_path):
    lib = tmp_path / "library"
    v1 = all_chosen(tmp_path)
    d = lib / "the-corridors"
    d.mkdir(parents=True)
    (d / "voice.json").write_text('{"provider": "elevenlabs", "model": "eleven_v4", '
                                  '"voice_id": "someone-else"}')
    r = CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--yes",
                                  "--scripts", str(REAL), "--voices", str(v1),
                                  "--library", str(lib)])
    assert r.exit_code != 0
    assert "someone-else" in r.output and "v-the-corridors" in r.output
    assert fakes == []


def test_render_needs_no_key_no_provider_and_keeps_raw(fakes, no_keys, tmp_path):
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    run(["voice", "the-corridors", "--yes", "--scripts", str(REAL), "--voices", str(v),
         "--library", str(lib)])
    d = lib / "the-corridors"
    raws = {p.name: p.read_bytes() for p in d.glob("*.raw.wav")}
    assert raws
    (d / "p01.wav").write_bytes(b"stale")
    before = calls(fakes)
    r = run(["render", "the-corridors", "--scripts", str(REAL), "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert calls(fakes) == before
    assert {p.name: p.read_bytes() for p in d.glob("*.raw.wav")} == raws
    assert (d / "p01.wav").read_bytes() != b"stale"
    assert (d / "recording.json").exists()


def test_render_fails_clearly_when_raw_is_missing(fakes, no_keys, tmp_path):
    r = CliRunner().invoke(main, ["esoterica", "render", "the-corridors", "--scripts",
                                  str(REAL), "--library", str(tmp_path / "library")])
    assert r.exit_code != 0
    assert "raw" in r.output and "voice" in r.output


def test_remaining_counts_raw_files_not_rendered(tmp_path):
    s = [x for x in load_all(REAL) if x.id == "the-corridors"][0]
    d = tmp_path / s.id
    d.mkdir()
    import numpy as np, soundfile as sf
    sf.write(d / "p01.wav", np.zeros(10, np.float32), 44100, subtype="FLOAT")
    full = ecli._remaining(s, tmp_path, "elevenlabs")
    sf.write(d / "p01.raw.wav", np.zeros(10, np.float32), 44100, subtype="FLOAT")
    assert ecli._remaining(s, tmp_path, "elevenlabs") < full
