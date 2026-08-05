# Plan 3e: level-matching — making a preview tell the truth about a render

**Status:** design approved 2026-08-05, not yet planned.

## What this is for

`sleepmix` repeats one loop for half an hour while eroding it. The mixer lets
you hear any point in that decay arc before committing to a render, and the
only reason that is useful is that a preview sounds like the render will. It
currently does not: a preview reads **quieter** than the render at the same
point in the arc, which makes it sound **more eroded** than what you will
actually get. Someone tuning by ear compensates for a difference that is not
in the mix.

## The recorded gap, and why it does not add up

`docs/project-state.md` records four things that contribute to a render's final
peak which `master_gain`'s calibration window never sees. All four were
measured the same way — RMS of a mid-arc mastered preview over the
corresponding crossfade-free region of a real `run_pipeline` output, default
config, changing one thing at a time — and the baseline with fades off is
**1.0003, +0.00 dB**.

The largest is recorded as: `_apply_fades` runs before `normalize_peak`, and
`fade_in_s` defaults to 8 s, so the fade attenuates exactly the region
iteration 0 occupies — the window `master_gain` calibrates against. **Measured
with default fades: 0.8107, −1.82 dB.**

**That attribution is an inference, and the arithmetic does not support it.**
The default mix is 20 minutes and the default fade-in is 8 seconds — 0.67% of
the way through an arc that decays to `amp_end_db` = −9 dB. Ordinary material
therefore decays about **0.06 dB** across the faded region. Fading it out and
re-finding the peak just past the fade should move the normalization divisor by
roughly that much. The measurement is thirty times larger.

So something other than the decay is setting the un-faded peak. The obvious
candidate is a **transient at t = 0** — the loop's first sample, a
discontinuity before any crossfade has smoothed anything. A single sample sets
a peak as effectively as a sustained passage does. The current ordering removes
it before normalizing, which is why the pipeline looks well-behaved today.

**This matters because it inverts the fix.** If the un-faded peak is sustained
material, normalizing before fading is correct and costs about 0.06 dB of
ceiling. If it is a transient, normalizing before fading means **a one-sample
click at the start dictates the level of a twenty-minute mix** — every render
quietly scaled down by an artifact the fade was about to delete. That would be
worse than the present behaviour, and silent: the file just comes out quiet,
with nothing to point at.

## The decision already taken

Given the choice of which side moves, the operator chose **the render**:
normalize the material first, then shape the envelope, on the grounds that it
is the more principled order. Previews are already right; renders change.

That decision stands **conditional on the measurement below**. It was taken
against a 1.82 dB cost that may not be a cost at all, or may be a symptom of
something the reordering would make permanent.

## Task 1 is a measurement, not a change

Before anything is reordered, establish where the un-faded global peak actually
is, on a real render at default config:

- **Its position in time.** At the very first sample, within the first
  iteration, or somewhere else entirely.
- **Its height above the sustained material** — the ratio of the global peak to,
  say, the 99th-percentile absolute sample, which is high enough to ignore a
  lone spike and low enough to represent what you hear.
- **Its width.** A peak one or two samples wide is a discontinuity. A peak tens
  of milliseconds wide is music.
- **Whether it survives `cycle_crossfade_ms = 0`**, which distinguishes a
  loop-boundary artefact from something in the source material.

The output is a number and a verdict, written into the plan's report and into
`docs/architecture.md`. **No code changes in this task.**

## The fix, chosen on that evidence

**If the peak is sustained material at t ≈ 0:** swap `pipeline.py:83-84` so
`normalize_peak` runs before `_apply_fades`. The finished file then peaks
marginally below `output.peak_db` — by the decay across the fade, ~0.06 dB —
because the loudest moment is inside the fade-in. That is the honest outcome of
asking for a fade, and `peak_db` becomes a ceiling rather than a target.

**If the peak is a transient:** do not reorder. Instead normalize on a peak
measured past a guard interval at the start, so a boundary discontinuity cannot
set the level of a twenty-minute mix. **The guard's length comes from Task 1's
measured peak width, rounded up to the next whole loop-crossfade** — it is not a
number to invent. This also fixes the render's own level independently of
previews, since a click currently costs level whether or not anyone is
previewing.

**Both arms are written out in full in the implementation plan.** Task 1 selects
which one runs; neither is left as "decide later". The plan also records the
measured numbers in `docs/architecture.md` either way, because the next person
to look at this deserves the evidence rather than the conclusion.

**If the measurement shows something neither arm anticipates** — a peak that is
neither sustained material nor a boundary transient — that is a `BLOCKED` and it
comes back to the operator. A third explanation would mean the model of the
pipeline in this document is wrong, and reordering anything on a wrong model is
how the 1.82 dB got mis-attributed in the first place.

**Either way the 1.82 dB is explained before anything changes**, and
`docs/project-state.md`'s entry is corrected to say what the number is, rather
than what it was assumed to be.

## Also fixed: `output.sample_rate` in `_master_key`

`RenderSession._master_key` omits `output.sample_rate` although `run_pipeline`
resamples before normalizing. The level magnitude is small — about 0.01 dB at
22050 → 44100 on the test signal — but the **cache** consequence is
unconditional: changing the output rate does not invalidate the memoized gain at
all, so a session keeps serving a factor measured at the old rate until
something else happens to clear it. That is a correctness bug wearing a
level-matching costume, and it is one line.

## Left recorded, not fixed

- **The inter-iteration crossfade can sum above a single iteration's peak.**
  Measured on the dry path at **+0.37 dB**, dropping to 0.9995 with
  `cycle_crossfade_ms = 0` and nothing else changed — so the residual is
  entirely this. With default reverb it is masked to about 0.01 dB, because
  reverb smears the peak either way. Fixing it properly means calibrating across
  a crossfade boundary: real work for an inaudible gain at defaults.
- **The sound bed is never mixed into the calibration window.** At the default
  `noise_gain_db = -34` it moves the ratio by **+0.03 dB**; even at −6 dB it
  reaches only −0.05 dB, because `normalize_peak` scales the stems down by very
  nearly the same factor the bed pushed the peak up. `SoundbedConfig.enabled`
  defaults to `False` in any case.

Both stay in `docs/project-state.md` with their measurements. The reason they
are recorded rather than fixed is that the sizes are counter-intuitive, and the
list has already misled once: the entry that had been written down was the
smallest of the four, and the largest was not written down at all.

## Verification

The existing `tests/test_preview.py::test_a_mastered_preview_sits_at_the_render_s_level`
asserts the ratio with fades **off**, where it is already 1.0003. It gains a
sibling asserting the ratio with fades **on**, which fails today at 0.81 and
must pass after the fix — whichever fix the measurement selects.

That test is the plan's real deliverable. Everything else is the change that
makes it pass.

## Out of scope

- The crossfade-summing and sound-bed contributions above.
- Any change to how `normalize_peak` itself works.
- Loudness normalisation (LUFS) rather than peak normalisation — a different
  design conversation, and a bigger one.
- The in-UI help and the `project-state.md` staleness pass, which are Plan 3f.
