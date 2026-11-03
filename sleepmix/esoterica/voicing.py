"""Voice Esoterica scripts: chunk, synthesize, join, normalise, write WAVs.

On disk a recording is `<library>/<id>/p01.wav, p02.wav, …` (1-based, from
the passage's 0-based `index`) plus `recording.json`, written only once every
passage exists. Every passage is mono float32 at 44100 Hz, normalised to
-24 dBFS RMS over speech frames with peaks limited to -3 dBFS (placeholders).

Resumable by construction: a passage whose WAV exists is never sent again, and
each WAV is written to a temp file and renamed, so an interrupted write never
leaves a file that a rerun would mistake for finished work.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import gcd
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
import yaml
from scipy.ndimage import minimum_filter1d
from scipy.signal import resample_poly

from .manifest import Manifest, PassageEntry, read_manifest, write_manifest
from .providers import Provider, ProviderError
from .script import Script, spoken_text

log = logging.getLogger(__name__)

SR = 44100
PER_RECORDING_SHOWS = frozenset({"testimonies", "addresses"})

# PLACEHOLDERS (recorded in docs/project-state.md)
CHUNK_GAP_S = 0.25         # silence between chunks of one passage
EDGE_S = 0.010             # raised-cosine fade at each chunk edge
LONG_PAUSE_S = 3.0         # a [long pause] (README: two to four seconds)
SHUFFLE_GAP_S = (2.0, 3.0) # silence between shuffle images
TARGET_RMS_DB = -24.0      # over speech-active frames
GATE_DB = -50.0            # a frame above this is speech-active
PEAK_DB = -3.0             # peak ceiling
FRAME_S = 0.02             # loudness frame length
LIMIT_WINDOW_S = 0.005     # limiter gain-smoothing window

_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'”’)]*\s+")
_TOKEN = re.compile(r"<[^>]*>|\[[^\]]*\]|\S+")
_LONG_PAUSE = re.compile(r"\s*\[long pause\]\s*")
_FRENCH_LINE = re.compile(r"^(?:(?:le|la|les|un|une|des|du|au|aux)\s|l['’])", re.I)


@dataclass(frozen=True)
class Voice:
    provider: str
    model: str
    voice_id: str


@dataclass
class VoicesConfig:
    providers: dict[str, dict]
    candidates: dict[str, dict[str, list[dict]]]
    chosen: dict[str, dict] = field(default_factory=dict)

    def voice_for(self, slot: str) -> Voice | None:
        c = self.chosen.get(slot)
        return Voice(c["provider"], c["model"], c["voice_id"]) if c else None


def voice_slot(script: Script) -> str:
    """The recording id for a show of different people, else the show."""
    return script.id if script.show in PER_RECORDING_SHOWS else script.show


def load_voices(path: Path) -> VoicesConfig:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers = data.get("providers") or {}
    candidates = data.get("candidates") or {}
    chosen = data.get("chosen") or {}
    for name, p in providers.items():
        for key in ("model", "price_per_char", "max_chars"):
            if key not in (p or {}):
                raise ValueError(f"{path}: providers.{name} is missing '{key}'")
    for slot, c in chosen.items():
        if not isinstance(c, dict) or not all(c.get(k) for k in
                                              ("provider", "model", "voice_id")):
            raise ValueError(f"{path}: chosen.{slot} needs provider, model and voice_id")
        if c["provider"] not in providers:
            raise ValueError(f"{path}: chosen.{slot} names unknown provider "
                             f"'{c['provider']}'")
    return VoicesConfig(providers=providers, candidates=candidates, chosen=chosen)


def check_distinct_voices(chosen: dict[str, dict], scripts: list[Script]) -> None:
    """No two testimony/address slots may share a chosen voice."""
    per_recording = {s.id for s in scripts if s.show in PER_RECORDING_SHOWS}
    seen: dict[tuple[str, str], str] = {}
    for slot in sorted(chosen):
        if slot not in per_recording:
            continue
        key = (chosen[slot]["provider"], chosen[slot]["voice_id"])
        if key in seen:
            raise ValueError(f"voices.yaml: {seen[key]} and {slot} share voice "
                             f"{key[1]}; every testimony and address needs its own")
        seen[key] = slot


# --- text ---------------------------------------------------------------------

def chunk(text: str, max_chars: int, measure: Callable[[str], int] = len) -> list[str]:
    """Split at sentence boundaries into pieces of at most max_chars.

    `measure` is how a piece is sized: pass the provider's translated length
    (`lambda t: len(provider.translate_cues(t))`) so the limit applies to what
    is actually sent, not to the neutral text. A single sentence longer than
    max_chars is hard-split at word boundaries (a bracket cue or an <…/> tag
    counts as one word and is never cut).
    """
    text = text.strip()
    if not text:
        return []
    if measure(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    for sent in _SENTENCE_END.split(text):
        sent = sent.strip()
        if not sent:
            continue
        if measure(sent) <= max_chars:
            pieces.append(sent)
            continue
        cur = ""
        for tok in _TOKEN.findall(sent):
            cand = f"{cur} {tok}" if cur else tok
            if cur and measure(cand) > max_chars:
                pieces.append(cur)
                cur = tok
            else:
                cur = cand
        if cur:
            pieces.append(cur)
    # greedily pack whole sentences back together
    out: list[str] = []
    for p in pieces:
        if out and measure(f"{out[-1]} {p}") <= max_chars:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def billed_chars(text: str, translate: Callable[[str], str]) -> int:
    """Characters a provider is sent for one passage's neutral text: split at
    `[long pause]` (never sent), each segment counted after cue translation."""
    return sum(len(translate(seg)) for seg in _LONG_PAUSE.split(text) if seg.strip())


def shuffle_billed_chars(lines: list[str], translate: Callable[[str], str]) -> int:
    """Characters sent for a shuffle burst (one request per image)."""
    return sum(len(translate(ln)) for ln in lines)


def split_sentences(text: str) -> list[str]:
    """Sentences of `text` (split after . ! ? or …, plus any closing quote)."""
    return [s.strip() for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def line_language(line: str, default: str) -> str:
    """A shuffle line that opens with a French article is French."""
    return "fr" if _FRENCH_LINE.match(line.strip()) else default


# --- audio --------------------------------------------------------------------

def _to_sr(x: np.ndarray, sr: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        g = gcd(SR, sr)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def _edges(x: np.ndarray) -> np.ndarray:
    n = min(int(EDGE_S * SR), len(x) // 2)
    if n < 1:
        return x
    ramp = (0.5 * (1 - np.cos(np.pi * np.arange(n) / n))).astype(np.float32)
    x = x.copy()
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    x[-1] = 0.0
    x[0] = 0.0
    return x


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(round(seconds * SR)), dtype=np.float32)


def _speech_rms_db(x: np.ndarray) -> float | None:
    n = int(FRAME_S * SR)
    if len(x) < n:
        frames = x[None, :].astype(np.float64)
    else:
        frames = x[: len(x) // n * n].reshape(-1, n).astype(np.float64)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    with np.errstate(divide="ignore"):
        db = 20 * np.log10(rms)
    active = frames[db > GATE_DB]
    if active.size == 0:
        return None
    return float(20 * np.log10(np.sqrt(np.mean(active ** 2))))


def _limit(x: np.ndarray) -> np.ndarray:
    """A smooth peak limiter: never above the ceiling, no gain steps."""
    ceiling = 10 ** (PEAK_DB / 20)
    a = np.abs(x)
    if a.max(initial=0.0) <= ceiling:
        return x
    need = np.minimum(1.0, ceiling / np.maximum(a, 1e-12))
    w = max(3, int(LIMIT_WINDOW_S * SR) | 1)
    g = minimum_filter1d(need, size=w, mode="nearest")
    # a moving average of a window-minimum stays at or below `need` everywhere
    g = np.convolve(np.pad(g, (w // 2, w // 2), mode="edge"), np.ones(w) / w, mode="valid")
    y = (x * g).astype(np.float32)
    return np.clip(y, -ceiling, ceiling)


def normalise(x: np.ndarray) -> np.ndarray:
    """-24 dBFS RMS over speech frames, peaks limited to -3 dBFS.

    The limiter takes a little off the RMS, so the gain is re-measured on the
    limited signal and corrected (a few rounds converge well inside ±0.5 dB).
    """
    x = np.asarray(x, dtype=np.float32)
    level = _speech_rms_db(x)
    if level is None:
        return x
    y = x
    gain = 10 ** ((TARGET_RMS_DB - level) / 20)
    for _ in range(4):
        y = _limit((x * gain).astype(np.float32))
        got = _speech_rms_db(y)
        if got is None or abs(got - TARGET_RMS_DB) < 0.1:
            break
        gain *= 10 ** ((TARGET_RMS_DB - got) / 20)
    final = _speech_rms_db(y)
    if final is not None and abs(final - TARGET_RMS_DB) > 0.5:
        log.warning("loudness: speech RMS %.2f dBFS misses the %.1f dBFS target by "
                    "more than 0.5 dB (the peak limiter is holding it down)",
                    final, TARGET_RMS_DB)
    return y


def _write_atomic(x: np.ndarray, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.stem}-", suffix=".wav")
    os.close(fd)
    try:
        sf.write(tmp, x, SR, subtype="FLOAT")
        os.replace(tmp, out)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _duration(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / info.samplerate


# --- voicing ------------------------------------------------------------------

def _speak(provider: Provider, text: str, voice: Voice, language: str) -> list[np.ndarray]:
    parts = []
    for piece in chunk(text, provider.max_chars,
                       measure=lambda t: len(provider.translate_cues(t))):
        audio, sr = provider.synthesize(piece, voice.voice_id, voice.model, language)
        parts.append(_edges(_to_sr(audio, sr)))
    return parts


def voice_passage(provider: Provider, text: str, voice: Voice, language: str,
                  out: Path) -> float:
    """Voice one passage (neutral cues) to `out`; return its duration in seconds.

    A `[long pause]` is real silence (LONG_PAUSE_S) rather than a provider cue,
    so the lessons get a dependable gap to answer in. Does nothing if `out`
    exists.
    """
    out = Path(out)
    if out.exists():
        return _duration(out)
    pieces: list[np.ndarray] = []
    for segment in _LONG_PAUSE.split(text):
        if not segment.strip():
            continue
        if pieces:
            pieces.append(_silence(LONG_PAUSE_S))
        for j, part in enumerate(_speak(provider, segment, voice, language)):
            if j:
                pieces.append(_silence(CHUNK_GAP_S))
            pieces.append(part)
    if not pieces:
        raise ValueError(f"nothing to voice for {out.name}")
    x = normalise(np.concatenate(pieces))
    _write_atomic(x, out)
    return len(x) / SR


def voice_shuffle(provider: Provider, lines: list[str], voice: Voice, language: str,
                  out: Path, rng: np.random.Generator) -> float:
    """One image per call, assembled with 2–3 s gaps from `rng`."""
    out = Path(out)
    if out.exists():
        return _duration(out)
    pieces: list[np.ndarray] = []
    for line in lines:
        audio, sr = provider.synthesize(line, voice.voice_id, voice.model,
                                        line_language(line, language))
        if pieces:
            pieces.append(_silence(rng.uniform(*SHUFFLE_GAP_S)))
        pieces.append(_edges(_to_sr(audio, sr)))
    if not pieces:
        raise ValueError(f"nothing to voice for {out.name}")
    x = normalise(np.concatenate(pieces))
    _write_atomic(x, out)
    return len(x) / SR


def shuffle_lines(text: str) -> list[str]:
    """A shuffle passage's images, one per non-blank line (cues dropped)."""
    return [ln.strip() for ln in re.sub(r"\[[^\]\n]*\]", "", text).split("\n")
            if ln.strip()]


