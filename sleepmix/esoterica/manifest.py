"""The per-recording manifest (`recording.json`)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMAT_VERSION = 1


class ManifestError(ValueError):
    """An unreadable or malformed recording.json (message names the path)."""


@dataclass
class PassageEntry:
    index: int
    file: str
    duration_s: float
    text: str
    intensity: str


@dataclass(kw_only=True)
class Manifest:
    format_version: int = FORMAT_VERSION
    id: str
    show: str
    title: str
    language: str
    source_character: str
    provider: str
    model: str
    voice_id: str
    made_at: str
    passages: list[PassageEntry] = field(default_factory=list)


def write_manifest(m: Manifest, dir: Path) -> Path:
    """Write recording.json atomically (temp file in the same dir, then rename)."""
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    target = dir / "recording.json"
    fd, tmp = tempfile.mkstemp(dir=dir, prefix=".recording-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(m), f, indent=2, ensure_ascii=False)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return target


def read_manifest(path: Path) -> Manifest:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("top level is not an object")
        if data.get("format_version") != FORMAT_VERSION:
            raise ManifestError(f"{path}: unsupported format_version "
                                f"{data.get('format_version')!r}")
        data["passages"] = [PassageEntry(**p) for p in data["passages"]]
        return Manifest(**data)
    except ManifestError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise ManifestError(f"{path}: invalid manifest ({type(e).__name__}: {e})") from e
