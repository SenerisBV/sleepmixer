"""Where sleepmix keeps its data.

The separation cache used to be a CWD-relative ``.sleepmix_cache``, which meant
its location depended on where you happened to launch from — fine for a CLI you
run from the project directory, wrong for a long-lived server process. These
helpers resolve to a stable per-user location instead, overridable with
``SLEEPMIX_DATA_DIR`` (which the test suite uses to stay off real data).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_VAR = "SLEEPMIX_DATA_DIR"


def data_dir() -> Path:
    """Application data root. Created if missing."""
    override = os.environ.get(ENV_VAR)
    d = Path(override).expanduser() if override else _platform_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    """Stem-separation cache. Created if missing."""
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _platform_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sleepmix"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "sleepmix"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sleepmix"
