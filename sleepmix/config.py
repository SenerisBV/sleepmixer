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

import inspect
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class StemDecayConfig:
    """How one stem falls apart across the length of the mix.

    Every stem row has a Decay panel, and every value in it has a start and an
    end. A mix is one loop played over and over, and as it plays each of these
    moves from its start toward its end, so the loop erodes a little more every
    time round. The Curve setting in that panel decides how the move is paced:
    evenly the whole way, holding close to the start until a late rush, or
    rushing away early and lingering near the end.

    Five things happen to a stem, and this is the order they happen in: treble
    is filtered away, notches are punched out of what is left, brief gaps are
    dropped in, the level falls, and noise is mixed in underneath. It is not
    the order the panel lists them in — those controls are alphabetical, which
    is also why each pair's end sits above its start."""

    enabled: bool = field(default=True, metadata={"label": "Enabled"})
    curve: str = field(default="linear", metadata={
        "label": "Curve", "choices": ["linear", "exp", "log"],
        "help": "linear · exp (ease-in, dissolves late) · log (ease-out, "
                "degrades fast then lingers)"})

    # Lowpass cutoff sweep — high frequencies erode first, like tape oxide.
    lowpass_start_hz: float = field(default=18000.0, metadata={
        "label": "Lowpass start", "unit": "Hz", "min": 20.0, "max": 20000.0,
        "step": 100.0,
        "help": "How much treble the stem still has at the beginning. "
                "Everything above this is filtered away."})
    lowpass_end_hz: float = field(default=1600.0, metadata={
        "label": "Lowpass end", "unit": "Hz", "min": 20.0, "max": 20000.0,
        "step": 100.0,
        "help": "How much treble is left by the end. This does more than "
                "anything else here to make a stem recede into the distance."})

    # Amplitude fade across the arc.
    amp_start_db: float = field(default=0.0, metadata={
        "label": "Amplitude start", "unit": "dB", "min": -60.0, "max": 0.0,
        "step": 0.5,
        "help": "How loud the stem is at the beginning of the decay, in dB "
                "relative to the stem itself (0 dB = unchanged)."})
    amp_end_db: float = field(default=-9.0, metadata={
        "label": "Amplitude end", "unit": "dB", "min": -60.0, "max": 0.0,
        "step": 0.5,
        "help": "How loud the stem is by the end of the decay, in dB "
                "relative to the stem itself (0 dB = unchanged)."})

    # Probability/density of brief dropouts (0..1).
    dropout_start: float = field(default=0.0, metadata={
        "label": "Dropouts start", "min": 0.0, "max": 1.0, "step": 0.01,
        "help": "How often brief gaps are dropped into the stem at the "
                "beginning. They are smoothly ramped, like tape dropouts, "
                "not hard cuts."})
    dropout_end: float = field(default=0.25, metadata={
        "label": "Dropouts end", "min": 0.0, "max": 1.0, "step": 0.01,
        "help": "How often brief gaps are dropped into the stem by the end. "
                "They are smoothly ramped, like tape dropouts, not hard "
                "cuts."})

    # Added noise-floor level (dBFS).
    noise_start_db: float = field(default=-90.0, metadata={
        "label": "Noise floor start", "unit": "dB", "min": -120.0, "max": 0.0,
        "step": 1.0,
        "help": "How much noise is mixed in underneath at the beginning. "
                "Added last in the decay, after the lowpass, spectral holes "
                "and dropouts."})
    noise_end_db: float = field(default=-42.0, metadata={
        "label": "Noise floor end", "unit": "dB", "min": -120.0, "max": 0.0,
        "step": 1.0,
        "help": "How much noise is mixed in underneath by the end. Added "
                "last in the decay, after the lowpass, spectral holes and "
                "dropouts."})

    # Fraction of spectral bins zeroed ('holes' in the spectrum), 0..1.
    spectral_hole_start: float = field(default=0.0, metadata={
        "label": "Spectral holes start", "min": 0.0, "max": 1.0, "step": 0.01,
        "help": "How much of the stem's frequency range is punched out at "
                "the beginning. Unlike the lowpass, this scatters gaps "
                "throughout the spectrum rather than sweeping the top away."})
    spectral_hole_end: float = field(default=0.30, metadata={
        "label": "Spectral holes end", "min": 0.0, "max": 1.0, "step": 0.01,
        "help": "How much of the stem's frequency range is punched out by "
                "the end. Unlike the lowpass, this scatters gaps throughout "
                "the spectrum rather than sweeping the top away."})


