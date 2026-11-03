"""Esoterica tests never touch the network, never see a key, never spend credits."""
import pytest
import requests


def _blocked(*args, **kwargs):
    raise RuntimeError("network disabled in tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", _blocked)
    monkeypatch.setattr(requests, "request", _blocked)
    # a key in the developer's shell must never reach a test
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    yield
