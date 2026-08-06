# Plan 3g: the sound bed in previews, and findable help — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a preview include the sound bed the render will have, and make the mixer's help text findable by a screen reader.

**Architecture:** `preview.render_window` gains the bed after the stem sum and before the master gain, mirroring `pipeline.run_pipeline`; that forces `config.soundbed` into `RenderSession._master_key` in the same commit, because the memoized gain would otherwise survive a change it now depends on. Separately, the mixer's `span.field-label` becomes a real `<label for=…>` and each control gains `aria-describedby` pointing at its help, which needs a new id function because `Config.keyOf` is not unique across the page.

**Tech Stack:** Python 3.11 / numpy · Elm 0.19.2 · pytest · elm-test

**Spec:** `docs/superpowers/specs/2026-08-06-finishing-touches-design.md`

## Global Constraints

- **`pipenv` runs only from the repository root. Never `cd` elsewhere first** — pipenv keys its virtualenv to the directory path, and `cd`-ing first silently creates a new empty virtualenv.
- **`elm` and `elm-test` run from `ui/`**, so `cd ui` is correct for those. These are two different rules; do not conflate them.
- Elm 0.19.2. **No new Elm packages, no npm dependencies, no CSS framework.**
- **No new Python dependencies.**
- **No `Debug.toString` or `Debug.log` anywhere under `ui/src`** — `elm make --optimize` refuses to build with them, so `make ui` fails. Allowed under `ui/tests`.
- **`make ui` from the repository root** rebuilds `sleepmix/static/app.js` and rewrites the hash. Run it and commit whatever it produces; a Python test recomputes the hash.
- **Every class emitted from `ui/src` must have a CSS rule in `sleepmix/static/index.html`.** `tests/test_static_bundle.py` enforces it and **must not be weakened**.
- **No browser automation, AppleScript, screenshots, or browser-driver MCPs.** A prior implementer drove GUI automation against the operator's real desktop and tripped a macOS TCC dialog over a Finder window holding a private key, invoices and a CV. Verify with curl.
- **Every server you start uses `SLEEPMIX_DATA_DIR=$(mktemp -d)`** and is killed afterwards. A prior implementer wrote into the operator's real music library before noticing.
- **Demucs is genuinely installed on this machine**, so `POST /api/songs/{id}/separate` starts a multi-minute run. Use `tests/stub_separation_worker.py`, or write a stem cache directly with `sleepmix.separation._write_cache`.
- Baseline at plan start: **293 Python tests** (plus one marked `slow`), **440 Elm tests**.

---

## Notes for whoever executes this

**Task 1 changes the audio path**, which every other plan this month forbade. It is in scope here and only here, and only in the one place named. Nothing else in `pipeline.py`, `disintegration.py` or the DSP ordering moves.

**The trap Task 1 exists to avoid repeating.** Plan 3f added `output.sample_rate` to `_master_key`, shipped it, and reverted it in the same plan's final review — because `render_window` never resamples, so the change was a measured no-op that only made previews slower. Its test asserted that two tuples differ, which is true by construction and proves nothing. **This task is the opposite case**, and its test must show the difference at the far end of the chain: a `master_gain` that genuinely differs with the bed on and off. `_master_key`'s own docstring now carries that lesson; read it before editing.

---

## File structure

| File | Responsibility |
|---|---|
| `sleepmix/preview.py` *(modify)* | `render_window` adds the bed after the stem sum, before the master gain. |
| `sleepmix/session.py` *(modify)* | `config.soundbed` joins `_master_key`; its docstring explains why this one belongs where `output.sample_rate` did not. |
| `ui/src/Config.elm` *(modify)* | `domId : Target -> String` — unique across the page, unlike `keyOf`. |
| `ui/src/Page/Mixer.elm` *(modify)* | `<label for>` and `aria-describedby`. |
| `docs/project-state.md` *(modify)* | Gap 4 closed; the rng caveat; the solo exception. |

---

## Task 1: The sound bed reaches previews, and the master gain notices it

**Files:**
- Modify: `sleepmix/preview.py`, `sleepmix/session.py`
- Test: `tests/test_preview.py`, `tests/test_session.py`

**Interfaces:**
- Consumes: `sleepmix.soundbed.build_soundbed(duration_s: float, sr: int, cfg: SoundbedConfig, rng) -> AudioBuffer`.
- Produces: no new API. `render_window`'s signature is unchanged; its output now contains the bed when `cfg.soundbed.enabled` and no `stems` filter was given.

**Where it goes and why.** `run_pipeline` sums the stems, adds the bed, then masters (`pipeline.py:73-76`). `render_window` sums the stems into `acc`, wraps it as `out`, then multiplies by `master_gain` when `master=True`. The bed goes between those two, which is the same position.

