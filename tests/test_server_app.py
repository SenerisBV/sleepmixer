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
    just as much loopback as `127.0.0.1` — the whole `127.0.0.0/8` block is.
    `""` belongs in the *rejected* group even though it looks like a natural
    default: passed to uvicorn it binds every interface, exactly like
    `0.0.0.0`/`::` — this same module's browser-URL logic already treats it
    that way, so the loopback check must agree rather than let `--host ""`
    slip past the refusal."""
    from sleepmix.cli import _is_loopback

    for host in ("127.0.0.1", "127.0.0.2", "localhost", "::1",
                 "0:0:0:0:0:0:0:1", "[::1]"):
        assert _is_loopback(host), host
    for host in ("", "0.0.0.0", "::", "192.168.1.5", "example.com", "not-an-ip"):
        assert not _is_loopback(host), host


def test_ui_refuses_an_empty_host_without_the_flag():
    """`--host ""` binds every interface (uvicorn's own default-empty
    behaviour, and what this file's browser-URL logic already assumes) — it
    must be refused exactly like `0.0.0.0`, not treated as a loopback no-op."""
    from click.testing import CliRunner

    from sleepmix.cli import main

    result = CliRunner().invoke(main, ["ui", "--host", "", "--no-open"])
    assert result.exit_code != 0
    assert "--allow-remote" in result.output


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


def test_a_rebound_host_header_is_rejected():
    """DNS rebinding is the live vector for a loopback service.

    Binding 127.0.0.1 stops other machines connecting; it does not stop a page
    the operator visits from re-resolving `evil.example` to 127.0.0.1 and
    becoming same-origin with this API. Such a request still carries the
    attacker's hostname in `Host`, which is the one thing that distinguishes it
    from a genuine local one — and the surface it reaches is no longer
    read-only: `POST /api/renders` costs minutes of CPU and a ~300 MB file per
    request, with no rate limit and no delete path."""
    with TestClient(create_app()) as client:
        r = client.get("/api/health", headers={"Host": "evil.example"})
        assert r.status_code == 400


def test_the_loopback_spellings_and_the_test_host_are_allowed():
    """A browser can send any of these for a loopback bind, and `TestClient`
    sends `testserver` — the reason an allow-list was deferred rather than
    added. All four must pass, or this middleware breaks ordinary local use."""
    with TestClient(create_app()) as client:
        for host in ("localhost", "localhost:8765", "127.0.0.1",
                     "127.0.0.1:8765", "[::1]:8765", "testserver"):
            r = client.get("/api/health", headers={"Host": host})
            assert r.status_code == 200, f"{host} -> {r.status_code}"


def test_the_allow_list_is_a_parameter():
    """`cli.py` passes the bound host, so `--allow-remote` still works."""
    app = create_app(allowed_hosts=["studio.local", "testserver"])
    with TestClient(app) as client:
        assert client.get("/api/health",
                          headers={"Host": "studio.local"}).status_code == 200
        assert client.get("/api/health",
                          headers={"Host": "localhost"}).status_code == 400


def test_ui_passes_the_bound_host_into_the_allow_list(monkeypatch):
    """A remote bind that rejected its own hostname would be unusable."""
    from click.testing import CliRunner

    from sleepmix.cli import main

    seen = {}

    def fake_create_app(*args, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr("sleepmix.server.app.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    result = CliRunner().invoke(
        main, ["ui", "--host", "192.168.1.5", "--allow-remote", "--no-open"])
    assert result.exit_code == 0, result.output
    assert "192.168.1.5" in seen["allowed_hosts"]
    assert "127.0.0.1" in seen["allowed_hosts"]

    seen.clear()
    result = CliRunner().invoke(
        main, ["ui", "--host", "0.0.0.0", "--allow-remote", "--no-open"])
    assert result.exit_code == 0, result.output
    # A wildcard bind cannot enumerate its own reachable hostnames, so it opts
    # out rather than allow one arbitrary spelling and reject the rest.
    assert seen["allowed_hosts"] == ["*"]


def test_a_missing_host_header_is_rejected():
    """No `Host` is not a pass. HTTP/1.1 requires one; anything without it is
    either malformed or deliberately probing what the allow-list skips."""
    from sleepmix.server.app import _HostAllowList, _host_without_port

    assert _host_without_port("") not in {"localhost", "127.0.0.1"}
    allow = _HostAllowList(app=None, allowed_hosts=["localhost"])
    assert not allow.allow_any


def test_host_parsing_handles_every_shape():
    """The parse `TrustedHostMiddleware` gets wrong is the reason this is ours.

    `"[::1]:8765".split(":")[0]` is `"["`, and `"::1".split(":")[0]` is `""` —
    so an IPv6 literal cannot be allow-listed there however it is spelled,
    which would 400 every request from `sleepmix ui --host ::1`."""
    from sleepmix.server.app import _host_without_port

    cases = {
        "localhost": "localhost",
        "localhost:8765": "localhost",
        "127.0.0.1": "127.0.0.1",
        "127.0.0.1:8765": "127.0.0.1",
        "[::1]": "::1",
        "[::1]:8765": "::1",
        "[0:0:0:0:0:0:0:1]:8765": "0:0:0:0:0:0:0:1",
        "LOCALHOST:8765": "localhost",
        " testserver ": "testserver",
        "": "",
    }
    for raw, expected in cases.items():
        assert _host_without_port(raw) == expected, raw


def test_an_ipv6_loopback_bind_answers_its_own_browser_url():
    """`cli.py` opens `http://[::1]:8765/` for `--host ::1`, so that exact
    `Host` must be accepted — end to end, not just in the parser."""
    with TestClient(create_app()) as client:
        for host in ("[::1]", "[::1]:8765"):
            assert client.get("/api/health",
                              headers={"Host": host}).status_code == 200, host
        assert client.get("/api/health",
                          headers={"Host": "[::2]:8765"}).status_code == 400


def test_the_all_extra_includes_the_ui_dependencies():
    """`pip install "sleepmix[all]"` then `sleepmix ui` is the install story the
    UI spec tells. Without fastapi/uvicorn in `all` it fails at the last step."""
    from pathlib import Path

    import sleepmix

    pyproject = (Path(sleepmix.__file__).resolve().parent.parent
                 / "pyproject.toml").read_text()
    line = next(ln for ln in pyproject.splitlines() if ln.startswith("all = ["))
    block = pyproject.split("all = [", 1)[1].split("]", 1)[0]
    assert "fastapi" in block, line
    assert "uvicorn" in block, line
