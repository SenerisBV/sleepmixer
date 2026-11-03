import logging
import re

import numpy as np
import pytest
import requests

from sleepmix.esoterica.providers import Cartesia, ElevenLabs, ProviderError
from sleepmix.esoterica.script import CUES

from .fakes import FakeResponse, FakeSession, pcm_f32, pcm_s16, tone

KEY = "sk-TESTSECRET123"
ALL_CUES = "a [pause] b [long pause] c [breath] d [softly] e [whisper] f [laughs quietly] g."


def ok_f32(call):
    return FakeResponse(200, pcm_f32(tone(0.3)), {"Content-Type": "audio/pcm"})


def ok_s16(call):
    return FakeResponse(200, pcm_s16(tone(0.3, sr=24000)), {"Content-Type": "audio/pcm"})


# --- ElevenLabs -----------------------------------------------------------------

def test_elevenlabs_request_shape_and_decode():
    s = FakeSession(ok_s16)
    p = ElevenLabs(KEY, s)
    audio, sr = p.synthesize("hello there.", "voice123", "eleven_v4", "en+invented")
    assert sr == 24000
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert len(audio) == len(tone(0.3, sr=24000))
    assert np.max(np.abs(audio)) < 1.0
    (call,) = s.calls
    assert call["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice123"
    assert call["params"]["output_format"] == "pcm_24000"
    assert call["headers"]["xi-api-key"] == KEY
    body = call["json"]
    assert body["text"] == "hello there."
    assert body["model_id"] == "eleven_v4"
    assert "language_code" not in body  # only sent for French
    vs = body["voice_settings"]
    assert set(vs) == {"stability", "similarity_boost", "speed"}  # v4: no style / speaker boost
    assert 0.7 <= vs["speed"] < 1.0
    assert call["timeout"] is not None


def test_elevenlabs_french_language_code():
    s = FakeSession(ok_s16)
    ElevenLabs(KEY, s).synthesize("bonjour.", "v", "eleven_v4", "fr")
    assert s.calls[0]["json"]["language_code"] == "fr"


def test_elevenlabs_settings_override():
    s = FakeSession(ok_s16)
    ElevenLabs(KEY, s, settings={"stability": 0.0, "speed": 0.8}).synthesize(
        "x.", "v", "eleven_v4", "en")
    vs = s.calls[0]["json"]["voice_settings"]
    assert vs["stability"] == 0.0 and vs["speed"] == 0.8


# --- Cartesia -------------------------------------------------------------------

def test_cartesia_request_shape_and_decode():
    s = FakeSession(ok_f32)
    p = Cartesia(KEY, s)
    audio, sr = p.synthesize("hello there.", "uuid-1", "sonic-3.6", "en")
    assert sr == 44100
    assert audio.dtype == np.float32
    np.testing.assert_allclose(audio, tone(0.3), atol=1e-7)
    (call,) = s.calls
    assert call["url"] == "https://api.cartesia.ai/tts/bytes"
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert call["headers"]["Cartesia-Version"] == "2026-08-14"
    body = call["json"]
    assert body["model_id"] == "sonic-3.6"
    assert body["transcript"] == "hello there."
    assert body["voice"] == {"id": "uuid-1"}
    assert body["language"] == "en"
    assert body["output_format"] == {"container": "raw", "encoding": "pcm_f32le",
                                     "sample_rate": 44100}
    gc = body["generation_config"]
    assert 0.6 <= gc["speed"] < 1.0
    assert gc["emotion"] == "calm"


def test_cartesia_french_omits_emotion():
    s = FakeSession(ok_f32)
    Cartesia(KEY, s).synthesize("bonjour.", "v", "sonic-3.6", "fr")
    body = s.calls[0]["json"]
    assert body["language"] == "fr"
    assert "emotion" not in body["generation_config"]


# --- Errors and the key ---------------------------------------------------------

def echo_401(call):
    # A hostile server echoing the request headers back in the body.
    body = ('{"detail": {"message": "invalid api key", "headers": %s}}'
            % repr(call["headers"]).replace("'", '"'))
    return FakeResponse(401, body.encode(), {"Content-Type": "application/json"})


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_key_never_leaks_in_error_or_logs(cls, caplog):
    caplog.set_level(logging.DEBUG)
    p = cls(KEY, FakeSession(echo_401))
    with pytest.raises(ProviderError) as e:
        p.synthesize("hello.", "v", "m", "en")
    msg = str(e.value)
    assert "401" in msg
    assert "TESTSECRET" not in msg
    assert "TESTSECRET" not in repr(e.value)
    assert "TESTSECRET" not in caplog.text
    assert e.value.__cause__ is None
    assert e.value.__context__ is None


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
@pytest.mark.parametrize("status", [429, 500])
def test_http_errors_raise_provider_error(cls, status):
    p = cls(KEY, FakeSession(lambda c: FakeResponse(status, b'{"detail": "busy"}')))
    with pytest.raises(ProviderError, match=str(status)):
        p.synthesize("hello.", "v", "m", "en")


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_timeout_raises_provider_error_without_key(cls):
    def boom(call):
        raise requests.Timeout(f"read timed out; headers={call['headers']}")
    p = cls(KEY, FakeSession(boom))
    with pytest.raises(ProviderError) as e:
        p.synthesize("hello.", "v", "m", "en")
    assert "TESTSECRET" not in str(e.value)
    assert e.value.__cause__ is None
    assert e.value.__context__ is None  # the requests exception is not reachable


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_empty_audio_is_an_error(cls):
    p = cls(KEY, FakeSession(lambda c: FakeResponse(200, b"")))
    with pytest.raises(ProviderError, match="empty"):
        p.synthesize("hello.", "v", "m", "en")


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_repr_hides_key(cls):
    p = cls(KEY, FakeSession(ok_f32))
    assert "TESTSECRET" not in repr(p)
    assert "TESTSECRET" not in str(vars(p).get("name", ""))


# --- Cue translation ------------------------------------------------------------

@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_every_cue_translated_or_stripped(cls):
    p = cls(KEY, FakeSession(ok_f32))
    for cue in CUES:
        out = p.translate_cues(f"before {cue} after.")
        for tag in re.findall(r"\[[^\]]*\]", out):
            assert tag in cls.SUPPORTED_TAGS, (cue, out)
        assert "before" in out and "after." in out
        assert "  " not in out
    out = p.translate_cues(ALL_CUES)
    assert set(re.findall(r"\[[^\]]*\]", out)) <= cls.SUPPORTED_TAGS


def test_elevenlabs_cue_forms():
    p = ElevenLabs(KEY, FakeSession(ok_s16))
    assert p.translate_cues("a [whisper] b") == "a [whispers] b"
    assert p.translate_cues("a [laughs quietly] b") == "a [laughs] b"
    assert p.translate_cues("a [breath] b") == "a [exhales] b"
    assert p.translate_cues("a [softly] b") == "a [softly] b"
    assert p.translate_cues("a. [pause] b") == "a. … b"
    assert "<break" not in p.translate_cues("a [long pause] b")  # v4: no SSML breaks


def test_cartesia_cue_forms():
    p = Cartesia(KEY, FakeSession(ok_f32))
    assert p.translate_cues("a. [pause] b") == 'a. <break time="1s"/> b'
    assert p.translate_cues("a. [long pause] b") == 'a. <break time="3s"/> b'
    assert p.translate_cues("a [laughs quietly] b") == "a [laughter] b"
    assert p.translate_cues("a [whisper] b") == "a b"
    assert p.translate_cues("a [breath] b") == "a b"
    assert p.translate_cues("a [softly] b") == "a b"


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_synthesize_never_sends_a_neutral_unsupported_cue(cls):
    """synthesize translates on its own, so a raw neutral cue never reaches the wire."""
    s = FakeSession(ok_f32 if cls is Cartesia else ok_s16)
    cls(KEY, s).synthesize(ALL_CUES, "v", "m", "en")
    sent = s.calls[0]["json"].get("text") or s.calls[0]["json"].get("transcript")
    assert set(re.findall(r"\[[^\]]*\]", sent)) <= cls.SUPPORTED_TAGS
    assert "[pause]" not in sent and "[whisper]" not in sent


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
@pytest.mark.parametrize("ctype", ["application/json", "application/json; charset=utf-8",
                                   "text/html", "text/plain"])
def test_2xx_non_audio_is_rejected_without_echo(cls, ctype):
    body = b'{"warning": "sk-TESTSECRET123 something odd"}'
    p = cls(KEY, FakeSession(lambda c: FakeResponse(200, body, {"Content-Type": ctype})))
    with pytest.raises(ProviderError, match="not audio") as e:
        p.synthesize("hello.", "v", "m", "en")
    assert "TESTSECRET" not in str(e.value) and "warning" not in str(e.value)


@pytest.mark.parametrize("cls", [ElevenLabs, Cartesia])
def test_translate_cues_needs_no_instance_or_key(cls):
    assert cls.translate_cues("a [laughs quietly] b") == cls(KEY, FakeSession(ok_f32)).translate_cues(
        "a [laughs quietly] b")