@dataclass
class StemConfig:
    """One separated stem and how it should behave in the mix.

    Every stem the separation produced gets a row: whether it is in the mix at
    all, how loud, how much of it goes into the reverb, and its own decay
    settings. Stems erode independently, which is the point — vocals can
    dissolve while the bass stays put."""

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
    """Which fragment of the song gets repeated, and how the repeats are joined.

    A mix is one loop played over and over for however long you asked for.
    Leave the start and end empty and a beat-aligned loop is found for you,
    somewhere between the search bounds; set them and that region is used
    exactly. Everything here is about choosing and joining the fragment — the
    eroding happens elsewhere."""

    bars: int = field(default=8, metadata={
        "label": "Bars", "min": 1, "max": 64, "step": 1,
        "help": "Together with beats per bar, decides how long the repeated "
                "fragment is, in musical rather than clock time — eight bars "
                "of four beats, by default."})
    beats_per_bar: int = field(default=4, metadata={
        "label": "Beats per bar", "min": 1, "max": 16, "step": 1,
        "help": "Together with bars, decides how long the repeated fragment "
                "is, in musical rather than clock time — eight bars of four "
                "beats, by default."})
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
    # Explicit loop region in seconds. Both None (the default) means auto-detect.
    # Set by the UI when you drag the loop handles on the waveform.
    start_s: float | None = field(default=None, metadata={
        "label": "Loop start", "unit": "s", "min": 0.0,
        "help": "Leave empty to auto-detect a beat-aligned loop."})
    end_s: float | None = field(default=None, metadata={
        "label": "Loop end", "unit": "s", "min": 0.0,
        "help": "Leave empty to auto-detect a beat-aligned loop."})


@dataclass
class TempoConfig:
    """How fast and how low the loop plays, before any of it erodes.

    Slowing a track down and dropping it a little is most of what makes it
    sound like it is somewhere else. This happens once, to the loop, and every
    repetition inherits it."""

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
    """The space the stems sit in.

    One shared room — the same size, damping, and wet/dry balance for every
    stem. Each stem's own send decides how much of itself goes into it, and
    each stem passes through the reverb on its own rather than after
    everything is mixed together. Larger and wetter pushes the mix further
    away, which is usually what you want for something you intend to fall
    asleep to."""

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
    """A continuous bed underneath the mix: noise, binaural tones, or both.

    Off by default. Mixed in when you render — previews never include it, so
    turning it on changes nothing you can hear in the mixer.

    The binaural half needs headphones. It works by sending each ear a slightly
    different tone and letting you hear the difference between them; a speaker
    adds the two together before they reach you, and there is nothing left to
    hear."""

    # The four binaural fields sort next to each other in the mixer's
    # key-ordered grid — beat_hz, carrier_hz, enabled, gain_db — so a
    # "Requires headphones" tacked onto each help line read as the same two
    # words four times running, with the *reason* arriving third. Said once
    # above them instead, where it is read before any of the four.
    enabled: bool = field(default=False, metadata={"label": "Sound bed"})
    noise_type: str = field(default="pink", metadata={
        "label": "Noise type", "choices": ["pink", "brown", "white", "none"]})
    noise_gain_db: float = field(default=-34.0, metadata={
        "label": "Noise level", "unit": "dB", "min": -80.0, "max": 0.0, "step": 1.0})
    binaural_enabled: bool = field(default=False, metadata={
        "label": "Binaural beats"})
    binaural_carrier_hz: float = field(default=110.0, metadata={
        "label": "Carrier", "unit": "Hz", "min": 20.0, "max": 500.0, "step": 1.0,
        "help": "The tone the left ear hears; the right ear gets this plus "
                "the beat frequency."})
    binaural_beat_hz: float = field(default=2.5, metadata={
        "label": "Beat frequency", "unit": "Hz", "min": 0.5, "max": 30.0, "step": 0.1,
        "help": "The difference between the two ears' tones, which is what "
                "you perceive as a slow pulse."})
    binaural_gain_db: float = field(default=-30.0, metadata={
        "label": "Binaural level", "unit": "dB", "min": -80.0, "max": 0.0, "step": 1.0,
        "help": "How loud the binaural tones sit under the mix."})


@dataclass
class OutputConfig:
    """The shape of the finished file: how long, how loud, and how it starts
    and ends.

    Length is the one that matters most, because everything else in the config
    describes a journey and this says how long the journey takes."""

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
        "step": 0.1,
        "help": "The ceiling the finished file is normalised to. Headroom, "
                "not loudness: it is how close the loudest moment gets to "
                "clipping."})


