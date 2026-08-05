# Plan 3f: legibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mixer explain itself to someone who did not write it, and stop `docs/project-state.md` asserting things that are no longer true.

**Architecture:** The schema pipeline already carries per-field `help` from `sleepmix/config.py` to the mixer, so most of this is content written in Python that appears in the interface with no frontend change. What the frontend must change is the surfacing — every help string is currently a hover tooltip — and the schema must gain a per-section description, which is the piece that does not exist yet.

**Tech Stack:** Python 3.11 / FastAPI · Elm 0.19.2 · pytest · elm-test

**Spec:** `docs/superpowers/specs/2026-08-05-legibility-design.md`

## Global Constraints

- **`pipenv` runs only from `/Users/moopius/projects/sleepmixer`. Never `cd` elsewhere first** — pipenv keys its virtualenv to the directory path, and `cd`-ing first silently creates a new empty virtualenv.
- **`elm` and `elm-test` run from `ui/`**, so `cd ui` is correct for those. These are two different rules; do not conflate them.
- Elm 0.19.2. **No new Elm packages, no npm dependencies, no CSS framework.** `Test.Html.*` ships with the already-declared `elm-explorations/test`.
- **No new Python dependencies.**
- **No `Debug.toString` or `Debug.log` anywhere under `ui/src`** — `elm make --optimize` refuses to build with them, so `make ui` fails. Allowed under `ui/tests`.
- **`make ui` from the repository root** rebuilds `sleepmix/static/app.js` and rewrites the hash. Run it and commit whatever it produces; a Python test recomputes the hash.
- **Every class emitted from `ui/src` must have a CSS rule in `sleepmix/static/index.html`.** `tests/test_static_bundle.py` enforces it and **must not be weakened** — it reads only `<style>` blocks, strips comments, requires selector position, and rejects a rule that exists only inside an at-rule or with an empty body.
- **Nothing in the audio path moves.** No change to `sleepmix/pipeline.py`, `sleepmix/disintegration.py`, `sleepmix/preview.py`'s `render_window`, or the order of any DSP operation. Task 5 touches one cache key; Task 6 measures and writes prose. If a task seems to require an audio change, it is out of scope — say so rather than making it.
- **No browser automation, AppleScript, screenshots, or browser-driver MCPs.** A prior implementer drove GUI automation against the operator's real desktop and tripped a macOS TCC dialog over a Finder window holding a private key, invoices and a CV. Verify with curl.
- **Every server you start uses `SLEEPMIX_DATA_DIR=$(mktemp -d)`** and is killed afterwards. A prior implementer wrote into the operator's real music library before noticing.
- **Demucs is genuinely installed on this machine**, so `POST /api/songs/{id}/separate` starts a multi-minute run. Use `tests/stub_separation_worker.py`, or write a stem cache directly with `sleepmix.separation._write_cache`.
- Baseline at plan start: **288 Python tests** (plus one marked `slow`), **415 Elm tests**.

---

## Notes for whoever executes this

**This plan's deliverable is mostly prose, and prose about DSP is easy to get wrong.** Every sentence written into a docstring or a `help` string must be checked against the code it describes. This project has already shipped a documentation claim contradicted by the same diff that introduced it. A reviewer should reject any sentence whose truth cannot be traced to a specific line.

**The decay pipeline, verified, because four tasks depend on describing it accurately.** `disintegration.apply_decay` applies, in this order, each parameter linearly interpolated from its `_start` to its `_end` value across the arc:

1. `_lowpass` — zero-phase Butterworth, cutoff lerped `lowpass_start_hz` → `lowpass_end_hz`
2. `_spectral_holes` — fraction lerped `spectral_hole_start` → `spectral_hole_end`
3. `_apply_dropouts` — "brief, smoothly-ramped gaps (tape dropouts)", density lerped `dropout_start` → `dropout_end`
4. amplitude — lerped `amp_start_db` → `amp_end_db`
5. broadband noise — `rng.standard_normal` scaled by an amplitude lerped `noise_start_db` → `noise_end_db`, skipped below 1e-6

