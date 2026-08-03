import importlib.resources as res

from sleepmix.config import MixConfig, config_schema, plan_stem_configs


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
