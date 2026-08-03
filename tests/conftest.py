"""Keep the whole test suite off the operator's real data directory.

``autouse`` means every test gets an isolated SLEEPMIX_DATA_DIR whether it asks
for one or not — the separation cache and (later) the library database must
never touch real files during a test run.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "sleepmix-data"))
    yield
