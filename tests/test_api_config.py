import pytest
from fastapi.testclient import TestClient

from sleepmix.config import MixConfig
from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_the_default_config_round_trips_through_from_dict(client):
    """The route is only useful if what it returns is something the server
    will accept back. A shape that describes the defaults but cannot be posted
    to /api/preview would be worse than no route."""
    body = client.get("/api/config/default").json()
    assert MixConfig.from_dict(body) == MixConfig()


def test_the_default_config_carries_the_curated_stem_list(client):
    """The whole reason this exists: the schema cannot describe a list, so the
    per-stem shaping the CLI uses is invisible to a schema-driven mixer."""
    stems = {s["name"]: s for s in client.get("/api/config/default").json()["stems"]}
    assert stems["drums"]["enabled"] is False
    assert stems["bass"]["decay"]["enabled"] is False
    assert stems["vocals"]["decay"]["curve"] == "exp"
    assert stems["vocals"]["decay"]["lowpass_end_hz"] == 2200