**Task 4 is the only one that is not transcription.** It decides how the new text sits on screen without doubling the mixer's height. Dispatch it on a capable model.

---

## File structure

| File | Responsibility |
|---|---|
| `sleepmix/config.py` *(modify)* | The text. Seven docstrings and the `help` metadata; `config_schema()` publishes descriptions. |
| `ui/src/Schema.elm` *(modify)* | `Schema` and `Section` decode `description`. |
| `ui/src/Page/Mixer.elm` *(modify)* | Renders descriptions and help visibly; `Attr.title` goes. |
| `sleepmix/static/index.html` *(modify)* | Rules for the new classes. |
| `sleepmix/session.py` *(modify)* | `output.sample_rate` joins `_master_key`. |
| `docs/project-state.md` *(modify)* | The staleness pass and the corrected 1.82 dB entry. |

---

## Task 1: The schema publishes a description per section

**Files:**
- Modify: `sleepmix/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `GET /api/schema` gains a top-level `"description"` and a `"description"` on every entry in `"sections"`. Both are non-empty strings.

**Why a docstring rather than a metadata dict.** The text has one home. A `description=` argument on `_SECTION_TYPES` would put the explanation somewhere other than the thing it explains, and the two drift the first time someone edits the class without looking at the table.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
import dataclasses

from sleepmix.config import _SECTION_TYPES, config_schema


def test_every_section_carries_a_description():
    """A section with no description reaches the mixer as a heading and a row
    of controls with nothing saying what any of it is for. Derived from
    _SECTION_TYPES rather than written out, so a section added later fails
    here until somebody describes it."""
    schema = config_schema()
    for name in _SECTION_TYPES:
        assert schema["sections"][name]["description"].strip(), name


def test_the_top_level_carries_a_description():
    assert config_schema()["description"].strip()


def test_a_generated_dataclass_docstring_is_refused(monkeypatch):
    """dataclass writes a __doc__ that is just the constructor signature.
    Publishing that would put 'LoopConfig(bars: int = 8, ...)' on screen as
    though it explained something."""
    import sleepmix.config as cfg

    @dataclasses.dataclass
    class Undocumented:
        x: int = 1

    with pytest.raises(ValueError, match="Undocumented"):
        cfg._describe_type(Undocumented)
```

Check `tests/test_config.py` already imports `pytest`; add it if not.

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_config.py -k description -v`
Expected: FAIL — `KeyError: 'description'`.

- [ ] **Step 3: Implement the plumbing**

In `sleepmix/config.py`, add `import inspect` at the top and:

```python
def _describe_type(dc_type: type) -> str:
    """A section's own explanation, taken from the class it describes.

    Sourced from ``__doc__`` so the text lives with the thing it explains
    rather than in a table beside it, which is how the two come to disagree.

    ``dataclass`` synthesises a ``__doc__`` that is the constructor signature,
    and publishing that would put ``LoopConfig(bars: 'int' = 8, ...)`` on
    screen as though it meant something. That case raises instead: a section
    added without a description should fail loudly here rather than quietly
    render a heading with nothing under it."""
    doc = inspect.cleandoc(dc_type.__doc__ or "")
    if not doc or doc.startswith(f"{dc_type.__name__}("):
        raise ValueError(
            f"{dc_type.__name__} needs a docstring: it is published to the UI "
            f"as the section's description")
    return doc
```

and change `config_schema`:

```python
    return {
        "description": _describe_type(MixConfig),
        "fields": _describe_fields(MixConfig),
        "sections": {name: {"description": _describe_type(t),
                            "fields": _describe_fields(t)}
                     for name, t in _SECTION_TYPES.items()},
    }
