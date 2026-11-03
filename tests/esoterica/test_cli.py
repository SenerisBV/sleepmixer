import json
import re
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml
from click.testing import CliRunner

from sleepmix.cli import main
from sleepmix.esoterica import cli as ecli
from sleepmix.esoterica.providers import Cartesia, ElevenLabs
from sleepmix.esoterica.script import load_all
from sleepmix.esoterica.voicing import (
    Voice, billed_chars, load_voices, shuffle_billed_chars, shuffle_lines,
)

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


def max_chars(cls):
    return int(load_voices(VOICES).providers[cls.name]["max_chars"])


def sent_chars(cls):
    total = 0
    for s in load_all(REAL):
        for p in s.passages:
            if s.show == "shuffles":
                total += shuffle_billed_chars(shuffle_lines(p.text), cls.translate_cues)
            else:
                total += billed_chars(p.text, cls.translate_cues, max_chars(cls))
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
    files = sorted(p.name for p in (out / "the-corridors").glob("*.wav"))
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
    el = billed_chars(ex, ElevenLabs.translate_cues, max_chars(ElevenLabs))
    ca = billed_chars(ex, Cartesia.translate_cues, max_chars(Cartesia))
    assert re.search(rf"elevenlabs .*{3 * el:,} characters", r.output)
    assert re.search(rf"cartesia .*{2 * ca:,} characters", r.output)


def test_voice_refuses_to_resume_with_a_different_voice(fakes, tmp_path):
    lib = tmp_path / "library"
    v1 = all_chosen(tmp_path)
    d = lib / "the-corridors"
    d.mkdir(parents=True)
    (d / "voice.json").write_text('{"provider": "elevenlabs", "model": "eleven_v4", '
                                  '"voice_id": "someone-else"}')
    sf.write(d / "p01.raw.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")  # paid
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


def test_render_all_skips_unvoiced_but_named_id_still_fails(fakes, no_keys, tmp_path):
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    run(["voice", "the-corridors", "--yes", "--scripts", str(REAL), "--voices", str(v),
         "--library", str(lib)])
    before = calls(fakes)
    r = run(["render", "--all", "--scripts", str(REAL), "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert "the-corridors:" in r.output and "passages rendered" in r.output
    assert "skipped, not voiced" in r.output
    assert calls(fakes) == before
    assert (lib / "the-corridors" / "recording.json").exists()
    assert not (lib / "shuffles-one").exists()
    r2 = CliRunner().invoke(main, ["esoterica", "render", "shuffles-one", "--scripts",
                                   str(REAL), "--library", str(lib)])
    assert r2.exit_code != 0 and "raw" in r2.output


def test_remaining_counts_raw_files_not_rendered(tmp_path):
    s = [x for x in load_all(REAL) if x.id == "the-corridors"][0]
    cfg = load_voices(VOICES)
    v = Voice("elevenlabs", "eleven_v4", "x")
    d = tmp_path / s.id
    d.mkdir()
    sf.write(d / "p01.wav", np.zeros(10, np.float32), 44100, subtype="FLOAT")
    full = ecli._remaining(s, tmp_path, v, cfg)
    sf.write(d / "p01.raw.wav", np.zeros(10, np.float32), 44100, subtype="FLOAT")
    assert ecli._remaining(s, tmp_path, v, cfg) < full


# --- final review: partial voicing, stale scripts, --revoice ------------------------

def _copy_scripts(tmp_path, only=("the-corridors",)):
    import shutil
    root = tmp_path / "scripts"
    for s in load_all(REAL):
        if s.id in only:
            (root / s.show).mkdir(parents=True, exist_ok=True)
            shutil.copy(s.path, root / s.show / s.path.name)
    return root


def _edit_passage(root, id, n, new_text):
    """Replace passage n (1-based) of `id` with new_text (keeps the rest)."""
    path = next(root.glob(f"*/{id}.md"))
    head, body = path.read_text().split("\n---\n", 1)
    parts = body.split("\n[passage]\n")
    parts[n - 1] = f"\n{new_text}\n"
    path.write_text(head + "\n---\n" + "\n[passage]\n".join(parts))


def test_render_all_partial_with_a_two_passage_script(fakes, no_keys, tmp_path):
    root = tmp_path / "scripts" / "testimonies"
    root.mkdir(parents=True)
    (root / "two.md").write_text("---\nid: two\nshow: testimonies\ntitle: T\nlanguage: en\n"
                                 "speaker: x\nsource_character: tape\nvoice:\n---\n"
                                 "One.\n\n[passage]\n\nTwo.\n")
    lib = tmp_path / "library"
    (lib / "two").mkdir(parents=True)
    sf.write(lib / "two" / "p01.raw.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")
    r = run(["render", "--all", "--scripts", str(tmp_path / "scripts"), "--library", str(lib)])
    assert r.exit_code == 0, r.output
    assert "two: skipped, partially voiced (missing p02.raw.wav)" in r.output
    r2 = CliRunner().invoke(main, ["esoterica", "render", "two", "--scripts",
                                   str(tmp_path / "scripts"), "--library", str(lib)])
    assert r2.exit_code != 0 and "p02.raw.wav" in r2.output


def test_voice_and_render_refuse_a_stale_script(fakes, no_keys, tmp_path):
    root = _copy_scripts(tmp_path)
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--yes", "--scripts",
                              str(root), "--voices", str(v), "--library", str(lib)],
                       catch_exceptions=False)
    _edit_passage(root, "the-corridors", 2, "An entirely new second passage.")
    before = calls(fakes)
    r = CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--scripts",
                                  str(root), "--voices", str(v), "--library", str(lib)])
    assert r.exit_code != 0
    assert "p02" in r.output and "--revoice p02" in r.output
    r = CliRunner().invoke(main, ["esoterica", "render", "the-corridors", "--scripts",
                                  str(root), "--library", str(lib)])
    assert r.exit_code != 0 and "p02" in r.output
    r = CliRunner().invoke(main, ["esoterica", "render", "--all", "--scripts",
                                  str(root), "--library", str(lib)])
    assert r.exit_code != 0 and "p02" in r.output
    assert calls(fakes) == before


