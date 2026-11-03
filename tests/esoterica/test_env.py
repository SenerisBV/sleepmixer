import pytest

from sleepmix.esoterica.env import api_key, load_env


def test_load_env_parses(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# a comment\n\nA_KEY=abc\n  B_KEY = 'quoted' \nexport C=3\n"
                 "D=has=equals\nnot a line\n")
    assert load_env(p) == {"A_KEY": "abc", "B_KEY": "quoted", "C": "3", "D": "has=equals"}


def test_load_env_missing_file(tmp_path):
    assert load_env(tmp_path / "nope") == {}


def test_env_var_wins(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("ELEVENLABS_API_KEY=from-file\n")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert api_key("ELEVENLABS_API_KEY", p) == "from-env"


def test_falls_back_to_file(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("CARTESIA_API_KEY=from-file\n")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    assert api_key("CARTESIA_API_KEY", p) == "from-file"


def test_missing_key_names_key_only(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("OTHER_KEY=super-secret-value\n")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    with pytest.raises(KeyError) as e:
        api_key("CARTESIA_API_KEY", p)
    assert "CARTESIA_API_KEY" in str(e.value)
    assert "super-secret-value" not in str(e.value) + repr(e.value)