```

- [ ] **Step 4: Write the seven docstrings**

These are the deliverable. Each must be true of the code — check every claim against the source before writing it, and against the decay-pipeline summary in this plan's notes.

`MixConfig`:

```python
    """Everything that decides what a finished mix sounds like.

    The mixer groups these two under "Mix": a seed that fixes the random parts
    of the decay so the same settings give the same mix twice, and the name of
    the model used to split the song into stems."""
```

`LoopConfig`:

```python
    """Which fragment of the song gets repeated, and how the repeats are joined.

    A mix is one loop played over and over for however long you asked for.
    Leave the start and end empty and a beat-aligned loop is found for you,
    somewhere between the search bounds; set them and that region is used
    exactly. Everything here is about choosing and joining the fragment — the
    eroding happens elsewhere."""
```

`TempoConfig`:

```python
    """How fast and how low the loop plays, before any of it erodes.

    Slowing a track down and dropping it a little is most of what makes it
    sound like it is somewhere else. This happens once, to the loop, and every
    repetition inherits it."""
```

`ReverbConfig`:

```python
    """The space the stems sit in.

    Applied to the whole mix rather than per stem, though each stem chooses
    how much of itself to send into it. Larger and wetter pushes the mix
    further away, which is usually what you want for something you intend to
    fall asleep to."""
```

`SoundbedConfig`:

```python
    """A continuous bed underneath the mix: noise, binaural tones, or both.

    Off by default. Mixed in when you render — previews never include it, so
    turning it on changes nothing you can hear in the mixer."""
```

`OutputConfig`:

```python
    """The shape of the finished file: how long, how loud, and how it starts
    and ends.

    Length is the one that matters most, because everything else in the config
    describes a journey and this says how long the journey takes."""
```

`StemConfig` — expand what is already there:

```python
    """One separated stem and how it should behave in the mix.

    Every stem the separation produced gets a row: whether it is in the mix at
    all, how loud, how much of it goes into the reverb, and its own decay
    settings. Stems erode independently, which is the point — vocals can
    dissolve while the bass stays put."""
```

`StemDecayConfig` — expand what is already there; this is the heart of the tool:

```python
    """How one stem falls apart across the length of the mix.

    Every value here is a pair: where the stem starts and where it ends up.
    The mix moves from one to the other in a straight line over however long
    you asked for, so the first minute sounds close to the start values and
    the last minute close to the end ones.

    Five things happen to a stem, in this order: treble is filtered away,
    notches are punched out of what is left, brief gaps are dropped in, the
    level falls, and noise is mixed in underneath."""
```

- [ ] **Step 5: Run the tests and commit**

```bash
pipenv run pytest -q -m "not slow"
git add sleepmix/config.py tests/test_config.py
git commit -m "feat: the schema describes each section"
```

---

## Task 2: Per-field help, where the name hides the effect

**Files:**
- Modify: `sleepmix/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a `help` entry in the `metadata` of each field named below. No schema shape change — `help` is already published.

**The rule, and the reason for it.** Write help where the field's name states a **mechanism** and not an **outcome**. "Gain, in decibels" under a control labelled *Gain (dB)* is words without information, and a screen full of those teaches a reader to skip all of them — including the four that matter.

**The omissions are deliberate and should be defended, not quietly filled in.** `gain_db`, `enabled`, `reverb_send`, `sample_rate`, `channels`, `fade_in_s`, `fade_out_s`, `room_size`, `damping`, `wet`, `dry`, `width`, `predelay_ms`, `crossfade_ms`, `noise_type` and `noise_gain_db` get nothing, because their labels already say what they do. A reviewer will see fields without help and reach for "incomplete"; the answer is that this list is a judgement about what a newcomer needs, and adding the other thirty-one sentences would make the four that matter harder to find rather than easier.

`separation_model` is excluded for a different reason: the mixer deliberately withholds a control for it, because changing it nulls the session's stems and triggers a multi-minute Demucs run inside the preview lock.

