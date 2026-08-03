"""Typed configuration for a sleep-mix render, loadable from YAML.

Every field has a sensible default, so a minimal config (even an empty file)
produces a valid mix. ``MixConfig.from_dict`` does shallow, forgiving merging
so partial YAML overrides just the keys you specify.

Fields also carry display metadata (label, unit, bounds, choices, help) so a
UI can build its controls from ``config_schema()`` instead of hard-coding
them — a hard-coded UI drifts from the config the moment a parameter is
added or its bounds change.
"""
from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class StemDecayConfig:
    """Per-stem 'disintegration' parameters.

    Each value is interpolated from its ``*_start`` to ``*_end`` across the full
    length of the mix, so the loop erodes a little more on every repetition.
    """

    enabled: bool = field(default=True, metadata={"label": "Enabled"})
    curve: str = field(default="linear", metadata={
        "label": "Curve", "choices": ["linear", "exp", "log"],
        "help": "linear · exp (ease-in, dissolves late) · log (ease-out, "
                "degrades fast then lingers)"})

    # Lowpass cutoff sweep — high frequencies erode first, like tape oxide.
    lowpass_start_hz: float = field(default=18000.0, metadata={
        "label": "Lowpass start", "unit": "Hz", "min": 20.0, "max": 20000.0,
        "step": 100.0})
    lowpass_end_hz: float = field(default=1600.0, metadata={
        "label": "Lowpass end", "unit": "Hz", "min": 20.0, "max": 20000.0,
        "step": 100.0})

    # Amplitude fade across the arc.
    amp_start_db: float = field(default=0.0, metadata={
        "label": "Amplitude start", "unit": "dB", "min": -60.0, "max": 0.0,
        "step": 0.5})
    amp_end_db: float = field(default=-9.0, metadata={
        "label": "Amplitude end", "unit": "dB", "min": -60.0, "max": 0.0,
        "step": 0.5})

    # Probability/density of brief dropouts (0..1).
    dropout_start: float = field(default=0.0, metadata={
        "label": "Dropouts start", "min": 0.0, "max": 1.0, "step": 0.01})
    dropout_end: float = field(default=0.25, metadata={
        "label": "Dropouts end", "min": 0.0, "max": 1.0, "step": 0.01})

    # Added noise-floor level (dBFS).
    noise_start_db: float = field(default=-90.0, metadata={
        "label": "Noise floor start", "unit": "dB", "min": -120.0, "max": 0.0,
        "step": 1.0})
    noise_end_db: float = field(default=-42.0, metadata={
        "label": "Noise floor end", "unit": "dB", "min": -120.0, "max": 0.0,
        "step": 1.0})

    # Fraction of spectral bins zeroed ('holes' in the spectrum), 0..1.
    spectral_hole_start: float = field(default=0.0, metadata={
        "label": "Spectral holes start", "min": 0.0, "max": 1.0, "step": 0.01})
    spectral_hole_end: float = field(default=0.30, metadata={
        "label": "Spectral holes end", "min": 0.0, "max": 1.0, "step": 0.01})


@dataclass
class StemConfig:
    """One separated stem and how it should behave in the mix."""

    name: str = field(default="other", metadata={
        "label": "Stem", "choices": ["vocals", "drums", "bass", "other", "mix"]})
    enabled: bool = field(default=True, metadata={"label": "Enabled"})
    gain_db: float = field(default=0.0, metadata={
        "label": "Gain", "unit": "dB", "min": -24.0, "max": 12.0, "step": 0.5})
    reverb_send: float = field(default=1.0, metadata={
        "label": "Reverb send", "min": 0.0, "max": 2.0, "step": 0.01})
    decay: StemDecayConfig = field(default_factory=StemDecayConfig)


@dataclass
class LoopConfig:
    bars: int = field(default=8, metadata={
        "label": "Bars", "min": 1, "max": 64, "step": 1})
    beats_per_bar: int = field(default=4, metadata={
        "label": "Beats per bar", "min": 1, "max": 16, "step": 1})
    crossfade_ms: float = field(default=120.0, metadata={
        "label": "Seam crossfade", "unit": "ms", "min": 0.0, "max": 2000.0,
        "step": 10.0})
    # Where to look for a loop, as fractions of the track (avoids intro/outro).
    search_start: float = field(default=0.2, metadata={
        "label": "Search from", "min": 0.0, "max": 1.0, "step": 0.01,
        "help": "Fraction of the track to start searching for a loop from, "
                "avoiding the intro."})
    search_end: float = field(default=0.8, metadata={
        "label": "Search to", "min": 0.0, "max": 1.0, "step": 0.01,
        "help": "Fraction of the track to stop searching for a loop at, "
                "avoiding the outro."})