def test_revoice_prints_estimate_then_deletes_only_named_stale_takes_with_yes(
        fakes, monkeypatch, tmp_path):
    root = _copy_scripts(tmp_path)
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    args = ["--scripts", str(root), "--voices", str(v), "--library", str(lib)]
    CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--yes", *args],
                       catch_exceptions=False)
    d = lib / "the-corridors"
    raws = {p.name: p.read_bytes() for p in d.glob("*.raw.wav")}
    _edit_passage(root, "the-corridors", 2, "An entirely new second passage.")

    # without --yes: estimate only, nothing deleted, nothing spent, no key read
    def boom(*a, **k):
        raise AssertionError("an API key was read without --yes")
    monkeypatch.setattr(ecli, "api_key", boom)
    before = calls(fakes)
    r = CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--revoice", "p02",
                                  *args])
    assert r.exit_code == 0, r.output
    n = len(ElevenLabs.translate_cues("An entirely new second passage."))
    assert re.search(rf"elevenlabs .*\b{n} characters", r.output)
    assert "p02.raw.wav" in r.output and "re-run with --yes" in r.output
    assert {p.name: p.read_bytes() for p in d.glob("*.raw.wav")} == raws
    assert calls(fakes) == before

    # naming a passage that is not stale is refused
    r = CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--revoice", "p01",
                                  "--revoice", "p02", "--yes", *args])
    assert r.exit_code != 0 and "p01" in r.output and "not stale" in r.output
    assert {p.name: p.read_bytes() for p in d.glob("*.raw.wav")} == raws

    # with --yes: only p02 is re-voiced; every other take is byte-identical
    r = CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--revoice", "p02",
                                  "--yes", *args], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    sent = [c[0] for p in fakes for c in p.calls][before:]
    assert sent == ["An entirely new second passage."]
    after = {p.name: p.read_bytes() for p in d.glob("*.raw.wav")}
    assert after.keys() == raws.keys()
    assert {k for k in raws if raws[k] != after[k]} == {"p02.raw.wav"}
    m = __import__("json").loads((d / "recording.json").read_text())
    assert m["passages"][1]["text"] == "An entirely new second passage."
    r = CliRunner().invoke(main, ["esoterica", "render", "the-corridors", "--scripts",
                                  str(root), "--library", str(lib)])
    assert r.exit_code == 0, r.output


