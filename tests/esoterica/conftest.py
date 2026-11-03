"""Esoterica tests never touch the network and never spend credits."""
import pytest
import requests


def _blocked(*args, **kwargs):
    raise RuntimeError("network disabled in tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", _blocked)
    monkeypatch.setattr(requests, "request", _blocked)
    yield
