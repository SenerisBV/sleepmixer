import dataclasses

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


def test_the_default_config_publishes_every_top_level_section(client):
    """Equality-based round-tripping alone cannot catch a route that omits
    whole sections. ``MixConfig.from_dict`` merges forgivingly — any key
    missing from the response falls back to the dataclass default — so a
    handler that returned only ``seed``/``separation_model``/``stems`` and
    silently dropped ``loop``, ``tempo``, ``reverb``, ``soundbed`` and
    ``output`` would still satisfy ``MixConfig.from_dict(body) == MixConfig()``,
    because the missing sections resolve to exactly the defaults being
    compared against. Deriving the expected key set from the dataclass, rather
    than writing it out, means a field added to ``MixConfig`` later cannot
    silently stop being published: this test starts failing the moment the
    route and the dataclass disagree, which is the property worth having."""
    body = client.get("/api/config/default").json()
    assert set(body) == {f.name for f in dataclasses.fields(MixConfig)}


def test_the_default_config_carries_the_curated_stem_list(client):
    """The whole reason this exists: the schema cannot describe a list, so the
    per-stem shaping the CLI uses is invisible to a schema-driven mixer."""
    stems = {s["name"]: s for s in client.get("/api/config/default").json()["stems"]}
    assert stems["drums"]["enabled"] is False
    assert stems["bass"]["decay"]["enabled"] is False
    assert stems["vocals"]["decay"]["curve"] == "exp"
    assert stems["vocals"]["decay"]["lowpass_end_hz"] == 2200
