"""Offline fakes for provider HTTP sessions and providers. Never the network."""
from __future__ import annotations

import json

import numpy as np

SR = 44100
# A 220 Hz sine at -24 dBFS RMS: a modest crest factor so the loudness target
# and the -3 dBFS peak cap can both hold.
AMP = 10 ** (-24 / 20) * np.sqrt(2)


def tone(seconds: float = 0.5, sr: int = SR, freq: float = 220.0) -> np.ndarray:
    """A sine that starts at zero and ends near a crest (not a zero-crossing),
    so a butt-join without fades would click."""
    n = int(seconds * sr)
    # choose the length so the last sample sits at the crest
    period = sr / freq
    n = int(round((np.floor(n / period) + 0.25) * period))
    t = np.arange(n) / sr
    return (AMP * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Records every post; returns canned responses from `responder(call)`."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []

    def post(self, url, params=None, json=None, headers=None, timeout=None, **kw):
        call = {"url": url, "params": params, "json": json,
                "headers": dict(headers or {}), "timeout": timeout}
        self.calls.append(call)
        return self.responder(call)


def pcm_f32(x: np.ndarray) -> bytes:
    return np.asarray(x, dtype="<f4").tobytes()


def pcm_s16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


class FakeProvider:
    """A Provider that returns `tone()` per call and can fail on demand."""

    name = "fake"
    max_chars = 200

    def __init__(self, fail_when=None):
        self.calls: list[tuple[str, str, str, str]] = []
        self.fail_when = fail_when  # callable(text) -> bool

    def translate_cues(self, text: str) -> str:
        import re
        return re.sub(r"\[[^\]]*\]", "", text)

    def synthesize(self, text, voice_id, model, language):
        from sleepmix.esoterica.providers import ProviderError
        if self.fail_when and self.fail_when(text):
            raise ProviderError("fake: HTTP 500 (server error)")
        self.calls.append((text, voice_id, model, language))
        return tone(0.4), SR