**The bed is generated per window, not sliced from a full-length one.** Noise is stationary and a binaural beat is periodic, so a window-length bed is perceptually identical to the corresponding slice — and building twenty minutes of noise to take twenty seconds of it would be absurd. Say so in a comment; this is exactly the kind of thing a later reader "corrects" into a slice.

**The rng is `np.random.default_rng(cfg.seed)`, matching `pipeline.py:45`.** Not for fidelity — for stability. `master_gain` memoizes a factor measured from one window, and a window with freshly random noise each call would make that factor depend on which draw occurred. **`run_pipeline`'s rng has advanced by the time it reaches the bed, so the preview's noise is not the same samples as the render's.** Inaudible, and the comment must say so rather than imply they match.

**The bed is absent when a stem is soloed.** A solo already does not match the render — the render has every enabled stem — and a bed over an isolated stem masks the thing it was isolated to hear. This is a deliberate exception, approved at design time; write the reason down.

**One failure mode the spec names and this arrangement makes unreachable, which is worth knowing rather than guarding.** A preview that contains the bed while the calibration window does not — or the reverse — would mis-level every preview by the bed's contribution. That cannot happen here, because `master_gain` calibrates by calling `render_window` itself, so the two are the same code path by construction. Do not add a flag that lets them diverge; the absence of one is the guarantee.

- [ ] **Step 1: Write the failing preview tests**

Add to `tests/test_preview.py`. Read the module's existing fixtures first (`_song`, `_level_cfg`, and `conftest`'s `stub_separation`) and reuse them rather than building new ones.

```python
def _with_bed(cfg, enabled=True):
    """A copy of cfg with the bed switched on and given something audible."""
    import copy
    out = copy.deepcopy(cfg)
    out.soundbed.enabled = enabled
    out.soundbed.noise_gain_db = -12.0
    return out


def test_a_preview_includes_the_sound_bed(tmp_path, stub_separation):
    """The gap this closes: enabling pink noise used to change nothing you
    could hear in the mixer, which is a difference in character rather than
    level — and character is the judgement a preview exists to support."""
    quiet = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg(), enabled=False))
    loud = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg(), enabled=True))
    without = render_window(quiet, 0.5, master=False)
    with_bed = render_window(loud, 0.5, master=False)
    assert with_bed.data.shape == without.data.shape
    assert not np.allclose(with_bed.data, without.data)


def test_the_bed_is_the_same_every_time_it_is_rendered(tmp_path, stub_separation):
    """Derived from the seed rather than freshly random, so the memoised master
    gain cannot depend on which draw happened to occur."""
    session = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg()))
    first = render_window(session, 0.5, master=False)
    second = render_window(session, 0.5, master=False)
    assert np.array_equal(first.data, second.data)


def test_a_soloed_preview_leaves_the_bed_out(tmp_path, stub_separation):
    """Solo already does not match the render, which has every enabled stem.
    A bed over an isolated stem masks the thing it was isolated to hear."""
    session = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg()))
    plain = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg(), enabled=False))
    one = render_window(session, 0.5, stems=["vocals"], master=False)
    same = render_window(plain, 0.5, stems=["vocals"], master=False)
    assert np.array_equal(one.data, same.data)
```

Match the real names of `_song`, `_level_cfg`, `RenderSession` and the separation fixture — read the file rather than copying these imports blind. If `_level_cfg` has the bed off already, `enabled=False` is a no-op and the first test still discriminates.

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_preview.py -k bed -v`
Expected: FAIL — the two windows are identical, because nothing adds a bed.

- [ ] **Step 3: Implement**

In `sleepmix/preview.py`, import `build_soundbed` from `.soundbed`, and between `out = AudioBuffer(acc, sr)` and the `if master:` block:

```python
    # Where run_pipeline puts it: after the stems are summed, before mastering.
    #
    # Generated for this window rather than sliced out of a full-length bed.
    # The noise is stationary and the binaural beat is periodic, so a window's
    # worth is perceptually the same as the matching slice of twenty minutes —
    # and building twenty minutes to take twenty seconds would be absurd.
    #
    # Seeded from the config rather than left freshly random, because
    # ``master_gain`` memoises a factor measured from one window and a random
    # window would make that factor depend on which draw happened. Note this
    # does *not* reproduce the render's own bed sample for sample:
    # ``run_pipeline``'s generator has advanced by the time it reaches the bed.
    # Noise is noise, so that is inaudible — but it is not the same signal.
    #
    # Skipped for a solo, which already does not match the render (the render
    # has every enabled stem). A bed over an isolated stem masks the thing it
    # was isolated to hear.
    if stems is None and cfg.soundbed.enabled:
        bed = build_soundbed(out.data.shape[0] / sr, sr, cfg.soundbed,
                             np.random.default_rng(cfg.seed))
        wide = bed.with_channels(cfg.output.channels).data
        n = min(out.data.shape[0], wide.shape[0])
        out = AudioBuffer(out.data[:n] + wide[:n], sr)
