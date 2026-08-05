# Plan 3f: legibility — the mixer explains itself, and the project state stops lying

**Status:** design approved 2026-08-05, not yet planned.

## What this is for

`sleepmix` separates a song into stems and repeats one loop for half an hour
while eroding it. The mixer exposes **47 config fields**. Someone who did not
write it cannot tell what most of them do, and the interface currently offers
almost no help with that.

Two counts, both established against the running server rather than by reading:

- **11 of 47 fields carry any help text at all.** The 36 without include every
  decay parameter — `lowpass_end_hz`, `amp_end_db`, `dropout_end`,
  `spectral_hole_end` — and the whole of the reverb and soundbed sections. They
  are exactly the fields whose names state a mechanism and not an effect.
- **Every help string that does exist is rendered as `Attr.title`**
  (`ui/src/Page/Mixer.elm:1700`) — a hover tooltip. Invisible on touch,
  unreachable by keyboard, and invisible to anyone who does not happen to hover
  over the right element.

So the help is both mostly missing and, where present, mostly unreachable.

The second half of this plan is unrelated in subject and identical in spirit:
`docs/project-state.md` has grown to roughly 1,300 lines across five plans and
has begun carrying claims that were true when written and are false now.

Two small items arrive here from a retired Plan 3e — a measurement that corrects
one of those false claims, and a one-line cache fix. Both are described under
"Two survivors from Plan 3e" below; the reasoning for the retirement is in
`docs/superpowers/specs/2026-08-05-level-matching-design.md`.

## The shape the help takes

**Sections explained; fields only where it earns its place.**

Forty-seven sentences would roughly double the height of the screen and lower
its signal-to-noise. "Gain, in decibels" under a control labelled *Gain (dB)* is
words without information, and a screen full of those teaches a reader to skip
all of them — including the four that matter.

What a newcomer actually needs is **what a section is for**, and then help on
the handful of controls whose names describe the mechanism rather than the
result.

### Section descriptions

`config_schema()` gains a `description` per section, and `Schema.Section` in Elm
gains it to match. Four to six short paragraphs, in the project's voice: what
decay, reverb, soundbed, loop, tempo and output actually do, and why you would
touch them.

**They are sourced from the dataclass docstrings**, so the text has one home
rather than two that drift. `StemConfig` and `StemDecayConfig` already have real
docstrings; `LoopConfig`, `TempoConfig`, `ReverbConfig`, `SoundbedConfig` and
`OutputConfig` currently show dataclass-generated signatures, which means those
need writing rather than wiring.

**Note the schema's union is closed on purpose**, and this adds a field to
`Section` rather than to `Field`, so the existing field decoders are untouched.
A section without a description must decode rather than fail — the server always
sends the key once this lands, but the decoder should not make the two
deployable independently by accident.

### Per-field help, where the name hides the effect

The principle: **write help where the field name states a mechanism and not an
outcome.** By that test the set is roughly —

- **The decay endpoints**, which are the heart of the tool and the least
  self-describing thing in it: `lowpass_start_hz` / `lowpass_end_hz`,
  `amp_start_db` / `amp_end_db`, `dropout_start` / `dropout_end`,
  `spectral_hole_start` / `spectral_hole_end`, `noise_start_db` /
  `noise_end_db`. Each pair wants one idea — what the stem sounds like at the
  beginning of the half hour and at the end — not two independent numbers.
- **`loop.bars` and `loop.beats_per_bar`**, which together decide how long the
  repeated fragment is, in a unit that is musical rather than temporal.
- **`output.peak_db`**, and especially so after Plan 3e, where it may stop being
  the level the file actually reaches.
- **The binaural fields** — `binaural_carrier_hz`, `binaural_beat_hz`,
  `binaural_gain_db` — where the constraint matters more than the number:
  binaural beats do nothing without headphones, because they rely on each ear
  receiving a different tone.

Fields whose label already says it — `gain_db`, `enabled`, `sample_rate`,
`channels` — get nothing, deliberately, and the plan says so rather than leaving
the omission to look like an oversight.

`separation_model` is excluded because the mixer deliberately withholds a
control for it: changing it nulls the session's stems and triggers a
multi-minute Demucs run inside the preview lock.

### Surfacing

`Attr.title` is replaced with visible markup. That is what makes section
paragraphs possible at all — a `title` attribute has nowhere to put one — and it
is what makes any of this reachable on a touchscreen or by keyboard.

New classes need rules in `sleepmix/static/index.html`, matching the existing
dark, quiet style. The class-coverage test in `tests/test_static_bundle.py`
proves a rule exists *somewhere*, not that it applies *where the class is
emitted* — `.back` needed four separate scopes for exactly that reason — so
selectors get read against the markup that emits them.

**The mixer must not get taller than it is useful.** Section descriptions sit
once per section, not once per field; per-field help is one line under the
control it belongs to.

## The staleness pass

Every entry in `docs/project-state.md`'s deferred and known-weakness sections is
checked against source. Two are already known to be false:

- *"There is no `DELETE /api/renders/{id}`, no pruning, no size cap… this is the
  resource problem on this branch"* — closed by Plan 3c;
  `sleepmix/server/api/renders.py:125` is the route.
