"""sleepmix — turn a song into an extended, disintegrating ambient sleep mix.

Separates a track into stems, loops a beat-aligned segment, slows it down,
drenches it in reverb, and progressively 'disintegrates' selected stems over a
long arc (a Basinski-style tape-decay effect applied per stem).
"""
from __future__ import annotations

from .audio import AudioBuffer, load_audio, save_audio
from .config import MixConfig, NothingToRender, config_schema, plan_stem_configs
from .peaks import compute_peaks
from .pipeline import run_pipeline
from .preview import render_window, preview_iteration_index
from .progress import CancelToken, Cancelled, ProgressEvent, ProgressReporter
from .session import RenderSession

__version__ = "0.1.0"

__all__ = ["AudioBuffer", "load_audio", "save_audio", "MixConfig", "run_pipeline"]
__all__ += ["render_window", "preview_iteration_index", "RenderSession",
            "ProgressReporter", "ProgressEvent", "CancelToken", "Cancelled"]
# ``config_schema`` is what a UI's schema endpoint calls to build its controls,
# and ``plan_stem_configs`` is how a caller finds out which stems a render will
# actually process — the two most UI-facing functions in the package were the
# two you had to reach into a submodule for.
__all__ += ["config_schema", "plan_stem_configs", "NothingToRender"]
__all__ += ["compute_peaks"]
