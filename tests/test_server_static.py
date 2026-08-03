import pytest
from fastapi.testclient import TestClient

from sleepmix.server.app import create_app
from sleepmix.server.warmup import warm_analysis


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_root_serves_the_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "sleepmix" in r.text.lower()


def test_health_reports_warm_state(client):
    assert "warm" in client.get("/api/health").json()


def test_warm_analysis_sets_the_flag_and_is_idempotent():
    """Must not raise even when librosa is absent — it is an optional dep.

    Reaches into ``_warmed`` because module-level memoization is exactly what
    is under test: without resetting it, whichever test ran first would have
    already warmed the module and this would assert nothing."""
    from sleepmix.server import warmup

    warmup._warmed = False
    assert warmup.is_warm() is False
    warm_analysis()
    assert warmup.is_warm() is True
    warm_analysis()  # second call must be a no-op, not an error
    assert warmup.is_warm() is True


def test_warm_analysis_makes_the_next_loop_search_fast():
    import time

    import numpy as np

    from sleepmix.analysis import find_loop
    from sleepmix.audio import AudioBuffer
    from sleepmix.config import LoopConfig

    warm_analysis()
    sr = 22050
    t = np.arange(sr * 4) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    buf = AudioBuffer(np.stack([y, y], axis=1), sr)

    start = time.perf_counter()
    find_loop(buf, LoopConfig())
    assert time.perf_counter() - start < 5.0
