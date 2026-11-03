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
import re

from sleepmix.esoterica.voicing import (
    PER_RECORDING_SHOWS, Voice, VoiceMismatchError, billed_chars, check_distinct_voices,
    check_resume_voice, chunk, load_voices, normalise, raw_passage_file, render_character,
    render_recording, voice_passage, voice_recording, voice_slot,
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


def test_voice_passage_failure_leaves_no_file_but_keeps_paid_pieces(tmp_path):
    fp = FakeProvider(fail_when=lambda t: "two" in t)
    fp.max_chars = 10
    out = tmp_path / "p.wav"
    with pytest.raises(ProviderError):
        voice_passage(fp, "one one. two two. three.", V, "en", out)
    # no output, no temp file; only the one piece that was paid for, cached
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 1 and re.fullmatch(r"p\.s01\.[0-9a-f]{10}\.seg\.wav", names[0])


# --- voice_recording ------------------------------------------------------------

def test_voice_recording_writes_passages_and_manifest(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["One. [pause] Two.", "<!-- intensity: low -->\nThree.", "Four."])
    lib = tmp_path / "lib"
    m = voice_recording(s, FakeProvider(), V, lib)
    assert m is not None
    d = lib / "rec"
    assert sorted(p.name for p in d.iterdir()) == [
        "p01.raw.json", "p01.raw.wav", "p01.wav", "p02.raw.json", "p02.raw.wav", "p02.wav",
        "p03.raw.json", "p03.raw.wav", "p03.wav", "recording.json", "voice.json"]
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
    # the failed passage's sidecar is written before its first request; no caches
    # (its one piece failed), no manifest
    assert sorted(p.name for p in d.iterdir()) == [
        "p01.raw.json", "p01.raw.wav", "p02.raw.json", "p02.raw.wav", "p03.raw.json",
        "voice.json"]
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
    x, sr = sf.read(lib / "shuf" / "p01.raw.wav", dtype="float32")
    silent = np.abs(x) < 1e-6
    edges = np.flatnonzero(np.diff(np.concatenate([[0], silent.astype(int), [0]])))
    gaps = (edges[1::2] - edges[::2]) / sr
    inner = [g for g in gaps if g > 1.0]
    assert len(inner) == 3 and all(2.0 <= g <= 3.0 for g in inner)
    # same id -> same gaps
    lib2 = tmp_path / "lib2"
    voice_recording(s, FakeProvider(), V, lib2)
    y, _ = sf.read(lib2 / "shuf" / "p01.raw.wav", dtype="float32")
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
    # STOP 2: every slot has a chosen voice
    assert set(cfg.chosen) == {voice_slot(s) for s in scripts}


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
    assert billed_chars(text, Cartesia.translate_cues, 1000) == (
        len(Cartesia.translate_cues("One. [pause] Two."))
        + len(Cartesia.translate_cues("Three [breath] four.")))
    assert billed_chars(text, ElevenLabs.translate_cues, 1000) == (
        len(ElevenLabs.translate_cues("One. [pause] Two."))
        + len(ElevenLabs.translate_cues("Three [breath] four.")))
    assert billed_chars(text, Cartesia.translate_cues, 1000) > len("One. Two.Three four.")


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
    sf.write(d / "p01.raw.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")
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


# --- source character: raw / render split -----------------------------------------

def test_raw_passage_file_name():
    assert raw_passage_file(0) == "p01.raw.wav"
    assert raw_passage_file(11) == "p12.raw.wav"


def test_manifest_records_source_character_and_rendered_file(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    m = voice_recording(s, FakeProvider(), V, tmp_path / "lib")
    assert m.source_character == "tape"
    assert read_manifest(tmp_path / "lib" / "rec" / "recording.json").source_character == "tape"
    assert [e.file for e in m.passages] == ["p01.wav", "p02.wav"]


def test_rendered_differs_from_raw_and_is_normalised(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    raw, _ = sf.read(lib / "rec" / "p01.raw.wav", dtype="float32")
    out, _ = sf.read(lib / "rec" / "p01.wav", dtype="float32")
    assert len(raw) == len(out) and not np.array_equal(raw, out)
    assert abs(speech_rms_db(out) + 24.0) < 0.5 and np.abs(out).max() <= 10 ** (-3 / 20) + 1e-6


def test_render_is_free_overwrites_render_and_keeps_raw_byte_identical(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    d = lib / "rec"
    raw_bytes = {n: (d / n).read_bytes() for n in ("p01.raw.wav", "p02.raw.wav")}
    (d / "p01.wav").write_bytes(b"stale")
    m = render_recording(s, lib)
    assert {n: (d / n).read_bytes() for n in raw_bytes} == raw_bytes
    assert (d / "p01.wav").read_bytes() != b"stale"
    assert sf.info(str(d / "p01.wav")).frames > 0
    assert read_manifest(d / "recording.json") == m
    assert sorted(p.name for p in d.iterdir()) == [
        "p01.raw.json", "p01.raw.wav", "p01.wav", "p02.raw.json", "p02.raw.wav", "p02.wav",
        "recording.json", "voice.json"]


def test_render_follows_a_changed_character(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    before = (lib / "rec" / "p01.wav").read_bytes()
    from dataclasses import replace
    m = render_recording(replace(s, source_character="room"), lib)
    assert m.source_character == "room"
    assert (lib / "rec" / "p01.wav").read_bytes() != before


def test_render_deterministic(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    a = (lib / "rec" / "p01.wav").read_bytes()
    render_character(s, lib)
    assert (lib / "rec" / "p01.wav").read_bytes() == a


def test_render_fails_clearly_without_raw_files(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    d = tmp_path / "lib" / "rec"
    d.mkdir(parents=True)
    sf.write(d / "p01.raw.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")
    with pytest.raises(FileNotFoundError, match="p02.raw.wav"):
        render_character(s, tmp_path / "lib")


def test_rendered_files_alone_do_not_imply_a_paid_voice(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    d = tmp_path / "lib" / "rec"
    d.mkdir(parents=True)
    sf.write(d / "p01.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")
    check_resume_voice(s, V, tmp_path / "lib")  # no raise


# --- final review: render edges and character_params ---------------------------

def test_rendered_file_starts_and_ends_at_silence(tmp_path):
    """Tape hiss would otherwise stop dead on the file's last sample."""
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])  # tape
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    y, sr = sf.read(lib / "rec" / "p01.wav", dtype="float32")
    assert y[-1] == 0.0 and y[0] == 0.0
    hiss = 10 ** (-52 / 20)
    # the last and first ~2 ms ramp from the hiss floor to nothing
    assert np.abs(y[-20:]).max() < hiss * 0.5
    assert np.abs(y[:20]).max() < hiss * 0.5
    assert np.abs(np.diff(y[-200:])).max() < 4 * hiss


def test_manifest_records_character_params(tmp_path):
    from sleepmix.esoterica import character
    from sleepmix.esoterica.character import character_params
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    m = voice_recording(s, FakeProvider(), V, lib)
    assert m.character_params["kind"] == "tape"
    assert m.character_params["TAPE_HISS_DB"] == character.TAPE_HISS_DB
    assert m.character_params["render_edge_s"] == voicing.RENDER_EDGE_S
    assert {k: v for k, v in m.character_params.items() if k != "render_edge_s"} \
        == character_params("tape")
    assert read_manifest(lib / "rec" / "recording.json").character_params == m.character_params


def test_retuned_character_rewrites_the_manifest(tmp_path, monkeypatch):
    from sleepmix.esoterica import character
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    first = voice_recording(s, FakeProvider(), V, lib)
    monkeypatch.setattr(character, "TAPE_HISS_DB", -60.0)
    again = render_recording(s, lib)
    assert again.character_params["TAPE_HISS_DB"] == -60.0
    assert again.made_at == first.made_at
    assert read_manifest(lib / "rec" / "recording.json").character_params["TAPE_HISS_DB"] == -60.0


def test_manifest_without_character_params_still_reads(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One."])
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    path = lib / "rec" / "recording.json"
    data = json.loads(path.read_text())
    del data["character_params"]
    path.write_text(json.dumps(data))
    assert read_manifest(path).character_params == {}


# --- final review: resume at the request, not the passage -----------------------

LONG = "Alpha one. Bravo two. Charlie three. Delta four. Echo five."


def _sent(fp):
    return [c[0] for c in fp.calls]


def test_failure_at_piece_n_rerun_bills_only_n_onwards(tmp_path):
    clean = FakeProvider()
    clean.max_chars = 15  # one sentence per request
    voice_passage(clean, LONG, V, "en", tmp_path / "clean" / "p01.raw.wav")
    pieces = _sent(clean)
    assert len(pieces) == 5

    out = tmp_path / "rec" / "p01.raw.wav"
    bad = FakeProvider(fail_when=lambda t: t.startswith("Charlie"))
    bad.max_chars = 15
    with pytest.raises(ProviderError):
        voice_passage(bad, LONG, V, "en", out)
    assert _sent(bad) == pieces[:2]
    assert not out.exists()
    assert len(voicing.segment_caches(out.parent, "p01")) == 2
    good = FakeProvider()
    good.max_chars = 15
    voice_passage(good, LONG, V, "en", out)
    assert _sent(good) == pieces[2:]  # pieces 1 and 2 were not paid for again
    # caches are dropped once the raw take is written; the take is what an
    # uninterrupted run makes, byte for byte
    assert voicing.segment_caches(out.parent) == []
    assert sorted(p.name for p in out.parent.iterdir()) == ["p01.raw.wav"]
    assert out.read_bytes() == (tmp_path / "clean" / "p01.raw.wav").read_bytes()


def test_long_pause_segments_resume_too(tmp_path):
    text = "First part. [long pause] Second part. [long pause] Third part."
    out = tmp_path / "p01.raw.wav"
    bad = FakeProvider(fail_when=lambda t: "Third" in t)
    with pytest.raises(ProviderError):
        voice_passage(bad, text, V, "en", out)
    good = FakeProvider()
    voice_passage(good, text, V, "en", out)
    assert _sent(good) == ["Third part."]


def test_shuffle_resumes_at_the_failed_image(tmp_path):
    lines = ["bright yellow", "warm rain", "une pomme verte", "sour apple"]
    s = write_script(tmp_path / "scripts", "shuffles", "shuf", ["\n".join(lines)])
    voice_recording(s, FakeProvider(), V, tmp_path / "clean")
    lib = tmp_path / "lib"
    assert voice_recording(s, FakeProvider(fail_when=lambda t: "pomme" in t), V, lib) is None
    good = FakeProvider()
    assert voice_recording(s, good, V, lib) is not None
    assert _sent(good) == ["une pomme verte", "sour apple"]
    assert ((lib / "shuf" / "p01.raw.wav").read_bytes()
            == (tmp_path / "clean" / "shuf" / "p01.raw.wav").read_bytes())


def test_a_cache_for_other_text_or_voice_is_not_reused(tmp_path):
    out = tmp_path / "p01.raw.wav"
    bad = FakeProvider(fail_when=lambda t: "Bravo" in t)
    bad.max_chars = 15
    with pytest.raises(ProviderError):
        voice_passage(bad, "Alpha one. Bravo two.", V, "en", out)
    other_voice = FakeProvider()
    other_voice.max_chars = 15
    voice_passage(other_voice, "Alpha one. Bravo two.", Voice("fake", "m", "v2"), "en",
                  tmp_path / "x" / "p01.raw.wav")
    edited = FakeProvider()
    edited.max_chars = 15
    voice_passage(edited, "Alpha won. Bravo two.", V, "en", out)
    assert _sent(edited) == ["Alpha won.", "Bravo two."]
    assert voicing.segment_caches(tmp_path) == []  # the stale piece is cleaned up too


def test_remaining_estimate_counts_only_uncached_pieces(tmp_path, monkeypatch):
    from sleepmix.esoterica import cli as ecli
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["Alpha one. Bravo two. Charlie three.", "Delta four."])
    cfg = load_voices(VOICES)
    cfg.providers["fake"] = {"model": "m", "price_per_char": 0.0, "max_chars": 15}
    monkeypatch.setitem(ecli.PROVIDERS, "fake", FakeProvider())  # only translate_cues is used
    lib = tmp_path / "lib"
    assert ecli._remaining(s, lib, V, cfg) == len("Alpha one.Bravo two.Charlie three.Delta four.")
    bad = FakeProvider(fail_when=lambda t: "Charlie" in t)
    bad.max_chars = 15
    assert voice_recording(s, bad, V, lib) is None
    assert ecli._remaining(s, lib, V, cfg) == len("Charlie three.Delta four.")


# --- final review: an unused voice.json binds nothing -----------------------------

def test_voice_json_without_paid_audio_is_not_binding(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One fails.", "Two."])
    lib = tmp_path / "lib"
    assert voice_recording(s, FakeProvider(fail_when=lambda t: "One" in t), V, lib) is None
    assert json.loads((lib / "rec" / "voice.json").read_text())["voice_id"] == "v1"
    assert not voicing.paid_audio(lib / "rec")
    v2 = Voice("fake", "m", "v2")
    check_resume_voice(s, v2, lib)  # nothing paid: no refusal
    assert voice_recording(s, FakeProvider(), v2, lib) is not None
    assert json.loads((lib / "rec" / "voice.json").read_text())["voice_id"] == "v2"


def test_voice_json_with_only_a_piece_cache_binds(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["Alpha one. Bravo two."])
    lib = tmp_path / "lib"
    bad = FakeProvider(fail_when=lambda t: "Bravo" in t)
    bad.max_chars = 15
    assert voice_recording(s, bad, V, lib) is None
    assert voicing.raw_takes(lib / "rec") == [] and voicing.paid_audio(lib / "rec")
    with pytest.raises(VoiceMismatchError):
        check_resume_voice(s, Voice("fake", "m", "v2"), lib)


# --- final review: stale-script guard --------------------------------------------

from sleepmix.esoterica.voicing import StaleTakesError, check_takes, take_sidecar_file  # noqa: E402


def _voiced(tmp_path, passages, id="rec"):
    s = write_script(tmp_path / "scripts", "testimonies", id, passages)
    lib = tmp_path / "lib"
    assert voice_recording(s, FakeProvider(), V, lib) is not None
    return s, lib


def test_voicing_writes_a_sidecar_per_take(tmp_path):
    s, lib = _voiced(tmp_path, ["One. [pause] Two.", "Three."])
    assert take_sidecar_file(0) == "p01.raw.json"
    side = json.loads((lib / "rec" / "p01.raw.json").read_text())
    import hashlib
    assert side["index"] == 0
    assert side["text_sha256"] == hashlib.sha256("One. [pause] Two.".encode()).hexdigest()
    assert (side["provider"], side["model"], side["voice_id"]) == ("fake", "m", "v1")
    assert (lib / "rec" / "p02.raw.json").exists()


def test_unchanged_script_is_current(tmp_path):
    s, lib = _voiced(tmp_path, ["One.", "Two."])
    assert check_takes(s, lib) == ({}, [])
    render_recording(s, lib)  # no raise
    fp = FakeProvider()
    voice_recording(s, fp, V, lib)
    assert fp.calls == []


def test_edited_passage_is_refused_by_name(tmp_path):
    s, lib = _voiced(tmp_path, ["One.", "Two.", "Three."])
    edited = write_script(tmp_path / "scripts", "testimonies", "rec",
                          ["One.", "Two, changed.", "Three."])
    stale, _ = check_takes(edited, lib)
    assert list(stale) == ["p02"]
    before = (lib / "rec" / "recording.json").read_bytes()
    with pytest.raises(StaleTakesError, match=r"rec.*p02.*--revoice p02"):
        render_recording(edited, lib)
    assert (lib / "rec" / "recording.json").read_bytes() == before
    fp = FakeProvider()
    with pytest.raises(StaleTakesError, match="p02"):
        voice_recording(edited, fp, V, lib)
    assert fp.calls == []


def test_a_cue_only_edit_is_stale_too(tmp_path):
    s, lib = _voiced(tmp_path, ["One. Two."])
    edited = write_script(tmp_path / "scripts", "testimonies", "rec", ["One. [pause] Two."])
    assert list(check_takes(edited, lib)[0]) == ["p01"]


def test_inserted_passage_shifts_indexes_and_is_refused(tmp_path):
    s, lib = _voiced(tmp_path, ["One.", "Two."])
    edited = write_script(tmp_path / "scripts", "testimonies", "rec",
                          ["One.", "New.", "Two."])
    stale, _ = check_takes(edited, lib)
    assert list(stale) == ["p02"]  # p03 has no take yet; p02's take is "Two."
    with pytest.raises(StaleTakesError, match="p02"):
        voice_recording(edited, FakeProvider(), V, lib)


def test_removed_passage_leaves_an_orphan_take_that_is_refused(tmp_path):
    s, lib = _voiced(tmp_path, ["One.", "Two.", "Three."])
    edited = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    stale, _ = check_takes(edited, lib)
    assert list(stale) == ["p03"] and "no passage 3" in stale["p03"]
    with pytest.raises(StaleTakesError, match="p03"):
        render_recording(edited, lib)


def test_backfill_from_a_matching_manifest(tmp_path):
    s, lib = _voiced(tmp_path, ["One. [pause] Two.", "Three."])
    d = lib / "rec"
    for f in d.glob("*.raw.json"):
        f.unlink()  # a recording voiced before sidecars existed
    stale, backfill = check_takes(s, lib)
    assert stale == {} and [p.index for p in backfill] == [0, 1]
    raws = {p.name: p.read_bytes() for p in d.glob("*.raw.wav")}
    render_recording(s, lib)
    side = json.loads((d / "p01.raw.json").read_text())
    assert side["backfilled"] is True and side["voice_id"] == "v1"
    assert check_takes(s, lib) == ({}, [])
    assert {p.name: p.read_bytes() for p in d.glob("*.raw.wav")} == raws


def test_no_sidecar_and_a_mismatched_manifest_is_stale(tmp_path):
    s, lib = _voiced(tmp_path, ["One.", "Two."])
    d = lib / "rec"
    for f in d.glob("*.raw.json"):
        f.unlink()
    edited = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two again."])
    stale, backfill = check_takes(edited, lib)
    assert list(stale) == ["p02"] and [p.index for p in backfill] == [0]
    with pytest.raises(StaleTakesError):
        render_recording(edited, lib)
    assert not (d / "p01.raw.json").exists()  # a refused render writes nothing


def test_missing_raw_error_names_the_files(tmp_path):
    from sleepmix.esoterica.voicing import MissingRawError
    s = write_script(tmp_path / "scripts", "testimonies", "rec", ["One.", "Two."])
    d = tmp_path / "lib" / "rec"
    d.mkdir(parents=True)
    sf.write(d / "p01.raw.wav", np.zeros(100, np.float32), 44100, subtype="FLOAT")
    with pytest.raises(MissingRawError) as e:
        render_recording(s, tmp_path / "lib")
    assert e.value.missing == ["p02.raw.wav"]


# --- pace: speed (provider) and pause_stretch (render) -----------------------------

from dataclasses import replace as _replace  # noqa: E402

from sleepmix.esoterica.voicing import piece_cache, stretch_pauses  # noqa: E402


def test_sidecar_records_speed_and_a_speed_change_is_stale(tmp_path):
    s, lib = _voiced(tmp_path, ["One.", "Two."])
    assert json.loads((lib / "rec" / "p01.raw.json").read_text())["speed"] is None
    slow = _replace(s, speed=0.7)
    stale, _ = check_takes(slow, lib)
    assert list(stale) == ["p01", "p02"]
    assert "speed" in stale["p01"]
    fp = FakeProvider()
    with pytest.raises(StaleTakesError, match="--revoice p01"):
        voice_recording(slow, fp, V, lib)
    assert fp.calls == []


def test_a_take_voiced_at_a_speed_is_current_at_that_speed(tmp_path):
    s = _replace(write_script(tmp_path / "scripts", "testimonies", "rec", ["One."]),
                 speed=0.7)
    lib = tmp_path / "lib"
    voice_recording(s, FakeProvider(), V, lib)
    assert json.loads((lib / "rec" / "p01.raw.json").read_text())["speed"] == 0.7
    assert check_takes(s, lib) == ({}, [])


def test_a_cache_at_another_speed_is_not_reused(tmp_path):
    from sleepmix.esoterica.voicing import Piece
    pc = Piece("Alpha.", "en", 0.0)
    out = tmp_path / "p01.raw.wav"
    assert piece_cache(out, 0, pc, V) == piece_cache(out, 0, pc, V, speed=None)
    assert piece_cache(out, 0, pc, V, speed=0.7) != piece_cache(out, 0, pc, V)


def _speech_and_gaps(sr=44100):
    t = tone(0.5)  # 0.5 s of "speech"
    gap = np.zeros(int(0.4 * sr), dtype=np.float32)
    lead = np.zeros(int(0.1 * sr), dtype=np.float32)
    return np.concatenate([lead, t, gap, t, gap, t, lead]), len(t), len(gap), len(lead)


def test_stretch_pauses_lengthens_inner_gaps_only():
    x, n_t, n_gap, n_lead = _speech_and_gaps()
    y = stretch_pauses(x, 44100, 2.0)
    assert abs(len(y) - (len(x) + 2 * n_gap)) < 0.05 * 44100  # each inner gap doubled (to a frame)
    assert stretch_pauses(x, 44100, 1.0) is x
    # the speech itself is untouched: same energy, same samples in order
    loud = lambda a: a[np.abs(a) > 1e-3]
    assert np.array_equal(loud(y), loud(x))


def test_stretch_pauses_leaves_short_gaps_between_words():
    t = tone(0.5)
    short = np.zeros(int(0.06 * 44100), dtype=np.float32)
    x = np.concatenate([t, short, t])
    assert len(stretch_pauses(x, 44100, 3.0)) == len(x)


def test_render_applies_pause_stretch_and_records_it(tmp_path):
    s = write_script(tmp_path / "scripts", "testimonies", "rec",
                     ["One. [long pause] Two."])
    lib = tmp_path / "lib"
    m = voice_recording(s, FakeProvider(), V, lib)
    plain = m.passages[0].duration_s
    assert "pause_stretch" not in m.character_params
    raw = (lib / "rec" / "p01.raw.wav").read_bytes()
    m2 = render_recording(_replace(s, pause_stretch=2.0), lib)
    assert m2.passages[0].duration_s > plain + 2.5  # the 3 s long pause roughly doubled
    assert m2.character_params["pause_stretch"] == 2.0
    assert (lib / "rec" / "p01.raw.wav").read_bytes() == raw


def test_delivery_tag_prefixes_every_request_and_is_recorded(tmp_path):
    s = _replace(write_script(tmp_path / "scripts", "testimonies", "rec",
                              ["One. [long pause] Two.", "Three."]),
                 delivery="[slowly]")
    fp = FakeProvider()
    lib = tmp_path / "lib"
    voice_recording(s, fp, V, lib)
    assert [c[0] for c in fp.calls] == ["[slowly] One.", "[slowly] Two.", "[slowly] Three."]
    assert json.loads((lib / "rec" / "p01.raw.json").read_text())["delivery"] == "[slowly]"
    assert check_takes(s, lib) == ({}, [])
    stale, _ = check_takes(_replace(s, delivery=None), lib)
    assert "delivery" in stale["p01"]


def test_a_cache_with_another_delivery_is_not_reused(tmp_path):
    from sleepmix.esoterica.voicing import Piece
    pc = Piece("Alpha.", "en", 0.0)
    out = tmp_path / "p01.raw.wav"
    assert piece_cache(out, 0, pc, V, delivery="[slowly]") != piece_cache(out, 0, pc, V)


def test_delivery_counts_in_the_estimate(tmp_path):
    from sleepmix.esoterica.voicing import Piece, uncached_chars
    pieces = [Piece("Alpha.", "en", 0.0), Piece("Bravo.", "en", 3.0)]
    out = tmp_path / "p01.raw.wav"
    plain = uncached_chars(pieces, out, V, lambda t: t)
    assert uncached_chars(pieces, out, V, lambda t: t, delivery="[slowly]") == plain + 2 * 9


def test_delivery_is_refused_for_a_provider_that_would_speak_it(tmp_path):
    s = _replace(write_script(tmp_path / "scripts", "testimonies", "rec", ["One."]),
                 delivery="[slowly]")
    fp = FakeProvider()
    with pytest.raises(ValueError, match="delivery"):
        voice_recording(s, fp, Voice("cartesia", "sonic-3.6", "x"), tmp_path / "lib")
    assert fp.calls == []
