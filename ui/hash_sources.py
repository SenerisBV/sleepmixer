#!/usr/bin/env python3
"""Print a hash of everything that goes into the Elm bundle.

`sleepmix/static/app.js` is committed, so it can drift from the sources it was
built from and nothing would notice. The Makefile records this hash beside the
bundle and a test recomputes it — mtimes cannot do the job, because a fresh
clone gives every file the same checkout time in arbitrary order.

Both the build and the test invoke *this* script, so there is no second
implementation to disagree with.
"""
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    inputs = sorted((ROOT / "ui" / "src").rglob("*.elm"))
    inputs += [ROOT / "ui" / "elm.json", ROOT / "ui" / "ports" / "events.js"]
    digest = hashlib.sha256()
    for path in inputs:
        # Include the name: renaming a module changes the bundle even when the
        # bytes of every file are unchanged.
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    print(digest.hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
