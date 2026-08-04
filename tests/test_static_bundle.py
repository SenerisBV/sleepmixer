"""The compiled Elm bundle has to actually ship and actually be referenced.

Both halves have burned this project before: an editable install hid a missing
package declaration until a wheel was built, and a placeholder page shipped
looking like a finished one.

And a third, which is what the class-coverage test below is for: `index.html`
was written for a health-check page and then never grew as later tasks added
markup. Eleven of the fourteen classes the views emitted had no rule at all,
including the progress bar the whole branch existed to deliver — an empty div
with no height, no background and no colour, rendering as literally nothing.
Six per-task reviews passed, because a review reads a diff and the missing
thing was in a file the diff never touched. Nobody in the loop that writes this
code can open a browser; this test is the substitute for eyes.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sleepmix
from sleepmix.server.app import create_app

STATIC = Path(sleepmix.__file__).resolve().parent / "static"
UI_SRC = Path(sleepmix.__file__).resolve().parent.parent / "ui" / "src"


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
    assert "audio.js" in html
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


@pytest.mark.parametrize("filename", ["events.js", "audio.js"])
def test_the_served_ports_module_matches_its_source(filename):
    """`sleepmix/static/{events,audio}.js` are copies, and the copies are what ship.

    `ui/ports/events.js` and `ui/ports/audio.js` are the files anyone edits and
    the files `ui/README.md` documents; `make ui` copies each next to the
    bundle because that is what the page loads. Nothing but this compares
    them, so a change made to a copy — or a `make ui` nobody ran — leaves two
    versions of the port layer in the repository with the served one silently
    winning.
    """
    root = Path(sleepmix.__file__).resolve().parent.parent
    source = (root / "ui" / "ports" / filename).read_bytes()
    served = (STATIC / filename).read_bytes()
    assert served == source, (
        f"sleepmix/static/{filename} has drifted from ui/ports/{filename} — "
        f"edit ui/ports/{filename} and run `make ui`"
    )


# `class "a b"`, and `A.class "a"` for the SVG module's qualified import. The
# optional paren catches `class ("a " ++ …)`, which nothing writes today and
# `test_no_class_name_is_assembled_at_runtime` exists to keep that way.
CLASS_LITERAL = re.compile(r'\bclass\s*\(?\s*"([^"]*)"')

# A `class` applied to anything that is not a string literal. The whitespace is
# what keeps `exposing (class, disabled)` and `exposing (class)` out of it.
CLASS_APPLIED_TO_SOMETHING_ELSE = re.compile(r'\bclass\s+(?!")')


def _elm_sources():
    sources = sorted(UI_SRC.rglob("*.elm"))
    assert sources, f"no Elm sources under {UI_SRC} — the scan would pass vacuously"
    return sources


def _code_only(text: str) -> str:
    """`text` with its comments blanked out, keeping every newline.

    Both scans below would otherwise read prose: `Main.elm`'s own docstring
    says the compiler "turns a whole class of mistakes into build failures",
    which is a `class` applied to something that is not a string literal, and
    a class name mentioned in a comment is not a class name anything emits.
    Blanking rather than deleting so reported line numbers still point at the
    line the offender is on."""
    out = []
    i, n, depth = 0, len(text), 0
    while i < n:
        if depth:
            if text.startswith("{-", i):
                depth += 1
                i += 2
            elif text.startswith("-}", i):
                depth -= 1
                i += 2
            else:
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
        elif text.startswith("{-", i):
            depth = 1
            i += 2
        elif text.startswith("--", i):
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif text[i] == '"':
            # Copied through, escapes and all: string literals are the thing
            # being looked for, and a `--` inside one is not a comment.
            out.append('"')
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i:i + 2])
                    i += 2
                    continue
                out.append(text[i])
                i += 1
                if text[i - 1] in ('"', "\n"):
                    break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _emitted_class_names():
    names = set()
    for path in _elm_sources():
        for match in CLASS_LITERAL.finditer(_code_only(path.read_text())):
            names.update(match.group(1).split())
    return names


def test_every_class_the_views_emit_has_a_rule_on_the_page():
    """A class with no rule is not a cosmetic problem — it is an invisible element.

    `.progress-fill` is the case that proves it: an empty div carrying nothing
    but an inline width, which without a height and a colour occupies no space
    and paints nothing. The compiler cannot see this — a class name is a
    string on one side and a stylesheet on the other — so nothing but this
    connects them."""
    css = (STATIC / "index.html").read_text()
    names = _emitted_class_names()
    assert len(names) > 10, "the scan found suspiciously few classes; check the regex"
    missing = sorted(
        name for name in names
        if not re.search(rf"\.{re.escape(name)}(?![\w-])", css)
    )
    assert not missing, (
        "these classes are emitted by ui/src and have no rule in "
        f"sleepmix/static/index.html, so whatever they style is unstyled — "
        f"and an empty div among them renders as nothing at all: {missing}"
    )


def test_no_class_name_is_assembled_at_runtime():
    """The coverage scan above reads string literals, and only those.

    `class (prefix ++ suffix)` or `classList` would slip a class name past it
    silently, which is the same hole the missing rules went through the first
    time. Both spellings are one `if` away from two literals — see
    `Page.Mixer`'s solo button — so the cost of this rule is a line, and what
    it buys is that the scan cannot be wrong by omission."""
    offenders = []
    for path in _elm_sources():
        text = _code_only(path.read_text())
        for pattern in (CLASS_APPLIED_TO_SOMETHING_ELSE, re.compile(r"\bclassList\b")):
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "class names must be written as string literals so they can be checked "
        f"against the stylesheet; these are built some other way: {offenders}"
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