- [ ] **Step 1: Write the failing test**

```python
NEEDS_HELP = {
    "stem_decay": [
        "lowpass_start_hz", "lowpass_end_hz",
        "amp_start_db", "amp_end_db",
        "dropout_start", "dropout_end",
        "spectral_hole_start", "spectral_hole_end",
        "noise_start_db", "noise_end_db",
    ],
    "loop": ["bars", "beats_per_bar"],
    "output": ["peak_db"],
    "soundbed": ["binaural_carrier_hz", "binaural_beat_hz", "binaural_gain_db"],
}


def test_the_fields_whose_names_hide_their_effect_carry_help():
    """These are the controls a newcomer cannot guess from the label. The list
    is deliberate and short: help on a field whose label already says it
    teaches readers to skip the ones that matter."""
    sections = config_schema()["sections"]
    for section, names in NEEDS_HELP.items():
        for name in names:
            assert sections[section]["fields"][name].get("help", "").strip(), \
                f"{section}.{name}"


def test_help_says_something_the_label_does_not():
    """A help string that restates the label is worse than none — it adds
    height without information."""
    sections = config_schema()["sections"]
    for section, names in NEEDS_HELP.items():
        for name in names:
            aField = sections[section]["fields"][name]
            assert aField["help"].strip().lower() != aField["label"].strip().lower()
            assert len(aField["help"]) > len(aField["label"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_config.py -k help -v`
Expected: FAIL on the first `stem_decay` field.

- [ ] **Step 3: Write the help text**

Add `"help"` to each named field's `metadata`. **Check each sentence against `sleepmix/disintegration.py` before writing it** — the plan's notes carry the verified pipeline. Suggested text, to be corrected wherever the source disagrees:

- `lowpass_start_hz` — "How much treble the stem still has at the beginning. Everything above this is filtered away."
- `lowpass_end_hz` — "How much treble is left by the end. This does more than anything else here to make a stem recede into the distance."
- `spectral_hole_start` / `_end` — "How much of the stem's frequency range is punched out, at the beginning / by the end. Unlike the lowpass, this removes bands from the middle rather than the top."
- `dropout_start` / `_end` — "How often brief gaps are dropped into the stem, at the beginning / by the end. They are smoothly ramped, like tape dropouts, not hard cuts."
- `amp_start_db` / `_end_db` — "How loud the stem is at the beginning / by the end, relative to where it started."
- `noise_start_db` / `_end_db` — "How much noise is mixed in underneath, at the beginning / by the end. Added after everything else, so it does not get filtered."
- `loop.bars` / `beats_per_bar` — "Together these decide how long the repeated fragment is, in musical rather than clock time — eight bars of four beats at the detected tempo."
- `output.peak_db` — "The ceiling the finished file is normalised to. Headroom, not loudness: it is how close the loudest moment gets to clipping."
- `binaural_carrier_hz` — "The tone each ear hears. **Requires headphones** — binaural beats work by giving each ear a slightly different pitch, and speakers mix them back together."
- `binaural_beat_hz` — "The difference between the two ears' tones, which is what you perceive as a slow pulse. **Requires headphones.**"
- `binaural_gain_db` — "How loud the binaural tones are under the mix. **Requires headphones.**"

Match the existing metadata style in the file — check whether other `help` strings use plain text or any markup, and follow it. If they are plain text, write the headphone warnings as plain sentences rather than with asterisks.

- [ ] **Step 4: Run the tests and commit**

```bash
pipenv run pytest -q -m "not slow"
git add sleepmix/config.py tests/test_config.py
git commit -m "feat: help on the controls whose names hide their effect"
```

---

## Task 3: Elm decodes the descriptions

**Files:**
- Modify: `ui/src/Schema.elm`
- Test: `ui/tests/SchemaTest.elm`

**Interfaces:**
- Consumes: `GET /api/schema`'s new `description` keys (Task 1).
- Produces:

