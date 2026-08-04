import subprocess
import sys

from fastapi.testclient import TestClient

import sleepmix
from sleepmix.server.app import create_app


def test_health_reports_status_and_version():
    with TestClient(create_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        # Subset rather than exact equality: Task 6 adds a "warm" field, and a
        # health endpoint growing a key should not break an unrelated test.
        assert body["status"] == "ok"
        assert body["version"] == sleepmix.__version__


def test_unknown_api_route_is_404():
    with TestClient(create_app()) as client:
        assert client.get("/api/nope").status_code == 404


def test_an_injected_store_outlives_the_app():
    """`create_app(store=...)` borrows a store; it must not close it.

    Closing a caller-owned store on shutdown made the injection point unusable:
    a second TestClient context over the same app rebound the now-closed
    connection and every query raised sqlite3.ProgrammingError."""
    from sleepmix.server.store import Store

    store = Store()
    try:
        app = create_app(store=store)
        with TestClient(app) as client:
            assert client.post("/api/songs", json={"path": "/nope.wav"}).status_code == 400
        # Second context over the same app: this is what used to blow up.
        with TestClient(app) as client:
            assert client.get("/api/songs").status_code == 200
        # And the caller's store is still the caller's, still open.
        song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0,
                              sample_rate=44100)
        assert store.get_song(song["id"])["title"] == "A"
    finally:
        store.close()


def test_an_injected_store_backs_the_routes():
    """The app must read and write the store it was handed, not a new one."""
    from sleepmix.server.store import Store

    store = Store()
    try:
        store.add_song(path="/tmp/injected.wav", title="Injected",
                       duration_s=1.0, sample_rate=44100)
        with TestClient(create_app(store=store)) as client:
            titles = [s["title"] for s in client.get("/api/songs").json()["songs"]]
        assert "Injected" in titles
    finally:
        store.close()


def test_core_imports_without_server_dependencies():
    """`import sleepmix` must not pull in fastapi.

    The server deps are an optional extra; someone who installed only the base
    package must still be able to use the CLI and the Python API."""
    code = (
        "import sys; import sleepmix; "
        "assert 'fastapi' not in sys.modules, sorted(m for m in sys.modules if 'fastapi' in m); "
        "print('clean')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "clean" in out.stdout


def test_ui_command_is_registered():
    from click.testing import CliRunner

    from sleepmix.cli import main

    result = CliRunner().invoke(main, ["ui", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output


def test_ui_refuses_a_non_loopback_bind_and_says_why():
    """The guard must fire before uvicorn.run — nothing may start listening.

    No server is started here: if the guard ever moved below `uvicorn.run`
    this test would hang rather than fail, which is itself the signal."""
    from click.testing import CliRunner

    from sleepmix.cli import main

    result = CliRunner().invoke(main, ["ui", "--host", "0.0.0.0", "--no-open"])
    assert result.exit_code != 0
    out = result.output.lower()
    assert "0.0.0.0" in result.output
    # It must name the consequence, not just say "not allowed".
    assert "read" in out and "authentication" in out
    assert "--allow-remote" in result.output


def test_is_loopback_accepts_every_spelling_and_rejects_look_alikes():
    """A string-set membership test gets these wrong; a real check must not.

    `0:0:0:0:0:0:0:1` is the fully-expanded form of `::1`, and `127.0.0.2` is
    just as much loopback as `127.0.0.1` — the whole `127.0.0.0/8` block is."""
    from sleepmix.cli import _is_loopback

    for host in ("127.0.0.1", "127.0.0.2", "localhost", "", "::1",
                 "0:0:0:0:0:0:0:1", "[::1]"):
        assert _is_loopback(host), host
    for host in ("0.0.0.0", "::", "192.168.1.5", "example.com", "not-an-ip"):
        assert not _is_loopback(host), host


def test_ui_accepts_an_ipv6_loopback_host_without_the_flag(monkeypatch):
    """The guard must not fire on `::1` — the exact spelling a naive
    string-set membership test used to reject."""
    from click.testing import CliRunner

    from sleepmix.cli import main

    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    result = CliRunner().invoke(main, ["ui", "--host", "::1", "--no-open"])
    assert result.exit_code == 0, result.output


def test_ui_help_documents_allow_remote():
    from click.testing import CliRunner

    from sleepmix.cli import main

    result = CliRunner().invoke(main, ["ui", "--help"])
    assert result.exit_code == 0
    assert "--allow-remote" in result.output


def test_subpackages_are_declared_for_distribution():
    """A non-editable install must include sleepmix.server and its children.

    The editable install used in development resolves imports from the source
    tree, so a missing package declaration is invisible here and only shows up
    as ModuleNotFoundError for whoever ran `pip install "sleepmix[ui]"`.
    Asserting on the declaration is the cheap proxy for building a wheel.
    """
    from pathlib import Path

    import sleepmix

    pyproject = Path(sleepmix.__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    assert "[tool.setuptools.packages.find]" in text
    assert 'include = ["sleepmix*"]' in text
