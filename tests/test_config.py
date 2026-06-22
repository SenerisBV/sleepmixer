import importlib.resources as res

from sleepmix.config import MixConfig


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
