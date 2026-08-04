# The Elm bundle is a committed artefact: `pip install sleepmix` must not need
# Node or Elm. Rebuild it with `make ui` after changing anything under ui/.

ELM_SOURCES := $(shell find ui/src -name '*.elm')

.PHONY: ui ui-dev test

ui: sleepmix/static/app.js sleepmix/static/events.js

sleepmix/static/app.js: $(ELM_SOURCES) ui/elm.json ui/ports/events.js
	cd ui && elm make src/Main.elm --optimize --output=../sleepmix/static/app.js
	python3 ui/hash_sources.py > sleepmix/static/app.js.sha256

sleepmix/static/events.js: ui/ports/events.js
	cp ui/ports/events.js sleepmix/static/events.js

ui-dev:
	cd ui && elm make src/Main.elm --debug --output=../sleepmix/static/app.js

test:
	pipenv run pytest -q
