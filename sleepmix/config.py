"""Typed configuration for a sleep-mix render, loadable from YAML.

Every field has a sensible default, so a minimal config (even an empty file)
produces a valid mix. ``MixConfig.from_dict`` does shallow, forgiving merging
so partial YAML overrides just the keys you specify.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class StemDecayConfig:
    """Per-stem 'disintegration' parameters.

    Each value is interpolated from its ``*_start`` to ``*_end`` across the full
    length of the mix, so the loop erodes a little more on every repetition.
    """

    enabled: bool = True
    curve: str = "linear"  # linear | exp (ease-in) | log (ease-out)

    # Lowpass cutoff sweep — high frequencies erode first, like tape oxide.
    lowpass_start_hz: float = 18000.0
    lowpass_end_hz: float = 1600.0

    # Amplitude fade across the arc.
    amp_start_db: float = 0.0
    amp_end_db: float = -9.0

    # Probability/density of brief dropouts (0..1).
    dropout_start: float = 0.0
    dropout_end: float = 0.25

    # Added noise-floor level (dBFS).
    noise_start_db: float = -90.0
    noise_end_db: float = -42.0

    # Fraction of spectral bins zeroed ('holes' in the spectrum), 0..1.
    spectral_hole_start: float = 0.0
    spectral_hole_end: float = 0.30


@dataclass
class StemConfig:
    """One separated stem and how it should behave in the mix."""

    name: str = "other"          # vocals | drums | bass | other | mix
    enabled: bool = True
    gain_db: float = 0.0
    reverb_send: float = 1.0     # multiplies the global reverb wet for this stem
    decay: StemDecayConfig = field(default_factory=StemDecayConfig)


@dataclass
class LoopConfig:
    bars: int = 8
    beats_per_bar: int = 4
    crossfade_ms: float = 120.0   # internal seam crossfade for seamless looping
    # Where to look for a loop, as fractions of the track (avoids intro/outro).
    search_start: float = 0.2
    search_end: float = 0.8


@dataclass
class TempoConfig:
    # Playback speed as a fraction of the original. 0.7 = 70% speed (slower,
    # longer). Pitch is preserved unless ``pitch_semitones`` is set.
    speed: float = 0.7
    pitch_semitones: float = -2.0


@dataclass
class ReverbConfig:
    room_size: float = 0.85
    damping: float = 0.5
    wet: float = 0.45
    dry: float = 0.6
    width: float = 1.0
    predelay_ms: float = 40.0


@dataclass
class SoundbedConfig:
    enabled: bool = False
    noise_type: str = "pink"      # pink | brown | white | none
    noise_gain_db: float = -34.0
    binaural_enabled: bool = False
    binaural_carrier_hz: float = 110.0
    binaural_beat_hz: float = 2.5   # delta/theta range for sleep
    binaural_gain_db: float = -30.0


@dataclass
class OutputConfig:
    duration_min: float = 20.0
    sample_rate: int = 44100
    channels: int = 2
    cycle_crossfade_ms: float = 800.0  # crossfade between successive loop cycles
    fade_in_s: float = 8.0
    fade_out_s: float = 12.0
    peak_db: float = -1.0


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