def shuffle_rng(script_id: str, passage_index: int) -> np.random.Generator:
    """Seeded from the id (crc32: Python's str hash is salted per process)."""
    return np.random.default_rng([zlib.crc32(script_id.encode("utf-8")), passage_index])


def passage_file(index: int) -> str:
    """0-based passage index -> on-disk name, 1-based: 0 -> 'p01.wav'."""
    return f"p{index + 1:02d}.wav"


class VoiceMismatchError(ValueError):
    """Resuming a recording with a different voice than its passages were made with."""


VOICE_FILE = "voice.json"


def _voice_record(v: Voice) -> dict:
    return {"provider": v.provider, "model": v.model, "voice_id": v.voice_id}


def check_resume_voice(script: Script, voice: Voice, library: Path) -> None:
    """Refuse to mix voices inside one recording. Raises VoiceMismatchError
    (message names the recording and both voices) before anything is spent.

    The recording directory's `voice.json` (written before the first request)
    says which voice made its passages; a finished `recording.json` says the
    same. Passages on disk with neither record are refused too: their voice
    is unknown.
    """
    d = Path(library) / script.id
    want = _voice_record(voice)
    have = None
    vf, mf = d / VOICE_FILE, d / "recording.json"
    if vf.exists():
        try:
            have = json.loads(vf.read_text(encoding="utf-8"))
        except ValueError:
            raise VoiceMismatchError(f"{script.id}: {vf} is unreadable; "
                                     "delete the directory to re-voice") from None
    elif mf.exists():
        m = read_manifest(mf)
        have = {"provider": m.provider, "model": m.model, "voice_id": m.voice_id}
    elif d.is_dir() and any(d.glob("p*.wav")):
        raise VoiceMismatchError(f"{script.id}: passages exist in {d} with no record "
                                 "of their voice; delete them to re-voice")
    if have is not None and {k: have.get(k) for k in want} != want:
        raise VoiceMismatchError(
            f"{script.id}: its passages were voiced with {have.get('provider')}/"
            f"{have.get('model')}/{have.get('voice_id')}, not {voice.provider}/"
            f"{voice.model}/{voice.voice_id}; delete {d} to re-voice with the new voice")


