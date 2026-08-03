import subprocess
import sys

from fastapi.testclient import TestClient

import sleepmix
from sleepmix.server.app import create_app


def test_health_reports_status_and_version():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    # Subset rather than exact equality: Task 6 adds a "warm" field, and a
    # health endpoint growing a key should not break an unrelated test.
    assert body["status"] == "ok"
    assert body["version"] == sleepmix.__version__


def test_unknown_api_route_is_404():
    client = TestClient(create_app())
    assert client.get("/api/nope").status_code == 404


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
