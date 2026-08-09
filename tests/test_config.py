import dataclasses
import importlib.resources as res

import pytest

from sleepmix.config import MixConfig, _SECTION_TYPES, config_schema, plan_stem_configs


def test_defaults_are_valid():
    cfg = MixConfig()
    assert cfg.output.sample_rate == 44100
    assert any(s.name == "vocals" for s in cfg.stems)


def test_partial_override_keeps_defaults():
    cfg = MixConfig.from_dict({
        "tempo": {"speed": 0.5},
        "output": {"duration_min": 3},
    })
    assert cfg.tempo.speed == 0.5
    assert cfg.tempo.pitch_semitones == -2.0          # untouched default
    assert cfg.output.duration_min == 3
    assert cfg.output.sample_rate == 44100            # untouched default


def test_stems_list_builds_nested_decay():
    cfg = MixConfig.from_dict({
        "stems": [{"name": "vocals", "decay": {"curve": "exp", "amp_end_db": -20}}],
    })
    assert len(cfg.stems) == 1
    assert cfg.stems[0].decay.curve == "exp"
    assert cfg.stems[0].decay.amp_end_db == -20


def test_unknown_keys_ignored():
    cfg = MixConfig.from_dict({"nonsense": 1, "seed": 7})
    assert cfg.seed == 7


def test_example_yaml_parses(tmp_path):
    text = res.files("sleepmix").joinpath("config.example.yaml").read_text()
    p = tmp_path / "c.yaml"
    p.write_text(text)
    cfg = MixConfig.from_yaml(str(p))
    assert cfg.soundbed.enabled is True
    assert cfg.output.duration_min == 25
    assert cfg.arrangement.gap_start_s == 0.0
    assert cfg.arrangement.gap_end_s == 0.0
    assert cfg.arrangement.gap_curve == "linear"


def test_schema_describes_tempo_speed():
    s = config_schema()
    speed = s["sections"]["tempo"]["fields"]["speed"]
    assert speed["type"] == "float"
    assert speed["default"] == 0.7
    assert speed["min"] == 0.05
    assert speed["max"] == 1.0
    assert speed["label"]


def test_schema_exposes_curve_choices():
    s = config_schema()
    curve = s["sections"]["stem_decay"]["fields"]["curve"]
    assert set(curve["choices"]) == {"linear", "exp", "log"}


def test_schema_includes_units_where_meaningful():
    s = config_schema()
    assert s["sections"]["output"]["fields"]["duration_min"]["unit"] == "min"
    assert s["sections"]["stem_decay"]["fields"]["lowpass_end_hz"]["unit"] == "Hz"


def test_schema_omits_nested_dataclasses_from_leaf_fields():
    """Nested sections must never appear as scalar controls.

    ``StemConfig.decay`` is a dataclass, not a value — a UI iterating the stem
    section's fields would otherwise render a text input for it."""
    s = config_schema()
    assert "decay" not in s["sections"]["stem"]["fields"]
    assert "stems" not in s["fields"]
    for section in ("loop", "tempo", "reverb", "soundbed", "output"):
        assert section not in s["fields"]


def test_metadata_does_not_change_defaults_or_yaml_loading(tmp_path):
    # Defaults survive the addition of metadata.
    assert MixConfig().tempo.speed == 0.7
    assert MixConfig().output.duration_min == 20.0
    # Partial YAML still merges as before.
    p = tmp_path / "c.yaml"
    p.write_text("tempo:\n  speed: 0.5\n")
    cfg = MixConfig.from_yaml(str(p))
    assert cfg.tempo.speed == 0.5
    assert cfg.tempo.pitch_semitones == -2.0


def test_plan_stem_configs_selects_enabled_configured_stems():
    planned = plan_stem_configs(["vocals", "drums", "bass", "other"], MixConfig())
    assert [sc.name for sc in planned] == ["vocals", "other", "bass"]


def test_plan_stem_configs_falls_back_only_when_nothing_matches():
    planned = plan_stem_configs(["mix"], MixConfig())
    assert [sc.name for sc in planned] == ["mix"]
    assert planned[0].enabled


def test_plan_stem_configs_plans_nothing_when_every_matching_stem_is_off():
    """Switching every stem off means silence, not the default mix.

    The fallback below exists for a config that says *nothing* about the stems
    a song has. Applied to a config that says "none of them", it plays the full
    default mix at full level — every gain, reverb send and decay setting
    discarded — which is four clicks away in the mixer's Enabled checkboxes."""
    cfg = MixConfig()
    for sc in cfg.stems:
        sc.enabled = False

    assert plan_stem_configs(["vocals", "drums", "bass", "other"], cfg) == []


def test_plan_stem_configs_falls_back_even_when_the_config_is_all_off():
    """The discriminator between the two cases, stated as a test.

    Same config as above — every stem disabled — against stems it does not
    name. Nothing it says applies to this song at all, so defaults are the only
    reading, and this must keep behaving exactly as the ``["mix"]`` fallback
    always has."""
    cfg = MixConfig()
    for sc in cfg.stems:
        sc.enabled = False

    planned = plan_stem_configs(["mix"], cfg)
    assert [sc.name for sc in planned] == ["mix"]
    assert planned[0].enabled