@dataclass
class TempoConfig:
    # Playback speed as a fraction of the original. 0.7 = 70% speed (slower,
    # longer). Pitch is preserved unless ``pitch_semitones`` is set.
    speed: float = field(default=0.7, metadata={
        "label": "Speed", "unit": "×", "min": 0.05, "max": 1.0, "step": 0.01,
        "help": "Playback speed as a fraction of the original. 0.7 = 70% speed."})
    pitch_semitones: float = field(default=-2.0, metadata={
        "label": "Pitch", "unit": "st", "min": -12.0, "max": 12.0, "step": 0.5,
        "help": "Semitones to shift, independent of speed."})


@dataclass
class ReverbConfig:
    room_size: float = field(default=0.85, metadata={
        "label": "Room size", "min": 0.0, "max": 1.0, "step": 0.01})
    damping: float = field(default=0.5, metadata={
        "label": "Damping", "min": 0.0, "max": 1.0, "step": 0.01})
    wet: float = field(default=0.45, metadata={
        "label": "Wet", "min": 0.0, "max": 1.0, "step": 0.01})
    dry: float = field(default=0.6, metadata={
        "label": "Dry", "min": 0.0, "max": 1.0, "step": 0.01})
    width: float = field(default=1.0, metadata={
        "label": "Width", "min": 0.0, "max": 1.0, "step": 0.01})
    predelay_ms: float = field(default=40.0, metadata={
        "label": "Pre-delay", "unit": "ms", "min": 0.0, "max": 500.0, "step": 1.0})


@dataclass
class SoundbedConfig:
    enabled: bool = field(default=False, metadata={"label": "Sound bed"})
    noise_type: str = field(default="pink", metadata={
        "label": "Noise type", "choices": ["pink", "brown", "white", "none"]})
    noise_gain_db: float = field(default=-34.0, metadata={
        "label": "Noise level", "unit": "dB", "min": -80.0, "max": 0.0, "step": 1.0})
    binaural_enabled: bool = field(default=False, metadata={
        "label": "Binaural beats",
        "help": "Requires headphones — binaural beats rely on each ear "
                "receiving a different tone."})
    binaural_carrier_hz: float = field(default=110.0, metadata={
        "label": "Carrier", "unit": "Hz", "min": 20.0, "max": 500.0, "step": 1.0})
    binaural_beat_hz: float = field(default=2.5, metadata={
        "label": "Beat frequency", "unit": "Hz", "min": 0.5, "max": 30.0, "step": 0.1})
    binaural_gain_db: float = field(default=-30.0, metadata={
        "label": "Binaural level", "unit": "dB", "min": -80.0, "max": 0.0, "step": 1.0})


@dataclass
class OutputConfig:
    duration_min: float = field(default=20.0, metadata={
        "label": "Duration", "unit": "min", "min": 1.0, "max": 480.0, "step": 1.0,
        "help": "Length of the finished mix."})
    sample_rate: int = field(default=44100, metadata={
        "label": "Sample rate", "unit": "Hz", "choices": [22050, 44100, 48000]})
    channels: int = field(default=2, metadata={
        "label": "Channels", "choices": [1, 2]})
    cycle_crossfade_ms: float = field(default=800.0, metadata={
        "label": "Cycle crossfade", "unit": "ms", "min": 0.0, "max": 5000.0,
        "step": 10.0, "help": "Crossfade between successive loop cycles."})
    fade_in_s: float = field(default=8.0, metadata={
        "label": "Fade in", "unit": "s", "min": 0.0, "max": 120.0, "step": 1.0})
    fade_out_s: float = field(default=12.0, metadata={
        "label": "Fade out", "unit": "s", "min": 0.0, "max": 120.0, "step": 1.0})
    peak_db: float = field(default=-1.0, metadata={
        "label": "Peak ceiling", "unit": "dBFS", "min": -12.0, "max": 0.0,
        "step": 0.1})


