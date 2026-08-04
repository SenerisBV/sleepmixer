# The Elm bundle is a committed artefact: `pip install sleepmix` must not need
# Node or Elm. Rebuild it with `make ui` after changing anything under ui/.
#
# `ui` is phony and rebuilds unconditionally rather than being a file target
# with prerequisites. `elm make` takes about a second, and mtime-driven
# rebuilding was actively wrong here: `make ui-dev` writes a --debug bundle over
# `app.js`, which then looks *newer* than every source, so a following `make ui`
# would skip the compile and only re-record the hash — stamping the debug build
# as current. The same reasoning applies to the events.js copy, which `make`
# would decline to refresh whenever someone edited the copy instead of the
# original.

.PHONY: ui ui-dev test

ui:
	cd ui && elm make src/Main.elm --optimize --output=../sleepmix/static/app.js
	cp ui/ports/events.js sleepmix/static/events.js
	python3 ui/hash_sources.py > sleepmix/static/app.js.sha256

ui-dev:
	cd ui && elm make src/Main.elm --debug --output=../sleepmix/static/app.js

test:
	pipenv run pytest -q
