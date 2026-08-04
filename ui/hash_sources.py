#!/usr/bin/env python3
"""Print a hash of the Elm bundle: both what goes into it and what comes out.

`sleepmix/static/app.js` is committed, so it can drift from the sources it was
built from and nothing would notice. The Makefile records this hash beside the
bundle and a test recomputes it — mtimes cannot do the job, because a fresh
clone gives every file the same checkout time in arbitrary order.

The *outputs* are hashed as well as the inputs, and that is not redundant.
Hashing inputs alone answers "have the sources changed since the last build",
which leaves two ways to commit a bundle nobody would notice:

* `make ui-dev` writes an `elm make --debug` build over `app.js` and correctly
  leaves the recorded hash alone — so a 326 KB debug bundle carrying the
  time-travelling debugger passed the entire test suite.
* `sleepmix/static/events.js` is a copy of `ui/ports/events.js` and is the file
  actually served. Editing the copy changed nothing any check looked at.

Including `app.js` and `events.js` in the digest makes both a test failure.
(The second is also asserted directly, byte for byte, in
`tests/test_static_bundle.py` — a hash says "something moved", the byte compare
says which file and in which direction.)

Both the build and the test invoke *this* script, so there is no second
implementation to disagree with.
"""
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

STATIC = ROOT / "sleepmix" / "static"

# The build outputs, in the order they are written. Listed explicitly rather
# than globbed: `index.html` lives in the same directory and is hand-edited,
# not built, so folding it in would make every stylesheet tweak look like a
# stale bundle.
OUTPUTS = [STATIC / "app.js", STATIC / "events.js"]


def main() -> int:
    inputs = sorted((ROOT / "ui" / "src").rglob("*.elm"))
    inputs += [ROOT / "ui" / "elm.json", ROOT / "ui" / "ports" / "events.js"]
    digest = hashlib.sha256()
    for path in inputs + OUTPUTS:
        # Include the name: renaming a module changes the bundle even when the
        # bytes of every file are unchanged.
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    print(digest.hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