@dataclass
class MixConfig:
    seed: int = 0
    separation_model: str = "htdemucs_ft"
    stems: list[StemConfig] = field(default_factory=lambda: [
        StemConfig(name="vocals", decay=StemDecayConfig(
            curve="exp", lowpass_end_hz=2200, amp_end_db=-16, spectral_hole_end=0.45)),
        StemConfig(name="other", decay=StemDecayConfig(
            curve="linear", lowpass_end_hz=2400, amp_end_db=-4)),
        StemConfig(name="bass", decay=StemDecayConfig(
            enabled=False)),  # keep the low end steady by default
        StemConfig(name="drums", enabled=False),  # usually too rhythmic for sleep
    ])
    loop: LoopConfig = field(default_factory=LoopConfig)
    tempo: TempoConfig = field(default_factory=TempoConfig)
    reverb: ReverbConfig = field(default_factory=ReverbConfig)
    soundbed: SoundbedConfig = field(default_factory=SoundbedConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # -- (de)serialization ---------------------------------------------
    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "MixConfig":
        return _build(cls, d or {})

    @classmethod
    def from_yaml(cls, path: str) -> "MixConfig":
        import yaml

        with open(path) as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})


def _build(dc_type: type, d: dict[str, Any]) -> Any:
    """Recursively construct a dataclass from a (partial) dict, keeping defaults
    for anything not supplied. Nested dataclasses and the ``stems`` list are
    constructed recursively; unknown keys are ignored."""
    if not isinstance(d, dict):
        return d
    from typing import get_type_hints

    hints = get_type_hints(dc_type)
    known = {f.name for f in fields(dc_type)}
    kwargs: dict[str, Any] = {}
    for name, val in d.items():
        if name not in known:
            continue  # forgiving: skip stray keys
        ftype = hints.get(name)
        if name == "stems" and isinstance(val, list):
            kwargs[name] = [_build(StemConfig, item) for item in val]
        elif is_dataclass(ftype) and isinstance(val, dict):
            kwargs[name] = _build(ftype, val)
        else:
            kwargs[name] = val
    return dc_type(**kwargs)


# -- schema export ------------------------------------------------------
_SECTION_TYPES = {
    "loop": LoopConfig,
    "tempo": TempoConfig,
    "reverb": ReverbConfig,
    "soundbed": SoundbedConfig,
    "output": OutputConfig,
    "stem": StemConfig,
    "stem_decay": StemDecayConfig,
}


def config_schema() -> dict[str, Any]:
    """Describe every config field so a UI can generate its own controls.

    Hard-coding controls in the frontend means they drift from the config the
    moment a parameter is added. This is the single source of truth for bounds,
    units and labels."""
    return {
        "fields": _describe_fields(MixConfig),
        "sections": {name: {"fields": _describe_fields(t)}
                     for name, t in _SECTION_TYPES.items()},
    }


def _describe_fields(dc_type: type) -> dict[str, Any]:
    from typing import get_type_hints

    hints = get_type_hints(dc_type)
    out: dict[str, Any] = {}
    for f in fields(dc_type):
        # Nested dataclasses (and the stem list) are described as their own
        # sections, never as leaf controls — a UI iterating these fields must
        # not be handed 'decay' or 'loop' as though they were scalar inputs.
        # Types are resolved via get_type_hints because ``from __future__ import
        # annotations`` makes ``f.type`` a string.
        if is_dataclass(hints.get(f.name)) or f.name == "stems":
            continue
        meta = dict(f.metadata)
        entry: dict[str, Any] = {
            "type": _type_name(f),
            "default": _default_of(f),
            "label": meta.get("label", f.name.replace("_", " ").capitalize()),
            "help": meta.get("help"),
        }
        for key in ("min", "max", "step", "unit", "choices"):
            if key in meta:
                entry[key] = meta[key]
        out[f.name] = entry
    return out


def _type_name(f) -> str:
    raw = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
    for py, name in (("bool", "bool"), ("int", "int"), ("float", "float")):
        if raw.startswith(py):
            return name
    return "str"


def _default_of(f) -> Any:
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:  # type: ignore[misc]
        return None
    return None
