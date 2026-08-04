import pytest
from fastapi.testclient import TestClient

from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_create_and_list(client):
    r = client.post("/api/presets",
                    json={"name": "Slow", "config": {"tempo": {"speed": 0.5}}})
    assert r.status_code == 201
    assert r.json()["config"]["tempo"]["speed"] == 0.5
    names = [p["name"] for p in client.get("/api/presets").json()["presets"]]
    assert names == ["Slow"]


def test_duplicate_names_are_rejected(client):
    client.post("/api/presets", json={"name": "Slow", "config": {}})
    r = client.post("/api/presets", json={"name": "Slow", "config": {}})
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_delete(client):
    created = client.post("/api/presets", json={"name": "Slow", "config": {}}).json()
    assert client.delete(f"/api/presets/{created['id']}").status_code == 204
    assert client.get("/api/presets").json()["presets"] == []


def test_deleting_an_unknown_preset_404s(client):
    assert client.delete("/api/presets/nope").status_code == 404


def test_an_invalid_config_is_rejected_on_save(client):
    """Saving a preset that could never render is worse than refusing it."""
    r = client.post("/api/presets", json={"name": "Bad", "config": {"seed": -1}})
    assert r.status_code == 400
    assert "seed" in r.json()["detail"].lower()