def voice_recording(script: Script, provider: Provider, voice: Voice,
                    library: Path, on_error=None) -> Manifest | None:
    """Voice every passage of `script` into `<library>/<id>/`.

    Returns the manifest, or None if a provider error stopped the run (the
    passages already written stay; no manifest is written; rerun to finish).
    `on_error(message)` is called with the (key-free) reason when that happens.
    """
    d = Path(library) / script.id
    manifest_path = d / "recording.json"
    check_resume_voice(script, voice, library)
    if not (d / VOICE_FILE).exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / VOICE_FILE).write_text(json.dumps(_voice_record(voice), indent=2) + "\n",
                                    encoding="utf-8")
    entries: list[PassageEntry] = []
    try:
        for p in script.passages:
            out = d / passage_file(p.index)
            if script.show == "shuffles":
                dur = voice_shuffle(provider, shuffle_lines(p.text), voice,
                                    script.language, out, shuffle_rng(script.id, p.index))
            else:
                dur = voice_passage(provider, p.text, voice, script.language, out)
            entries.append(PassageEntry(index=p.index, file=out.name,
                                        duration_s=round(dur, 3),
                                        text=spoken_text(p), intensity=p.intensity))
    except ProviderError as e:
        msg = f"{script.id}: stopped at passage {len(entries) + 1}: {e}"
        log.warning("%s", msg)
        if on_error:
            on_error(msg)
        return None
    if manifest_path.exists():
        try:
            existing = read_manifest(manifest_path)
            if existing.passages == entries:
                return existing
        except ValueError:
            pass
    m = Manifest(id=script.id, show=script.show, title=script.title,
                 language=script.language, source_character=script.source_character,
                 provider=voice.provider, model=voice.model, voice_id=voice.voice_id,
                 made_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 passages=entries)
    write_manifest(m, d)
    return m