```elm
type alias Section =
    { description : String, fields : Dict String Field }

type alias Schema =
    { description : String, fields : Dict String Field, sections : Dict String Section }
```

**A missing description must decode, not fail.** The server always sends it once Task 1 lands, and the bundle and the server ship together — but the decoder should not make them accidentally independent, and a section heading with no paragraph is a smaller failure than a mixer that will not load. Use `Decode.maybe` with `Maybe.withDefault ""`, and let the *Python* test be the thing that insists every section has one.

**Do not touch the `Field` union.** It is closed on purpose — a field type this application cannot render fails the decode loudly rather than rendering nothing — and this task adds nothing to it.

- [ ] **Step 1: Write the failing tests**

Extend `ui/tests/SchemaTest.elm`, reusing its existing captured fragments as string literals. Cover: a section with a description decodes it; a section **without** one decodes to `""` rather than failing; and the top-level description decodes.

**Capture the new shape from the running server rather than hand-writing it** — start `SLEEPMIX_DATA_DIR=$(mktemp -d) pipenv run sleepmix ui --no-open --port 8765`, `curl -s localhost:8765/api/schema`, paste a real section fragment in, and kill the server. Every decoder in this project has been built that way; the one fixture that was hand-edited to look captured had to be redone.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && elm-test`
Expected: FAIL to compile — `Section` has no `description`.

- [ ] **Step 3: Implement**

```elm
section : Decoder Section
section =
    Decode.map2 Section
        (Decode.map (Maybe.withDefault "") (Decode.maybe (Decode.field "description" Decode.string)))
        (Decode.field "fields" (Decode.dict field))
```

and the same treatment for the top level in `decoder`.

- [ ] **Step 4: Run, rebuild, commit**

```bash
cd ui && elm-test
cd /Users/moopius/projects/sleepmixer && make ui && pipenv run pytest -q -m "not slow"
git add ui sleepmix/static && git commit -m "feat: decode the schema's descriptions"
```

---

## Task 4: The mixer shows what it knows

**Files:**
- Modify: `ui/src/Page/Mixer.elm`, `sleepmix/static/index.html`
- Test: `ui/tests/MixerTest.elm`

**Interfaces:**
- Consumes: `Schema.Section.description` and `Schema.description` (Task 3); the `help` strings (Task 2).
- Produces: the finished feature. Nothing later depends on it.

**This is the task that is not transcription.** It decides how a paragraph per section and a line per control sit on screen without making the mixer unusable through sheer height.

**What must change:**

1. **`Attr.title` goes.** `Page/Mixer.elm:1700` is `help words = Attr.title (Maybe.withDefault "" words)` — a hover tooltip, invisible on touch, unreachable by keyboard, invisible to anyone not hovering the right element. Replaced with visible markup under the control it belongs to.
2. **Each section renders its description.** `section` (`:1419`) already builds `details [ class "section" ] [ summary … , sectionNote name, div [ class "fields" ] … ]`, so there is a slot. The description goes beside `sectionNote`, not instead of it — **`sectionNote` is a different kind of note** and must survive. It says what a change will *cost* ("changing the loop means finding and stretching it again, so the next preview takes as long as the first did") or that a section does not affect previews at all. The description says what the section is *for*. Both are worth having and neither substitutes for the other.
3. **The `mix` pseudo-section takes the schema's top-level description.** `settingsPanel` (`:1378`) renders top-level fields as a section literally named `"mix"`, which has no entry in `schema.sections`. It needs the top-level `description` passed in rather than looking one up that does not exist.
4. **`stem` and `stem_decay` are filtered out of `settingsPanel`** (`:1385`) and rendered per stem. Their descriptions must appear **once**, above the stem rows — not repeated for every stem. Decide where and say why in your report.

**Extract the decisions into pure functions so `elm-test` can reach them.** Whatever chooses which description a section gets, and whether a field renders help, should be callable without a view.

**Write view-level tests through `Main.view`**, not a hand-built page config. That pattern's absence in an earlier plan let three findings through, each a thing that could be deleted from a screen with both suites green. Assert: a section's description renders; a field's help renders where the field does; `sectionNote`'s text still renders for `loop`; and the description is not duplicated per stem. **Prove each by deleting the call and watching the test fail**, and quote those runs.

**The CSS.** New classes need rules in `sleepmix/static/index.html`, matching the existing dark, quiet style. The coverage test proves a rule exists *somewhere*, not that it applies *where the class is emitted* — `.back` needed four separate scopes for exactly that reason. **Read every new selector against the markup that emits it.** Nobody in this loop can open a browser.

**The failure mode this task is most likely to produce is a mixer nobody can scan.** More words is the risk of a plan about adding words. Descriptions sit once per section; help sits under its control; neither is repeated.

- [ ] **Step 1: Write the failing tests** for the pure helpers and the four view behaviours above.
- [ ] **Step 2: Run to verify they fail.** `cd ui && elm-test`.
- [ ] **Step 3: Implement** in `ui/src/Page/Mixer.elm`.
- [ ] **Step 4: Write the CSS**, then `pipenv run pytest tests/test_static_bundle.py -v`, then read every new selector against its markup.
- [ ] **Step 5: Prove the view tests bite** by deleting each asserted call in turn. Quote the runs.
- [ ] **Step 6: Run everything, rebuild, commit**

```bash
cd ui && elm-test
cd /Users/moopius/projects/sleepmixer && make ui && pipenv run pytest -q -m "not slow"
git add ui sleepmix/static && git commit -m "feat: the mixer explains itself"
```

---

## Task 5: `output.sample_rate` joins the master-gain cache key

**Files:**
- Modify: `sleepmix/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later depends on it.