# This docstring is published as the mixer's top-level description, so it is
# read directly above the one row Mix renders. It deliberately does NOT say what
# a seed is for: the seed's own `help` says that, an inch lower, and Mix renders
# exactly one control — so a description that explained the seed would be 100%
# of the section restating 100% of itself. Same shape Task 4 of Plan 3f fixed
# twice (Mix claiming two controls while showing one; Soundbed's description and
# note carrying one sentence between them). Name the control here, explain it
# there.
@dataclass
class MixConfig:
    """Everything that decides what a finished mix sounds like.

    Just one of these gets a control in the mixer, under "Mix": the seed. The
    other is the model the song is split into stems with, which is a fact about
    the separation rather than about the mix. Everything else a mix is made of
    is in the sections below."""

    # ``min`` is not decoration: ``validate`` rejects a negative seed, and the
    # UI builds its controls from this metadata alone. Without a floor here the
    # generated control can produce a value the config refuses, and the failure
    # lands as a 400 on a preview rather than as a control that will not go
    # there.
    seed: int = field(default=0, metadata={
        "label": "Seed", "min": 0, "step": 1,
        "help": "Fixes the random parts of the decay — dropouts, noise, "
                "spectral holes — so the same settings render the same mix."})
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
        config = _build(cls, d or {})
        config.validate()
        return config

    def validate(self) -> None:
        """Raise ``ValueError`` for values that would fail deep in the DSP.

        ``seed`` feeds numpy's ``SeedSequence`` via ``util.iteration_rng``,
        which requires non-negative entropy. Caught here because this is where
        a config from a UI field first arrives."""
        if int(self.seed) < 0:
            raise ValueError(f"seed must be non-negative, got {self.seed}")

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


def _describe_type(dc_type: type) -> str:
    """A section's own explanation, taken from the class it describes.

    Sourced from ``__doc__`` so the text lives with the thing it explains
    rather than in a table beside it, which is how the two come to disagree.

    ``dataclass`` synthesises a ``__doc__`` that is the constructor signature,
    and publishing that would put ``LoopConfig(bars: 'int' = 8, ...)`` on
    screen as though it meant something. That case raises instead: a section
    added without a description should fail loudly here rather than quietly
    render a heading with nothing under it."""
    doc = inspect.cleandoc(dc_type.__doc__ or "")
    if not doc or doc.startswith(f"{dc_type.__name__}("):
        raise ValueError(
            f"{dc_type.__name__} needs a docstring: it is published to the UI "
            f"as the section's description")
    return doc


def config_schema() -> dict[str, Any]:
    """Describe every config field so a UI can generate its own controls.

    Hard-coding controls in the frontend means they drift from the config the
    moment a parameter is added. This is the single source of truth for bounds,
    units and labels."""
    return {
        "description": _describe_type(MixConfig),
        "fields": _describe_fields(MixConfig),
        "sections": {name: {"description": _describe_type(t),
                             "fields": _describe_fields(t)}
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


class NothingToRender(ValueError):
    """The config asks for a mix of no stems at all.

    A ``ValueError`` so that a caller which only knows "this config is bad"
    (the CLI, a render job) handles it with everything else; its own type so
    that ``POST /api/preview`` can answer 400 with the reason for *this*
    specifically, without turning an arithmetic ``ValueError`` from somewhere
    deep in the DSP into a message about stems."""


def plan_stem_configs(available: list[str], config: "MixConfig") -> list[StemConfig]:
    """Which stem configs apply, given the stems that actually exist.

    Configured stems that are enabled and present; or — only when the config
    *describes* none of them — every available stem at defaults, which is what
    happens when separation falls back to a single 'mix' stem. Preview and batch
    render must agree on this or the preview shows audio the render never
    produces.

    The two conditions are separate on purpose, and the distinction is load-
    bearing. "No configured name matches what separation produced" means the
    config has nothing to say about this song and defaults are the only sensible
    reading. "Every matching stem is switched off" is a *deliberate instruction*
    from whoever switched them off, and answering it with a full default mix
    plays audio nobody asked for, at a level nobody chose, discarding every gain
    and decay setting in the same step. That was unreachable until the mixer
    shipped per-stem Enabled checkboxes; four clicks reach it now.

    So this may return an empty list, and every caller must decide what that
    means rather than letting it fall through to silence — see
    ``preview.render_window`` and ``pipeline._plan_jobs``, which both refuse."""
    matching = [sc for sc in config.stems if sc.name in available]
    if not matching:
        return [StemConfig(name=name) for name in available]
    return [sc for sc in matching if sc.enabled]
