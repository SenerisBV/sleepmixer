from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml

from sleepmix.esoterica import voicing
from sleepmix.esoterica.manifest import read_manifest
from sleepmix.esoterica.providers import Cartesia, ElevenLabs, ProviderError
from sleepmix.esoterica.script import load_all, load_script
import json
import logging

from sleepmix.esoterica.voicing import (
    PER_RECORDING_SHOWS, Voice, VoiceMismatchError, billed_chars, check_distinct_voices,
    check_resume_voice, chunk, load_voices, normalise, voice_passage, voice_recording,
    voice_slot,
)

from .fakes import FakeProvider, FakeResponse, FakeSession, pcm_f32, pcm_s16, tone

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "esoterica" / "scripts"
VOICES = ROOT / "esoterica" / "voices.yaml"
V = Voice(provider="fake", model="m", voice_id="v1")


def speech_rms_db(x, sr=44100, frame=0.02, gate_db=-50.0):
    n = int(frame * sr)
    frames = x[: len(x) // n * n].reshape(-1, n)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-12))
    active = frames[db > gate_db]
    return 20 * np.log10(np.sqrt(np.mean(active.astype(np.float64) ** 2)))


def write_script(root: Path, show: str, id: str, passages: list[str], language="en"):
    d = root / show
    d.mkdir(parents=True, exist_ok=True)
    body = "\n\n[passage]\n\n".join(passages)
    (d / f"{id}.md").write_text(
        f"---\nid: {id}\nshow: {show}\ntitle: T\nlanguage: {language}\nspeaker: x\n"
        f"source_character: tape\nvoice:\n---\n{body}\n")
    return load_script(d / f"{id}.md")


# --- chunk ----------------------------------------------------------------------

def test_chunk_keeps_sentences_and_respects_limit():
    sents = [f"Sentence number {i} is here." for i in range(40)]
    text = " ".join(sents)
    chunks = chunk(text, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks) == text
    for c in chunks:  # every chunk is whole sentences
        assert c.startswith("Sentence") and c.endswith(".")


def test_chunk_short_text_is_one_chunk():
    assert chunk("One. Two? Three!", 1000) == ["One. Two? Three!"]


def test_chunk_hard_splits_a_long_sentence_at_word_boundaries():
    words = [f"w{i:03d}" for i in range(250)]
    text = " ".join(words)  # 999 characters, no sentence end
    assert len(text) >= 999
    chunks = chunk(text, 120)
    assert all(0 < len(c) <= 120 for c in chunks)
    assert " ".join(chunks) == text
    assert all(w in words for c in chunks for w in c.split())


def test_chunk_keeps_tags_whole():
    text = "a " * 30 + '<break time="1s"/> ' + "b " * 30
    for c in chunk(text.strip(), 50):
        assert c.count("<") == c.count(">")


# --- voice_passage --------------------------------------------------------------

def cartesia_tone(call):
    return FakeResponse(200, pcm_f32(tone(0.5)))


def test_voice_passage_joins_chunks_without_clicks_and_normalises(tmp_path):
    s = FakeSession(cartesia_tone)
    p = Cartesia("k", s)
    p.max_chars = 40
    text = "The floor was warm. I had my shoes off. I remember that well. And the light."
    out = tmp_path / "p01.wav"
    dur = voice_passage(p, text, Voice("cartesia", "sonic-3.6", "v"), "en", out)
    assert len(s.calls) > 1  # it really was chunked
    x, sr = sf.read(out, dtype="float32")
    assert sr == 44100 and x.ndim == 1
    assert sf.info(out).subtype == "FLOAT"
    assert dur == pytest.approx(len(x) / sr)
    canned = tone(0.5)
    # normalisation scales everything by one gain, so compare relative jumps
    gain = np.max(np.abs(x)) / np.max(np.abs(canned))
    assert np.max(np.abs(np.diff(x))) <= np.max(np.abs(np.diff(canned))) * gain * 1.01
    assert speech_rms_db(x) == pytest.approx(-24.0, abs=0.5)
    assert 20 * np.log10(np.max(np.abs(x))) <= -3.0 + 1e-6
    # chunks are separated by about 250 ms of silence
    silent = np.abs(x) < 1e-6
    runs = np.diff(np.flatnonzero(np.diff(np.concatenate([[0], silent.astype(int), [0]]))))[::2]
    assert any(abs(r - 0.25 * sr) < 0.02 * sr for r in runs)


def test_voice_passage_limits_peaks(tmp_path):
    spiky = tone(0.5)
    spiky[1000] = 0.9  # a lone spike: the -24 dB RMS target would push it over -3 dBFS
    s = FakeSession(lambda c: FakeResponse(200, pcm_f32(spiky)))
    out = tmp_path / "p.wav"
    voice_passage(Cartesia("k", s), "Hello.", Voice("cartesia", "m", "v"), "en", out)
    x, _ = sf.read(out, dtype="float32")
    assert np.max(np.abs(x)) <= 10 ** (-3 / 20) + 1e-6
    assert speech_rms_db(x) == pytest.approx(-24.0, abs=0.5)


def test_voice_passage_resamples_to_44100(tmp_path):
    s = FakeSession(lambda c: FakeResponse(200, pcm_s16(tone(1.0, sr=24000))))
    out = tmp_path / "p.wav"
    dur = voice_passage(ElevenLabs("k", s), "Hello.", Voice("elevenlabs", "eleven_v4", "v"),
                        "en", out)
    x, sr = sf.read(out, dtype="float32")
    assert sr == 44100
    assert dur == pytest.approx(1.0, abs=0.03)


def test_voice_passage_skips_existing(tmp_path):
    out = tmp_path / "p.wav"
    sf.write(out, np.zeros(44100, np.float32), 44100, subtype="FLOAT")
    fp = FakeProvider()
    assert voice_passage(fp, "Hello.", V, "en", out) == pytest.approx(1.0)
    assert fp.calls == []


def test_voice_passage_long_pause_is_real_silence(tmp_path):
    fp = FakeProvider()
    out = tmp_path / "p.wav"
    voice_passage(fp, "Mubba. [long pause] Mubba mubba.", V, "en", out)
    assert len(fp.calls) == 2
    assert all("[" not in c[0] for c in fp.calls)
    x, sr = sf.read(out, dtype="float32")
    silent = np.abs(x) < 1e-6
    edges = np.flatnonzero(np.diff(np.concatenate([[0], silent.astype(int), [0]])))
    longest = np.max(edges[1::2] - edges[::2])
    assert longest >= 2.0 * sr


def test_voice_passage_failure_leaves_no_file(tmp_path):
    fp = FakeProvider(fail_when=lambda t: "two" in t)
    fp.max_chars = 10
    out = tmp_path / "p.wav"
    with pytest.raises(ProviderError):
        voice_passage(fp, "one one. two two. three.", V, "en", out)
    assert list(tmp_path.iterdir()) == []


# --- voice_recording ------------------------------------------------------------

def test_voice_recording_writes_passages_and_manifest(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["One. [pause] Two.", "<!-- intensity: low -->\nThree.", "Four."])
    lib = tmp_path / "lib"
    m = voice_recording(s, FakeProvider(), V, lib)
    assert m is not None
    d = lib / "rec"
    assert sorted(p.name for p in d.iterdir()) == ["p01.wav", "p02.wav", "p03.wav",
                                                    "recording.json", "voice.json"]
    back = read_manifest(d / "recording.json")
    assert back == m
    assert [e.file for e in m.passages] == ["p01.wav", "p02.wav", "p03.wav"]
    assert [e.index for e in m.passages] == [0, 1, 2]
    assert m.passages[0].text == "One. Two."
    assert m.passages[1].intensity == "low"
    assert m.provider == "fake" and m.model == "m" and m.voice_id == "v1"
    assert m.made_at.endswith("+00:00") or m.made_at.endswith("Z")
    assert all(e.duration_s > 0 for e in m.passages)


def test_voice_recording_is_resumable(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    again = FakeProvider()
    m = voice_recording(s, again, V, lib)
    assert again.calls == []
    assert m is not None and len(m.passages) == 2


def test_mid_run_failure_keeps_done_passages_and_no_manifest(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["One.", "Two.", "Three fails.", "Four."])
    lib = tmp_path / "lib"
    bad = FakeProvider(fail_when=lambda t: "Three" in t)
    assert voice_recording(s, bad, V, lib) is None
    d = lib / "rec"
    assert sorted(p.name for p in d.iterdir()) == ["p01.wav", "p02.wav", "voice.json"]
    good = FakeProvider()
    m = voice_recording(s, good, V, lib)
    assert m is not None
    assert len(good.calls) == 2  # only passages 3 and 4
    assert (d / "recording.json").exists()


def test_shuffles_voice_one_image_per_call_with_seeded_gaps(tmp_path):
    lines = ["bright yellow", "warm rain", "une pomme verte", "sour apple"]
    s = write_script(tmp_path / "scripts", "shuffles", "shuf", ["\n".join(lines)])
    lib = tmp_path / "lib"
    fp = FakeProvider()
    m = voice_recording(s, fp, V, lib)
    assert [c[0] for c in fp.calls] == lines
    assert [c[3] for c in fp.calls] == ["en", "en", "fr", "en"]
    x, sr = sf.read(lib / "shuf" / "p01.wav", dtype="float32")
    silent = np.abs(x) < 1e-6
    edges = np.flatnonzero(np.diff(np.concatenate([[0], silent.astype(int), [0]])))
    gaps = (edges[1::2] - edges[::2]) / sr
    inner = [g for g in gaps if g > 1.0]
    assert len(inner) == 3 and all(2.0 <= g <= 3.0 for g in inner)
    # same id -> same gaps
    lib2 = tmp_path / "lib2"
    voice_recording(s, FakeProvider(), V, lib2)
    y, _ = sf.read(lib2 / "shuf" / "p01.wav", dtype="float32")
    assert len(y) == len(x)
    assert m.passages[0].text.split("\n") == lines


# --- slots and voices.yaml ------------------------------------------------------

def test_voice_slot():
    scripts = {s.id: s for s in load_all(REAL)}
    assert PER_RECORDING_SHOWS == frozenset({"testimonies", "addresses"})
    assert voice_slot(scripts["backward-lesson-one"]) == voice_slot(scripts["mubba-lesson-one"]) == "lessons"
    assert voice_slot(scripts["the-corridors"]) == "the-corridors"
    assert voice_slot(scripts["the-corridors"]) != voice_slot(scripts["the-orchard-light"])
    assert voice_slot(scripts["the-lantern-accords"]) == "the-lantern-accords"


def test_real_voices_yaml_covers_every_slot():
    cfg = load_voices(VOICES)
    scripts = load_all(REAL)
    slots = {voice_slot(s) for s in scripts}
    assert set(cfg.candidates) == slots
    for slot, per in cfg.candidates.items():
        assert set(per) == {"elevenlabs", "cartesia"}
        for prov, cands in per.items():
            assert 2 <= len(cands) <= 3, (slot, prov)
            for c in cands:
                assert c["voice_id"] and c["name"] and c["why"]
    for prov in ("elevenlabs", "cartesia"):
        p = cfg.providers[prov]
        assert p["model"] and p["price_per_char"] > 0 and p["max_chars"] > 0
    check_distinct_voices(cfg.chosen, scripts)


def test_testimony_slots_share_no_candidates():
    cfg = load_voices(VOICES)
    a = {c["voice_id"] for cs in cfg.candidates["the-corridors"].values() for c in cs}
    b = {c["voice_id"] for cs in cfg.candidates["the-orchard-light"].values() for c in cs}
    assert not a & b


def test_chosen_testimony_and_address_voices_must_be_distinct():
    scripts = load_all(REAL)
    ok = {"the-corridors": {"provider": "elevenlabs", "model": "m", "voice_id": "A"},
          "the-orchard-light": {"provider": "elevenlabs", "model": "m", "voice_id": "B"},
          "the-lantern-accords": {"provider": "cartesia", "model": "m", "voice_id": "C"},
          "lessons": {"provider": "elevenlabs", "model": "m", "voice_id": "A"}}
    check_distinct_voices(ok, scripts)  # a per-show slot may reuse a voice
    bad = dict(ok)
    bad["the-lantern-accords"] = {"provider": "elevenlabs", "model": "m", "voice_id": "A"}
    with pytest.raises(ValueError, match="the-corridors.*the-lantern-accords|the-lantern-accords.*the-corridors"):
        check_distinct_voices(bad, scripts)


def test_load_voices_rejects_malformed_chosen(tmp_path):
    data = yaml.safe_load(VOICES.read_text())
    data["chosen"] = {"lessons": {"provider": "elevenlabs"}}
    p = tmp_path / "voices.yaml"
    p.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="lessons"):
        load_voices(p)


# --- review round 1 ---------------------------------------------------------------

def test_chunk_measures_translated_length():
    text = " ".join(["Word word. [pause]"] * 20)
    measure = lambda t: len(Cartesia.translate_cues(t))
    chunks = chunk(text, 100, measure=measure)
    assert all(measure(c) <= 100 for c in chunks)
    # plain len() would pack more per chunk than the provider can take
    assert any(measure(c) > 100 for c in chunk(text, 100))


def test_voice_passage_sends_chunks_within_limit_after_translation(tmp_path):
    s = FakeSession(cartesia_tone)
    p = Cartesia("k", s)
    p.max_chars = 60
    text = " ".join(["The floor was warm. [pause]"] * 8)
    voice_passage(p, text, Voice("cartesia", "m", "v"), "en", tmp_path / "p.wav")
    assert all(len(c["json"]["transcript"]) <= 60 for c in s.calls)


def test_billed_chars_counts_what_is_sent():
    text = "One. [pause] Two. [long pause] Three [breath] four."
    # [long pause] is a split, never sent; each segment counted after translation
    assert billed_chars(text, Cartesia.translate_cues) == (
        len(Cartesia.translate_cues("One. [pause] Two."))
        + len(Cartesia.translate_cues("Three [breath] four.")))
    assert billed_chars(text, ElevenLabs.translate_cues) == (
        len(ElevenLabs.translate_cues("One. [pause] Two."))
        + len(ElevenLabs.translate_cues("Three [breath] four.")))
    assert billed_chars(text, Cartesia.translate_cues) > len("One. Two.Three four.")


def test_resume_with_a_different_voice_is_refused(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["One.", "Two fails.", "Three."])
    lib = tmp_path / "lib"
    assert voice_recording(s, FakeProvider(fail_when=lambda t: "Two" in t), V, lib) is None
    rec = json.loads((lib / "rec" / "voice.json").read_text())
    assert rec == {"provider": "fake", "model": "m", "voice_id": "v1"}
    other = FakeProvider()
    with pytest.raises(VoiceMismatchError, match="rec.*v1.*v2"):
        voice_recording(s, other, Voice("fake", "m", "v2"), lib)
    assert other.calls == []
    # the same voice resumes fine
    assert voice_recording(s, FakeProvider(), V, lib) is not None


def test_resume_refused_for_finished_recording_with_other_voice(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    (lib / "rec" / "voice.json").unlink()  # the manifest alone still records it
    with pytest.raises(VoiceMismatchError):
        check_resume_voice(s, Voice("fake", "m", "other"), lib)
    check_resume_voice(s, V, lib)


def test_resume_refused_for_passages_with_no_voice_record(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    d = tmp_path / "lib" / "rec"
    d.mkdir(parents=True)
    sf.write(d / "p01.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")
    fp = FakeProvider()
    with pytest.raises(VoiceMismatchError, match="no record"):
        voice_recording(s, fp, V, tmp_path / "lib")
    assert fp.calls == []


def test_normalise_warns_when_it_cannot_reach_the_target(caplog):
    x = np.zeros(44100, np.float32)
    x[::1000] = 0.9  # a sparse spike train: capped at -3 dBFS, RMS stays far below -24
    with caplog.at_level(logging.WARNING, logger="sleepmix.esoterica.voicing"):
        normalise(x)
    assert "misses" in caplog.text


def test_normalise_quiet_when_on_target(caplog):
    with caplog.at_level(logging.WARNING, logger="sleepmix.esoterica.voicing"):
        normalise(tone(1.0) * 0.1)
    assert "misses" not in caplog.text
