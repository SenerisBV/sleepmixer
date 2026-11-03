"""Minimal .env reader and API key lookup. Never includes a value in an error."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def api_key(name: str, env_path: Path) -> str:
    """Environment first, then .env. Raises KeyError(name) (no value) if missing."""
    value = os.environ.get(name)
    if value:
        return value
    value = load_env(env_path).get(name)
    if value:
        return value
    raise KeyError(name)