**Why.** `RenderSession._master_key` omits `output.sample_rate` although `run_pipeline` resamples before normalizing. The level magnitude is about 0.01 dB — negligible — but the **cache** consequence is unconditional: changing the output rate does not invalidate the memoized gain at all, so a session keeps serving a factor measured at the old rate until something else happens to clear it. This is a cache bug that happens to live in a level-matching entry.

**Read `_master_key` before changing it.** It carries a specific set of things, and the reason each is there is worth preserving; add to it rather than rewriting it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_session.py` (check the module's existing fixtures and reuse them):

```python
def test_changing_the_output_rate_changes_the_master_key():
    """run_pipeline resamples before normalizing, so a gain measured at one
    output rate does not describe a render at another. Without this the
    memoized factor survives the change and the session keeps serving it."""
    base = MixConfig()
    other = MixConfig()
    other.output.sample_rate = 22050
    assert _master_key(base, reverb=True) != _master_key(other, reverb=True)
```

Match `_master_key`'s real signature and import path — read `sleepmix/session.py` first rather than copying the call above verbatim.

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_session.py -k master_key -v`
Expected: FAIL — the two keys are equal.

- [ ] **Step 3: Add the field to the key, run, commit**

```bash
pipenv run pytest -q -m "not slow"
git add sleepmix/session.py tests/test_session.py
git commit -m "fix: the master-gain cache notices an output-rate change"
```

---

## Task 6: The measurement, and the staleness pass

**Files:**
- Modify: `docs/project-state.md`
- Modify: `docs/architecture.md`, `README.md`, `ui/README.md` — only where this plan's own changes make a claim false

**Write no application code in this task.** If the measurement uncovers a bug, report it prominently and leave it; the whole-branch review is next.

- [ ] **Step 1: Measure where the un-faded peak actually is**

