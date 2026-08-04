"""The compiled Elm bundle has to actually ship and actually be referenced.

Both halves have burned this project before: an editable install hid a missing
package declaration until a wheel was built, and a placeholder page shipped
looking like a finished one.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sleepmix
from sleepmix.server.app import create_app

STATIC = Path(sleepmix.__file__).resolve().parent / "static"


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_the_compiled_bundle_is_present_and_not_empty():
    app_js = STATIC / "app.js"
    assert app_js.is_file(), "run `make ui` — the bundle is a committed artefact"
    assert app_js.stat().st_size > 10_000, "suspiciously small for a compiled Elm app"


def test_the_page_references_the_bundle_and_the_ports():
    html = (STATIC / "index.html").read_text()
    assert "app.js" in html
    assert "events.js" in html
    assert "Elm.Main.init" in html


def test_the_page_is_no_longer_the_placeholder():
    html = (STATIC / "index.html").read_text().lower()
    assert "placeholder" not in html


def test_the_server_serves_the_bundle(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


def test_the_root_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_the_served_ports_module_matches_its_source():
    """`sleepmix/static/events.js` is a copy, and the copy is what ships.

    `ui/ports/events.js` is the file anyone edits and the file `ui/README.md`
    documents; `make ui` copies it next to the bundle because that is what the
    page loads. Nothing but this compares them, so a change made to the copy —
    or a `make ui` nobody ran — leaves two versions of the port layer in the
    repository with the served one silently winning.
    """
    root = Path(sleepmix.__file__).resolve().parent.parent
    source = (root / "ui" / "ports" / "events.js").read_bytes()
    served = (STATIC / "events.js").read_bytes()
    assert served == source, (
        "sleepmix/static/events.js has drifted from ui/ports/events.js — "
        "edit ui/ports/events.js and run `make ui`"
    )


def test_the_bundle_is_not_stale_relative_to_the_sources():
    """A committed artefact silently drifts from its source.

    Compares a content hash rather than mtimes: after a fresh `git clone` every
    file carries checkout time in arbitrary order, so an mtime comparison would
    flake for anyone but the person who built it. Invokes the same script the
    Makefile uses, so the two sides cannot compute the hash differently.

    The hash covers the built `app.js` and `events.js` as well as the sources
    they came from, which is what makes a committed `make ui-dev` bundle fail
    here: a `--debug` build changes nothing on the input side, so an
    inputs-only hash matched it exactly.
    """
    import subprocess
    import sys

    root = Path(sleepmix.__file__).resolve().parent.parent
    recorded = (STATIC / "app.js.sha256").read_text().strip()
    current = subprocess.run(
        [sys.executable, str(root / "ui" / "hash_sources.py")],
        capture_output=True, text=True, check=True, cwd=root).stdout.strip()
    assert recorded == current, "app.js is stale — run `make ui` and commit the result"
