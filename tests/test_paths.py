from pathlib import Path

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


def test_platform_data_dir_is_absolute_and_not_cwd():
    """Assert on the default location without creating it.

    ``_platform_data_dir`` is a pure resolver — it does no I/O — so this checks
    the default is a real per-user path without writing anything into the
    operator's actual home. Calling ``data_dir()`` here instead would create
    that directory for real, which the suite must never do.
    """
    d = paths._platform_data_dir()
    assert d.is_absolute()
    assert d != Path.cwd()
