"""sleepmix — turn a song into an extended, disintegrating ambient sleep mix.

Separates a track into stems, loops a beat-aligned segment, slows it down,
drenches it in reverb, and progressively 'disintegrates' selected stems over a
long arc (a Basinski-style tape-decay effect applied per stem).
"""
from __future__ import annotations

from .audio import AudioBuffer, load_audio, save_audio
from .config import MixConfig
from .pipeline import run_pipeline

__version__ = "0.1.0"

__all__ = ["AudioBuffer", "load_audio", "save_audio", "MixConfig", "run_pipeline"]