- *"`JobManager._jobs`, `_tokens` and `_subscribers` are never evicted"* —
  closed by Plan 3c; `sleepmix/server/jobs.py:63` takes `keep_terminal=50` and
  `_evict` is at `:220`.

Both were invalidated by a plan that added its own section and never went back
to retire what it had closed. Assume there are more.

**Closed entries are marked closed and dated by plan, not deleted.** The
reasoning in them is the useful part — it records why something was once thought
not worth fixing, which is exactly the context a maintainer needs when deciding
whether to reopen it. An entry that simply vanishes teaches nothing.

The pass covers `docs/project-state.md` only. `docs/architecture.md`, `README.md`
and `ui/README.md` are checked for claims this plan's own changes make false,
and otherwise left alone.

## Two survivors from Plan 3e

Plan 3e was going to reorder `pipeline.py`'s fade and normalize steps to close a
recorded 1.82 dB gap between previews and renders. It was retired before
implementation: `preview.render_window` "applies one gain factor to every
window" (`sleepmix/preview.py:101`), so the ratio between previews at the start,
middle and end of the arc is already exact, and a uniform offset does not change
any comparison the mixer exists to support. Two pieces of it belong here.

### Correct the 1.82 dB entry rather than acting on it

`docs/project-state.md` attributes that gap to the fade ordering. **The
arithmetic does not support it.** The default mix is 20 minutes, the default
fade-in is 8 seconds — 0.67% of an arc that decays to `amp_end_db` = −9 dB — so
ordinary material decays about **0.06 dB** across the faded region. The recorded
figure is thirty times larger, which means something other than the decay is
setting the un-faded peak. The likeliest candidate is a transient at t = 0, the
loop's first sample, before any crossfade has smoothed anything.

A wrong explanation in the documentation is worse than a known gap, because the
next person builds on it — and this plan is about documentation that has stopped
being true.

**The measurement, which changes no audio:** render once at default config and
report where the un-faded global peak sits in time; its height above the 99th
percentile of absolute sample values, which is high enough to ignore a lone
spike and low enough to represent what is audible; its width in samples, since
one or two samples is a discontinuity and tens of milliseconds is music; and
whether it survives `cycle_crossfade_ms = 0`, which separates a loop-boundary
artefact from something in the source.

The entry is then rewritten to say what the number **is**, with the evidence.
If the measurement shows something the transient hypothesis does not explain,
that is worth reporting prominently rather than smoothing over — it would mean
the model of the pipeline in both this document and `docs/architecture.md` is
wrong.

### `output.sample_rate` joins `RenderSession._master_key`

One line, and not really about level. `run_pipeline` resamples before
normalizing, but `_master_key` omits the output rate — so changing it does not
invalidate the memoized gain at all, and a session keeps serving a factor
measured at the old rate until something else happens to clear it. The level
magnitude is about 0.01 dB; the cache consequence is unconditional. A test
should pin that changing `output.sample_rate` produces a different key.

## Failure modes the plan must handle

- **A section description that describes behaviour the code does not have.**
  Every paragraph is checked against the code it describes. This project has
  shipped a documentation claim contradicted by the same diff that introduced
  it; prose about DSP is easier to get wrong than prose about routes.
- **Help text that repeats the label.** Caught by the "mechanism not outcome"
  test above; a reviewer should reject any string that a reader could have
  derived from the field name.
- **A class emitted where its rule does not reach.** The coverage test cannot
  see this.
- **The mixer becoming unreadable through sheer height.** More words is the
  failure mode this plan is most likely to produce, being a plan about adding
  words.

## Testing

The Python side gains a test that every section in `config_schema()` carries a
non-empty `description`, and that each of the named fields above carries
non-empty `help` — derived from a list in the test rather than written out
twice, so a section added later fails until it is described.

The Elm side gains decoder coverage for `Section.description`, including that a
section without one decodes rather than fails, and **view-level tests through
`Main.view`** asserting a section's description renders and that a field's help
renders where the field does. View tests written from the start, per the pattern
established in Plan 3c — their absence there let three findings through, each of
them a thing that could be deleted from a screen with both suites green.

## Out of scope

- **A simple/advanced split** of the mixer. Considered; it needs someone to
  decide which knobs are the important ones, which is a different and larger
  conversation than explaining the ones that exist.
- **A glossary or primer page.** The help belongs beside the control.
- Rewriting `docs/architecture.md` or the READMEs beyond claims this plan
  falsifies.
- **Any change to the audio path.** The fade ordering stays as it is, the
  crossfade summing and the sound bed's absence from the calibration window stay
  recorded with their measurements, and nothing in `pipeline.py` moves. The
  measurement above produces a sentence, not a diff.
- **The sound bed's absence from previews** — `render_window` sums only the
  configured stems and never calls `build_soundbed`, so enabling binaural beats
  or pink noise changes nothing you can hear in the mixer. Unlike the level
  items, this is a *character* difference, and it touches the judgement previews
  exist to support. It is currently handled by a note beside the section.
  **Whether that disclosure is enough is worth revisiting once this plan's help
  text exists**, since the two are the same kind of problem — but revisiting it
  means deciding whether to put the bed into `render_window`, which is an audio
  change and belongs to its own design.