def test_revoice_must_name_every_stale_passage_and_needs_one_id(fakes, tmp_path):
    root = _copy_scripts(tmp_path)
    v = all_chosen(tmp_path)
    lib = tmp_path / "library"
    args = ["--scripts", str(root), "--voices", str(v), "--library", str(lib)]
    CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--yes", *args],
                       catch_exceptions=False)
    _edit_passage(root, "the-corridors", 1, "New first.")
    _edit_passage(root, "the-corridors", 2, "New second.")
    r = CliRunner().invoke(main, ["esoterica", "voice", "the-corridors", "--revoice", "p01",
                                  "--yes", *args])
    assert r.exit_code != 0 and "p02" in r.output
    r = CliRunner().invoke(main, ["esoterica", "voice", "--all", "--revoice", "p01", *args])
    assert r.exit_code != 0


# --- final review: audition files know their voice -----------------------------------

def _corridors_audition(out, voices, **kw):
    return CliRunner().invoke(main, ["esoterica", "audition", "--slot", "the-corridors",
                                     *(["--yes"] if kw.get("yes") else []),
                                     "--scripts", str(REAL), "--voices", str(voices),
                                     "--out", str(out)], catch_exceptions=False)


def test_audition_writes_a_voice_sidecar_per_file(fakes, tmp_path):
    import json
    out = tmp_path / "audition"
    r = _corridors_audition(out, VOICES, yes=True)
    assert r.exit_code == 0, r.output
    cfg = load_voices(VOICES)
    blue = next(c for c in cfg.candidates["the-corridors"]["elevenlabs"] if c["name"] == "Blue")
    side = json.loads((out / "the-corridors" / "elevenlabs-blue.json").read_text())
    assert side == {"provider": "elevenlabs", "model": cfg.providers["elevenlabs"]["model"],
                    "voice_id": blue["voice_id"], "name": "Blue"}
    assert blue["voice_id"] in (out / "index.md").read_text()


def test_audition_redoes_a_file_whose_voice_changed(fakes, tmp_path):
    import json
    out = tmp_path / "audition"
    _corridors_audition(out, VOICES, yes=True)
    before = calls(fakes)
    untouched = (out / "the-corridors" / "elevenlabs-julie.wav").read_bytes()
    data = yaml.safe_load(VOICES.read_text())
    for c in data["candidates"]["the-corridors"]["elevenlabs"]:
        if c["name"] == "Blue":
            c["voice_id"] = "a-new-blue"
    v2 = tmp_path / "voices.yaml"
    v2.write_text(yaml.safe_dump(data, allow_unicode=True))
    s = next(x for x in load_all(REAL) if x.id == "the-corridors")
    one = billed_chars(ecli.audition_excerpt(s), ElevenLabs.translate_cues, max_chars(ElevenLabs))
    r = _corridors_audition(out, v2)  # estimate only
    assert re.search(rf"elevenlabs .*\b{one:,} characters", r.output)
    assert "elevenlabs-blue" in r.output and calls(fakes) == before
    r = _corridors_audition(out, v2, yes=True)
    assert r.exit_code == 0, r.output
    new = [c for p in fakes for c in p.calls][before:]
    assert {c[1] for c in new} == {"a-new-blue"}
    side = json.loads((out / "the-corridors" / "elevenlabs-blue.json").read_text())
    assert side["voice_id"] == "a-new-blue"
    assert (out / "the-corridors" / "elevenlabs-julie.wav").read_bytes() == untouched
    assert "a-new-blue" in (out / "index.md").read_text()


def test_audition_file_without_a_sidecar_is_redone(fakes, tmp_path):
    out = tmp_path / "audition"
    _corridors_audition(out, VOICES, yes=True)
    (out / "the-corridors" / "cartesia-edith.json").unlink()
    r = _corridors_audition(out, VOICES)
    s = next(x for x in load_all(REAL) if x.id == "the-corridors")
    one = billed_chars(ecli.audition_excerpt(s), Cartesia.translate_cues, max_chars(Cartesia))
    assert re.search(rf"cartesia .*\b{one:,} characters", r.output)
    assert re.search(r"elevenlabs .*\b0 characters", r.output)