def test_from_dict_rejects_a_negative_seed():
    """numpy's SeedSequence requires non-negative entropy; a negative seed
    would raise deep inside the DSP with an unhelpful message."""
    import pytest

    with pytest.raises(ValueError, match="seed"):
        MixConfig.from_dict({"seed": -1})


def test_from_dict_accepts_zero_and_positive_seeds():
    assert MixConfig.from_dict({"seed": 0}).seed == 0
    assert MixConfig.from_dict({"seed": 7}).seed == 7


def test_schema_gives_seed_the_floor_validate_enforces():
    """The UI generates its controls from this metadata and nothing else.

    ``validate`` rejects a negative seed, so a schema that does not say so
    describes a control which can produce a config the server will refuse —
    the rejection then arrives as a 400 on a preview instead of as a slider
    that will not go below zero."""
    seed = config_schema()["fields"]["seed"]
    assert seed["type"] == "int"
    assert seed["default"] == 0
    assert seed["min"] == 0


def test_every_section_carries_a_description():
    """A section with no description reaches the mixer as a heading and a row
    of controls with nothing saying what any of it is for. Derived from
    _SECTION_TYPES rather than written out, so a section added later fails
    here until somebody describes it."""
    schema = config_schema()
    for name in _SECTION_TYPES:
        assert schema["sections"][name]["description"].strip(), name


def test_the_top_level_carries_a_description():
    assert config_schema()["description"].strip()


def test_a_generated_dataclass_docstring_is_refused():
    """dataclass writes a __doc__ that is just the constructor signature.
    Publishing that would put 'LoopConfig(bars: int = 8, ...)' on screen as
    though it explained something."""
    import sleepmix.config as cfg

    @dataclasses.dataclass
    class Undocumented:
        x: int = 1

    with pytest.raises(ValueError, match="Undocumented"):
        cfg._describe_type(Undocumented)


NEEDS_HELP = {
    "stem_decay": [
        "lowpass_start_hz", "lowpass_end_hz",
        "amp_start_db", "amp_end_db",
        "dropout_start", "dropout_end",
        "spectral_hole_start", "spectral_hole_end",
        "noise_start_db", "noise_end_db",
    ],
    "loop": ["bars", "beats_per_bar"],
    "output": ["peak_db"],
    "soundbed": ["binaural_carrier_hz", "binaural_beat_hz", "binaural_gain_db"],
}


def test_the_fields_whose_names_hide_their_effect_carry_help():
    """These are the controls a newcomer cannot guess from the label. The list
    is deliberate and short: help on a field whose label already says it
    teaches readers to skip the ones that matter."""
    sections = config_schema()["sections"]
    for section, names in NEEDS_HELP.items():
        for name in names:
            assert sections[section]["fields"][name].get("help", "").strip(), \
                f"{section}.{name}"


def test_help_says_something_the_label_does_not():
    """A minimal sanity check, not proof of substance: it only catches the
    laziest failure mode, a help string that is the label copied verbatim (or
    padded to be longer than it). It cannot tell real information apart from
    filler."""
    sections = config_schema()["sections"]
    for section, names in NEEDS_HELP.items():
        for name in names:
            aField = sections[section]["fields"][name]
            assert aField["help"].strip().lower() != aField["label"].strip().lower()
            assert len(aField["help"]) > len(aField["label"])


def test_the_arrangement_section_is_published_to_the_ui():
    schema = config_schema()
    assert "arrangement" in schema["sections"]
    fields = schema["sections"]["arrangement"]["fields"]
    assert set(fields) == {"gap_start_s", "gap_end_s", "gap_curve"}
    assert schema["sections"]["arrangement"]["description"]


def test_every_arrangement_field_carries_the_bounds_the_config_enforces():
    """A control that can produce a value ``validate`` refuses turns a slider
    into a 400 on a preview."""
    fields = config_schema()["sections"]["arrangement"]["fields"]
    for name in ("gap_start_s", "gap_end_s"):
        assert fields[name]["min"] == -30.0
        assert fields[name]["max"] == 120.0
    assert fields["gap_curve"]["choices"] == ["linear", "exp", "log"]


def test_arrangement_round_trips_through_from_dict():
    cfg = MixConfig.from_dict(
        {"arrangement": {"gap_start_s": 1.5, "gap_end_s": 9.0,
                         "gap_curve": "exp"}})
    assert cfg.arrangement.gap_start_s == 1.5
    assert cfg.arrangement.gap_end_s == 9.0
    assert cfg.arrangement.gap_curve == "exp"


def test_arrangement_defaults_are_todays_behaviour():
    cfg = MixConfig()
    assert cfg.arrangement.gap_start_s == 0.0
    assert cfg.arrangement.gap_end_s == 0.0
    assert cfg.arrangement.gap_curve == "linear"


def test_a_gap_outside_the_published_bounds_is_refused():
    with pytest.raises(ValueError, match="gap_start_s"):
        MixConfig.from_dict({"arrangement": {"gap_start_s": -100.0}})
    with pytest.raises(ValueError, match="gap_end_s"):
        MixConfig.from_dict({"arrangement": {"gap_end_s": 500.0}})


def test_an_unknown_gap_curve_is_refused():
    with pytest.raises(ValueError, match="gap_curve"):
        MixConfig.from_dict({"arrangement": {"gap_curve": "sigmoid"}})