```

- [ ] **Step 4: Write the failing session tests**

Add to `tests/test_session.py`:

```python
def test_the_master_gain_notices_the_bed(tmp_path, stub_separation):
    """The test Plan 3f's sample_rate change should have had and did not: it
    asserted two tuples differ, which is true by construction. What matters is
    whether the value at the far end of the invalidation chain moves."""
    quiet = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg(), enabled=False))
    loud = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg(), enabled=True))
    assert master_gain(quiet, reverb=True) != master_gain(loud, reverb=True)


def test_toggling_the_bed_clears_the_memoised_gain(tmp_path, stub_separation):
    session = RenderSession(str(_song(tmp_path)), _with_bed(_level_cfg(), enabled=False))
    before = master_gain(session, reverb=True)
    assert session.master_gain  # memoised
    session.update_config(_with_bed(_level_cfg(), enabled=True))
    assert not session.master_gain, "a bed change must not serve a stale factor"
    assert master_gain(session, reverb=True) != before
```

Import `_with_bed`, `_song` and `_level_cfg` from wherever they actually live, or duplicate the small helper — read both test modules and pick whichever the file already does for shared helpers.

- [ ] **Step 5: Run to verify they fail, then implement**

Run: `pipenv run pytest tests/test_session.py -k bed -v` — expect FAIL, the gains are equal.

Add `config.soundbed` to `_master_key`'s returned tuple, beside the existing entries and without disturbing their order. **Then extend the docstring**: it currently explains at length why `output.sample_rate` is deliberately absent and must not be added. Add the counterpart — that `config.soundbed` *is* here, because `render_window` reads it as of this plan, and that the difference between the two cases is whether the calibration window depends on the field, not whether the render does.

- [ ] **Step 6: Prove the pairing is load-bearing**

Revert only the `_master_key` line, leaving the bed in `render_window`, and run `pipenv run pytest tests/test_session.py -k bed -v`. The stale-gain test must fail. Restore it, confirm `git diff` on `session.py` is clean, and quote both runs in your report — this is what the previous plan's version of this change could not do.

- [ ] **Step 7: Run everything and commit**

```bash
pipenv run pytest -q -m "not slow"
git add sleepmix/preview.py sleepmix/session.py tests/
git commit -m "feat: previews carry the sound bed, and the master gain notices"
```

---

## Task 2: Help a screen reader can find

**Files:**
- Modify: `ui/src/Config.elm`, `ui/src/Page/Mixer.elm`
- Test: `ui/tests/ConfigTest.elm`, `ui/tests/MixerTest.elm`

**Interfaces:**
- Consumes: `Config.Target(..)` as it already is.
- Produces: `Config.domId : Target -> String`, added to the module's exposing list.

**Why `keyOf` cannot be reused.** `Config.keyOf` returns the *bare field name* — it discards the section and the stem index, because values live in per-section dictionaries keyed by bare name. That is correct for looking a value up and useless as a DOM id: every stem's `enabled` would collide with every other stem's, and with `stem_decay`'s. Two functions, two jobs; do not change `keyOf`.

- [ ] **Step 1: Write the failing `domId` tests**

Add to `ui/tests/ConfigTest.elm`:

```elm
domIdSuite : Test
domIdSuite =
    describe "Config.domId"
        [ test "two stems' identically-named fields do not collide" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.InStem 0 "enabled"))
                    (Config.domId (Config.InStem 1 "enabled"))
        , test "a stem field and its decay counterpart do not collide" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.InStem 0 "enabled"))
                    (Config.domId (Config.InStemDecay 0 "enabled"))
        , test "the same field in two sections does not collide" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.InSection "loop" "bars"))
                    (Config.domId (Config.InSection "output" "bars"))
        , test "a top-level field does not collide with a section's" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.Top "seed"))
                    (Config.domId (Config.InSection "loop" "seed"))
        , test "it is stable for the same target" <|
            \_ ->
                Expect.equal
                    (Config.domId (Config.InStem 2 "gain_db"))
                    (Config.domId (Config.InStem 2 "gain_db"))
        ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && elm-test`
Expected: FAIL to compile — `Config.domId` does not exist.

- [ ] **Step 3: Implement `domId`**

```elm
{-| A DOM id for the control at this target, unique across the whole page.

Not `keyOf`, which returns the bare field name because that is what indexes the
per-section dictionaries — and which therefore gives every stem's `enabled` the
same string as every other stem's. An id that collides points two controls at
one label, which is worse for a screen reader than no label at all.
-}
domId : Target -> String
domId target =
    case target of
        Top key ->
            "f-top-" ++ key

        InSection section key ->
            "f-" ++ section ++ "-" ++ key

        InStem index key ->
            "f-stem" ++ String.fromInt index ++ "-" ++ key

        InStemDecay index key ->
            "f-decay" ++ String.fromInt index ++ "-" ++ key
