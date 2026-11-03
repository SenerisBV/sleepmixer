"""Parse Esoterica scripts (format documented in esoterica/README.md)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SHOWS = frozenset({"testimonies", "sideline", "addresses", "stations",
                   "lessons", "meditations", "shuffles"})
CUES = frozenset({"[pause]", "[long pause]", "[breath]", "[softly]",
                  "[whisper]", "[laughs quietly]"})
SOURCE_CHARACTERS = frozenset({"tape", "room", "oldmic", "hum", "clean"})
LANGUAGES = frozenset({"en", "fr", "en+invented"})
INTENSITIES = frozenset({"low", "medium", "high"})

_REQUIRED = ("id", "show", "title", "language", "speaker", "source_character", "voice")
_OPTIONAL = ("voice_profile", "speed", "pause_stretch", "delivery")
# delivery: inline provider tags sent before every request, e.g. ElevenLabs v4
# "[slowly, languidly, like molasses]" (v4 ignores `speed`; tags do slow it).
_DELIVERY = re.compile(r"^\[[^\[\]\n]+\](\s*\[[^\[\]\n]+\])*$")
# speed: the provider's speaking-rate setting for this recording (ElevenLabs
# accepts 0.7-1.2, Cartesia 0.6-1.5); pause_stretch: render-time factor on the
# silences between phrases (free to change, raw takes are not touched).
SPEED_RANGE = (0.5, 1.5)
PAUSE_STRETCH_RANGE = (1.0, 4.0)
_BRACKET = re.compile(r"\[[^\]\n]*\]")
_INTENSITY = re.compile(r"^<!--\s*intensity:\s*(\S+?)\s*-->$")
_COMMENT = re.compile(r"<!--.*?-->")


class ScriptError(ValueError):
    """A malformed script. The message always names the file."""


@dataclass(frozen=True)
class Passage:
    index: int
    text: str
    intensity: str  # "low" | "medium" | "high"


@dataclass(frozen=True)
class Script:
    id: str
    show: str
    title: str
    language: str
    speaker: str
    source_character: str
    voice_profile: str | None
    voice: dict | None
    passages: tuple[Passage, ...]
    path: Path
    speed: float | None = None
    pause_stretch: float = 1.0
    delivery: str | None = None


def spoken_text(p: Passage) -> str:
    """The passage text with cues and comments removed (use for character counts)."""
    t = _COMMENT.sub("", p.text)
    t = _BRACKET.sub("", t)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def load_script(path: Path) -> Script:
    path = Path(path)

    def fail(msg: str, line: int | None = None):
        where = f"{path.name}" + (f", line {line}" if line else "")
        raise ScriptError(f"{where}: {msg}")

    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        fail("missing front matter (file must start with a '---' line)", 1)
    try:
        end = lines.index("---", 1)
    except ValueError:
        fail("front matter is not closed with a '---' line", 1)
    try:
        meta = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as e:
        fail(f"front matter is not valid YAML ({e})", 1)
    if not isinstance(meta, dict):
        fail("front matter must be a YAML mapping", 1)

    def key_line(key: str) -> int:
        for n in range(1, end):
            if re.match(rf"^{re.escape(str(key))}\s*:", lines[n]):
                return n + 1
        return 1

    for key in meta:
        if key not in _REQUIRED and key not in _OPTIONAL:
            fail(f"unknown front matter key '{key}'", key_line(key))
    for key in _REQUIRED:
        if key not in meta:
            fail(f"missing front matter key '{key}'")
    for key in ("id", "show", "title", "language", "speaker", "source_character"):
        if not isinstance(meta[key], str) or not meta[key].strip():
            fail(f"front matter '{key}' must be a non-empty string", key_line(key))
    if meta["id"] != path.stem:
        fail(f"id '{meta['id']}' does not match the filename '{path.stem}'",
             key_line("id"))
    if meta["show"] not in SHOWS:
        fail(f"unknown show '{meta['show']}'", key_line("show"))
    if meta["language"] not in LANGUAGES:
        fail(f"unknown language '{meta['language']}'", key_line("language"))
    if meta["source_character"] not in SOURCE_CHARACTERS:
        fail(f"unknown source_character '{meta['source_character']}'",
             key_line("source_character"))
    vp = meta.get("voice_profile")
    if vp is not None and not isinstance(vp, str):
        fail("voice_profile must be a string", key_line("voice_profile"))
    def number(key: str, lo: float, hi: float) -> float | None:
        v = meta.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            fail(f"{key} must be a number", key_line(key))
        if not lo <= v <= hi:
            fail(f"{key} must be between {lo} and {hi}", key_line(key))
        return float(v)

    speed = number("speed", *SPEED_RANGE)
    pause_stretch = number("pause_stretch", *PAUSE_STRETCH_RANGE) or 1.0
    delivery = meta.get("delivery")
    if delivery is not None and (not isinstance(delivery, str)
                                 or not _DELIVERY.match(delivery.strip())):
        fail("delivery must be one or more [bracketed] tags, e.g. '[slowly]'",
             key_line("delivery"))
    delivery = delivery.strip() if delivery else None
    voice = meta["voice"]
    if voice is not None and not isinstance(voice, dict):
        fail("voice must be empty or a mapping", key_line("voice"))

    # Split the body into raw passages of (file line number, text) pairs.
    raw: list[list[tuple[int, str]]] = [[]]
    start_lines = [end + 2]  # file line where each passage starts (its separator)
    for i in range(end + 1, len(lines)):
        if lines[i] == "[passage]":
            raw.append([])
            start_lines.append(i + 1)
        else:
            raw[-1].append((i + 1, lines[i]))

    passages = []
    for idx, chunk in enumerate(raw):
        while chunk and not chunk[0][1].strip():
            chunk.pop(0)
        while chunk and not chunk[-1][1].strip():
            chunk.pop()
        intensity = "medium"
        if chunk:
            m = _INTENSITY.match(chunk[0][1].strip())
            if m:
                intensity = m.group(1)
                if intensity not in INTENSITIES:
                    fail(f"unknown intensity '{intensity}'", chunk[0][0])
                chunk.pop(0)
        for ln, text in chunk:
            if "<!--" in text:
                fail("HTML comments are only allowed as a passage's "
                     "'<!-- intensity: ... -->' first line", ln)
            for cue in _BRACKET.findall(text):
                if cue not in CUES:
                    fail(f"unknown cue {cue}", ln)
            if "[" in _BRACKET.sub("", text) or "]" in _BRACKET.sub("", text):
                fail("stray '[' or ']' (an unbalanced or split cue would be "
                     "spoken aloud)", ln)
        body = "\n".join(t for _, t in chunk).strip()
        p = Passage(idx, body, intensity)
        if not spoken_text(p):
            fail(f"passage {idx + 1} is empty (no spoken text)", start_lines[idx])
        passages.append(p)

    return Script(id=meta["id"], show=meta["show"], title=meta["title"],
                  language=meta["language"], speaker=meta["speaker"],
                  source_character=meta["source_character"], voice_profile=vp,
                  voice=voice, passages=tuple(passages), path=path,
                  speed=speed, pause_stretch=pause_stretch, delivery=delivery)


def load_all(root: Path) -> list[Script]:
    """Parse every `<show>/<id>.md` under root, sorted by show then id."""
    scripts = []
    seen: dict[str, Path] = {}
    for p in sorted(Path(root).glob("*/*.md")):
        s = load_script(p)
        if p.parent.name != s.show:
            raise ScriptError(f"{p.name}: lives in directory '{p.parent.name}' "
                              f"but its show is '{s.show}'")
        if s.id in seen:
            raise ScriptError(f"duplicate id '{s.id}': {seen[s.id]} and {p}")
        seen[s.id] = p
        scripts.append(s)
    return scripts
