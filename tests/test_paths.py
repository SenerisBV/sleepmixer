import os

from sleepmix import paths


def test_data_dir_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "custom"))
    assert paths.data_dir() == tmp_path / "custom"


def test_data_dir_is_created(tmp_path, monkeypatch):
    target = tmp_path / "made" / "here"
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(target))
    assert paths.data_dir().is_dir()


def test_cache_dir_lives_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert paths.cache_dir().parent == tmp_path
    assert paths.cache_dir().is_dir()


def test_default_data_dir_is_absolute_and_not_cwd(monkeypatch):
    monkeypatch.delenv("SLEEPMIX_DATA_DIR", raising=False)
    d = paths.data_dir()
    assert d.is_absolute()
    assert d != os.getcwd()