```

Add `domId` to the exposing list, keeping the existing grouping.

- [ ] **Step 4: Write the failing markup tests**

Add to `ui/tests/MixerTest.elm`, through `Main.view` as the module's other view tests do — read one first and follow its shape. Cover:

- every rendered control carries an `id`, and the `label` beside it carries a `for` with the same value;
- a control that has help carries `aria-describedby` whose value is the help paragraph's `id`;
- a fixture with **two** stems produces no duplicate ids — the case `keyOf` would have broken.

`aria-describedby` has no dedicated Elm helper; it is `Html.Attributes.attribute "aria-describedby" …`, and `Test.Html.Selector.attribute` matches it.

**Remember that `Selector.text` cannot be ANDed with `Selector.class` in one list** — `ContainsText` is `always False` on element nodes, so a combined selector silently matches nothing. Use `Selector.containing`, as every other view test in this file does.

- [ ] **Step 5: Run to verify they fail, then implement**

In `ui/src/Page/Mixer.elm`: `span [ class "field-label" ]` becomes `label [ class "field-label", Attr.for (Config.domId target) ]`; the control gains `Attr.id (Config.domId target)`; and where help is rendered, the `p` gains `Attr.id (Config.domId target ++ "-help")` and the control gains `Attr.attribute "aria-describedby" (Config.domId target ++ "-help")` — **only when there is help**, since pointing at an element that does not exist is worse than pointing at nothing.

Keep the `class "field-label"` literal exactly as it is: `tests/test_static_bundle.py` scans for that literal, and the existing CSS rule still applies to a `label` as readily as to a `span`.

- [ ] **Step 6: Prove the tests bite**

Delete `Attr.for` from the label, run `elm-test`, confirm the label test fails. Restore. Then delete the `aria-describedby` attribute, confirm that test fails, restore. Quote both runs — every assertion here is about attributes that are trivially rendered as empty strings.

- [ ] **Step 7: Run everything, rebuild, commit**

```bash
cd ui && elm-test
cd .. && make ui && pipenv run pytest -q -m "not slow"
git add ui sleepmix/static && git commit -m "feat: help a screen reader can find"
```

---

## Task 3: The record

**Files:**
- Modify: `docs/project-state.md`, `docs/architecture.md`

**Write no application code.**

- [ ] **Step 1: Close what this plan closed**

`docs/project-state.md` records four calibration-window gaps. **The fourth — the sound bed's absence from the calibration window, measured at +0.03 dB at the default `noise_gain_db = -34` — is now closed**, because `render_window` includes the bed and `master_gain` measures `render_window`. Mark it closed by this plan, in the style the file already uses for closed entries: kept with its reasoning, not deleted.

The same file records the sound bed's absence from previews as a *character* gap, distinct from the level ones. That is closed too.

- [ ] **Step 2: Record what is now true and was not**

- **The preview's bed is not the render's bed sample for sample.** Both are seeded from `config.seed`, but `run_pipeline`'s generator has advanced by the time it reaches the bed. Inaudible; not identical. A future reader comparing buffers deserves to know before they start.
- **The bed is absent from a soloed preview**, deliberately, with the reason.
- **`config.soundbed` is now in `_master_key` and `output.sample_rate` still is not**, and the distinction is whether the *calibration window* reads the field — not whether the render does. That pair is the clearest example in the codebase of why the question is "does the measured value move" rather than "does the render depend on it".

- [ ] **Step 3: Check `docs/architecture.md` for claims this plan falsified**

It describes the preview path. Anything saying previews exclude the bed is now false. Fix what this plan broke and leave the rest alone.

- [ ] **Step 4: Commit**

```bash
git add docs
git commit -m "docs: the bed reaches previews, and what that closed"
```

---

## What this plan does not cover

- **The remaining calibration-window gaps:** the inter-iteration crossfade summing (+0.37 dB dry, ~0.01 dB with default reverb), and the fade ordering, whose 1.82 dB was traced in Plan 3f to a synthetic 30-second test fixture and does not describe the mixer's real default.
- **A separate audition for the bed alone.** The bed being in every preview is the point.
- **A path allow-list for `import_song`, and authentication.** Ruled out on the grounds that the server binds `127.0.0.1`, carries a Host allow-list against DNS rebinding, sets no CORS headers and takes JSON-only bodies — **conditional on `--allow-remote` never being used**, at which point both become necessary.
- Segment selection and arrangement; streaming peak computation.