# --- pace -------------------------------------------------------------------------

def _speedy_scripts(tmp_path):
    root = tmp_path / "scripts"
    for show, id, extra in (("testimonies", "slow-one", "speed: 0.7\n"),
                            ("testimonies", "plain-one", "")):
        (root / show).mkdir(parents=True, exist_ok=True)
        (root / show / f"{id}.md").write_text(
            f"---\nid: {id}\nshow: {show}\ntitle: T\nlanguage: en\nspeaker: x\n"
            f"source_character: clean\n{extra}voice:\n---\nOne. Two.\n")
    return root


def test_voice_sends_each_recordings_own_speed(monkeypatch, tmp_path):
    seen = []

    def factory(name, cfg, env_path):
        seen.append((cfg.get("settings") or {}).get("speed"))
        p = FakeProvider()
        p.name = name
        return p

    monkeypatch.setattr(ecli, "make_provider", factory)
    root = _speedy_scripts(tmp_path)
    voices = voices_with_chosen(tmp_path, {
        s: {"provider": "elevenlabs", "model": "eleven_v4", "voice_id": f"v-{s}"}
        for s in ("slow-one", "plain-one")})
    r = CliRunner().invoke(main, ["esoterica", "voice", "--all", "--yes",
                                  "--scripts", str(root), "--voices", str(voices),
                                  "--library", str(tmp_path / "lib")])
    assert r.exit_code == 0, r.output
    default = (yaml.safe_load(VOICES.read_text())["providers"]["elevenlabs"].get("settings") or {}).get("speed")
    assert sorted(seen, key=str) == sorted([0.7, default], key=str)
    side = json.loads((tmp_path / "lib" / "slow-one" / "p01.raw.json").read_text())
    assert side["speed"] == 0.7


def test_revoice_after_a_speed_change(monkeypatch, tmp_path, fakes):
    root = _speedy_scripts(tmp_path)
    voices = voices_with_chosen(tmp_path, {
        s: {"provider": "elevenlabs", "model": "eleven_v4", "voice_id": f"v-{s}"}
        for s in ("slow-one", "plain-one")})
    args = ["--scripts", str(root), "--voices", str(voices), "--library", str(tmp_path / "lib")]
    assert CliRunner().invoke(main, ["esoterica", "voice", "plain-one", "--yes", *args]).exit_code == 0
    p = root / "testimonies" / "plain-one.md"
    p.write_text(p.read_text().replace("voice:\n", "speed: 0.7\nvoice:\n"))
    r = CliRunner().invoke(main, ["esoterica", "voice", "plain-one", "--yes", *args])
    assert r.exit_code != 0 and "speed changed" in r.output and "--revoice p01" in r.output
    before = calls(fakes)
    r = CliRunner().invoke(main, ["esoterica", "voice", "plain-one", "--revoice", "p01",
                                  "--yes", *args])
    assert r.exit_code == 0, r.output
    assert calls(fakes) > before


def test_delivery_for_cartesia_is_refused_before_anything_is_deleted(monkeypatch, tmp_path, fakes):
    root = _speedy_scripts(tmp_path)
    p = root / "testimonies" / "plain-one.md"
    voices = voices_with_chosen(tmp_path, {
        s: {"provider": "cartesia", "model": "sonic-3.6", "voice_id": f"v-{s}"}
        for s in ("slow-one", "plain-one")})
    args = ["--scripts", str(root), "--voices", str(voices), "--library", str(tmp_path / "lib")]
    assert CliRunner().invoke(main, ["esoterica", "voice", "plain-one", "--yes", *args]).exit_code == 0
    p.write_text(p.read_text().replace("voice:\n", "delivery: '[slowly]'\nvoice:\n"))
    before = calls(fakes)
    r = CliRunner().invoke(main, ["esoterica", "voice", "plain-one", "--revoice", "p01",
                                  "--yes", *args])
    assert r.exit_code != 0 and "read it aloud" in r.output
    assert calls(fakes) == before
    assert (tmp_path / "lib" / "plain-one" / "p01.raw.wav").exists()
