"""Text-to-speech providers for Esoterica: ElevenLabs and Cartesia.

Both take an injected `requests.Session` (tests pass a fake; nothing here opens
its own connection) and return mono float32 samples plus a sample rate.

Secrets: the key is sent in a per-request header and is never put in a log
line, a repr, or an exception. Error messages are built from the status code
and a short, redacted excerpt of the response body only, never from the
request, its headers, or a chained exception.

API details were read from the providers' live docs on 2026-11-03; the Task 3
report has the sources.
"""
from __future__ import annotations

import json
import re
from typing import Protocol

import numpy as np
import requests

TIMEOUT = (10, 300)  # connect, read (seconds); a long passage takes a while
_TOKENISH = re.compile(r"(Bearer\s+\S+|\bsk[_-][A-Za-z0-9_\-]{4,}|xi-api-key\S*\s*\S+)", re.I)


class ProviderError(RuntimeError):
    """A failed synthesis. The message never contains an API key."""


class Provider(Protocol):
    name: str
    max_chars: int

    def synthesize(self, text: str, voice_id: str, model: str,
                   language: str) -> tuple[np.ndarray, int]: ...

    def translate_cues(self, text: str) -> str: ...


def api_language(language: str) -> str:
    """Script language -> ISO 639-1 for the provider ('en+invented' is English)."""
    return "fr" if language == "fr" else "en"


def _translate(text: str, table: dict[str, str]) -> str:
    for cue, form in table.items():
        text = text.replace(cue, form)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


class _Base:
    name = ""
    max_chars = 0
    SUPPORTED_TAGS: frozenset[str] = frozenset()
    CUE_FORMS: dict[str, str] = {}

    def __init__(self, api_key: str, session: requests.Session,
                 settings: dict | None = None):
        self._key = api_key
        self._session = session
        self.settings = {**self.DEFAULT_SETTINGS, **(settings or {})}

    def __repr__(self) -> str:  # never show the key
        return f"{type(self).__name__}(settings={self.settings!r})"

    def translate_cues(self, text: str) -> str:
        # [long pause] first so "[pause]" can't match inside it (it can't, but
        # the order makes the table read top to bottom).
        return _translate(text, self.CUE_FORMS)

    def _redact(self, s: str) -> str:
        if self._key:
            s = s.replace(self._key, "***")
        return _TOKENISH.sub("***", s)

    def _post(self, url: str, *, params=None, body: dict, headers: dict) -> bytes:
        try:
            r = self._session.post(url, params=params, json=body, headers=headers,
                                   timeout=TIMEOUT)
        except requests.RequestException as e:
            # Deliberately no `from e`: a requests exception can carry the
            # request (and so the headers) in its args or attributes.
            raise ProviderError(f"{self.name}: request failed "
                                f"({type(e).__name__})") from None
        if not (200 <= r.status_code < 300):
            raise ProviderError(f"{self.name}: HTTP {r.status_code}"
                                f"{self._detail(r)}") from None
        if not r.content:
            raise ProviderError(f"{self.name}: empty audio in the response") from None
        return r.content

    def _detail(self, r) -> str:
        """A short, redacted reason from an error body (a message, not the body)."""
        try:
            data = json.loads(r.content.decode("utf-8", errors="replace"))
        except ValueError:
            return ""
        msg = None
        if isinstance(data, dict):
            d = data.get("detail", data)
            if isinstance(d, dict):
                msg = d.get("message") or d.get("status") or d.get("code")
            elif isinstance(d, str):
                msg = d
            if msg is None:
                msg = data.get("message") or data.get("error")
        if not isinstance(msg, str) or not msg:
            return ""
        return f" ({self._redact(msg)[:200]})"


class ElevenLabs(_Base):
    """ElevenLabs text-to-speech, raw PCM.

    POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
    Model `eleven_v4` ("our most emotive"): 10,000 characters per request,
    French, audio tags in square brackets, no SSML breaks (pauses come from
    ellipses). Live /v1/models reports no style or speaker-boost control for
    v4, so only stability, similarity and speed are sent.
    """

    name = "elevenlabs"
    max_chars = 10000
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    # pcm_44100 needs the Pro tier; 24 kHz S16LE works on every paid tier and
    # voicing resamples to 44.1 kHz anyway.
    OUTPUT_FORMAT = "pcm_24000"
    SAMPLE_RATE = 24000
    DEFAULT_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "speed": 0.85}
    SUPPORTED_TAGS = frozenset({"[whispers]", "[exhales]", "[laughs]", "[softly]"})
    CUE_FORMS = {
        "[long pause]": "… …",  # voicing splits on it first; a fallback only
        "[pause]": "…",
        "[breath]": "[exhales]",
        "[softly]": "[softly]",
        "[whisper]": "[whispers]",
        "[laughs quietly]": "[laughs]",
    }

    def synthesize(self, text, voice_id, model, language):
        body = {
            "text": self.translate_cues(text),
            "model_id": model,
            "language_code": api_language(language),
            "voice_settings": {k: self.settings[k] for k in
                               ("stability", "similarity_boost", "speed")},
        }
        raw = self._post(self.URL.format(voice_id=voice_id),
                         params={"output_format": self.OUTPUT_FORMAT}, body=body,
                         headers={"xi-api-key": self._key,
                                  "Content-Type": "application/json"})
        if len(raw) % 2:
            raw = raw[:-1]
        audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if audio.size == 0:
            raise ProviderError(f"{self.name}: empty audio in the response")
        return audio, self.SAMPLE_RATE


class Cartesia(_Base):
    """Cartesia Sonic text-to-speech, raw float32 PCM at 44.1 kHz.

    POST https://api.cartesia.ai/tts/bytes, Cartesia-Version 2026-08-14.
    `<break time="…"/>` for pauses and `[laughter]` are supported; there is no
    whisper or breath control, so those cues are stripped. `emotion` is
    documented as English-only, so it is left out for French.
    """

    name = "cartesia"
    max_chars = 1000  # PLACEHOLDER: the docs give no transcript limit
    URL = "https://api.cartesia.ai/tts/bytes"
    VERSION = "2026-08-14"
    SAMPLE_RATE = 44100
    DEFAULT_SETTINGS = {"speed": 0.8, "emotion": "calm"}
    SUPPORTED_TAGS = frozenset({"[laughter]"})
    CUE_FORMS = {
        "[long pause]": '<break time="3s"/>',
        "[pause]": '<break time="1s"/>',
        "[breath]": "",
        "[softly]": "",
        "[whisper]": "",
        "[laughs quietly]": "[laughter]",
    }

    def synthesize(self, text, voice_id, model, language):
        lang = api_language(language)
        gen = {"speed": self.settings["speed"]}
        if lang == "en" and self.settings.get("emotion"):
            gen["emotion"] = self.settings["emotion"]
        body = {
            "model_id": model,
            "transcript": self.translate_cues(text),
            "voice": {"id": voice_id},
            "language": lang,
            "output_format": {"container": "raw", "encoding": "pcm_f32le",
                              "sample_rate": self.SAMPLE_RATE},
            "generation_config": gen,
        }
        raw = self._post(self.URL, body=body,
                         headers={"Authorization": f"Bearer {self._key}",
                                  "Cartesia-Version": self.VERSION,
                                  "Content-Type": "application/json"})
        raw = raw[: len(raw) // 4 * 4]
        audio = np.frombuffer(raw, dtype="<f4").astype(np.float32)
        if audio.size == 0:
            raise ProviderError(f"{self.name}: empty audio in the response")
        return audio, self.SAMPLE_RATE