`docs/project-state.md` records a 1.82 dB gap between previews and renders and attributes it to `_apply_fades` running before `normalize_peak`. **The arithmetic does not support that attribution.** The default mix is 20 minutes and the default fade-in is 8 seconds — 0.67% of an arc that decays to `amp_end_db` = −9 dB — so ordinary material decays about **0.06 dB** across the faded region. The recorded figure is thirty times larger, so something other than the decay is setting the un-faded peak. The likeliest candidate is a transient at t = 0: the loop's first sample, before any crossfade has smoothed anything.

Render once at default config against a throwaway data dir, with a stem cache written directly via `sleepmix.separation._write_cache` so no Demucs runs, and report on the mix **before** `_apply_fades`:

- where the global peak sits in time;
- its height above the 99th percentile of absolute sample values — high enough to ignore a lone spike, low enough to represent what is audible;
- its width in samples, since one or two samples is a discontinuity and tens of milliseconds is music;
- whether it survives `cycle_crossfade_ms = 0`, which separates a loop-boundary artefact from something in the source.

**Change nothing.** This produces a paragraph.

- [ ] **Step 2: Rewrite the entry to say what the number is**

Replace the fade-ordering bullet in `docs/project-state.md` with what the measurement found, keeping the measured 1.82 dB and the method. If the measurement does not support the transient hypothesis either, **say so plainly and say what was actually observed** — an unexplained number honestly labelled is worth more than a tidy wrong explanation, which is what is there now.

Also record, beside it, why the gap is not being closed: `preview.render_window` applies one gain factor to every window (`sleepmix/preview.py:101`), so the ratio between previews at the start, middle and end of the arc is exact, and a uniform offset cannot change any comparison the mixer exists to support.

- [ ] **Step 3: Check every deferred entry against source**

Two are already known false, both closed by Plan 3c and never retired:

- *"There is no `DELETE /api/renders/{id}`, no pruning, no size cap… this is the resource problem on this branch"* — `sleepmix/server/api/renders.py:125` is the route.
- *"`JobManager._jobs`, `_tokens` and `_subscribers` are never evicted"* — `sleepmix/server/jobs.py:63` takes `keep_terminal=50`; `_evict` is at `:220`.

Assume there are more. Check each remaining entry in the deferred and known-weakness sections against the code it describes.

**Mark closed entries closed, with which plan closed them. Do not delete them.** The reasoning is the useful part — it records why something was once thought not worth fixing, which is exactly what a maintainer needs when deciding whether to reopen it. An entry that vanishes teaches nothing.

- [ ] **Step 4: Record what this plan leaves open**

- The sound bed is absent from previews: `render_window` sums only the configured stems and never calls `build_soundbed`, so enabling binaural beats or pink noise changes nothing audible in the mixer. Unlike the level items this is a *character* difference, and it touches the judgement previews exist to support. Handled by a note beside the section; whether that is enough is worth revisiting now the help text exists, and closing it means putting the bed into `render_window`, which is an audio change with its own design.
- The remaining calibration-window gaps, with their measurements: the inter-iteration crossfade summing (+0.37 dB dry, ~0.01 dB with default reverb) and the sound bed's absence from the calibration window (+0.03 dB at default gain, off by default).
- That Plan 3e was retired before implementation, with a pointer to `docs/superpowers/specs/2026-08-05-level-matching-design.md`, so the gap in plan numbering is not a mystery.

- [ ] **Step 5: Commit**

```bash
git add docs README.md ui/README.md
git commit -m "docs: what the mixer now explains, and what the project state got wrong"
```

---

## What this plan does not cover

- **Any change to the audio path.** The fade ordering stays, the crossfade summing and the sound bed's absence from the calibration window stay recorded, nothing in `pipeline.py` or `disintegration.py` moves.
- **Putting the sound bed into previews** — an audio change, its own design.
- **A simple/advanced split of the mixer**, and a glossary or primer page. Help belongs beside the control.
- **Rewriting `docs/architecture.md` or the READMEs** beyond claims this plan falsifies.
- Segment selection and arrangement, a path allow-list for `import_song`, streaming peak computation, and authentication — carried forward unchanged.
