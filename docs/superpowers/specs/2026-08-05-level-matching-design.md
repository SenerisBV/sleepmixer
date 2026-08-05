# Plan 3e: level-matching — retired before implementation

**Status:** retired 2026-08-05. Not implemented, and deliberately so. Two small
survivors moved into Plan 3f (`2026-08-05-legibility-design.md`).

This file is kept rather than deleted because the reasoning is the useful part.
The gaps it describes are real and still open; what changed is the judgement
about whether closing them serves anyone.

## What it was going to do

`docs/project-state.md` records four things that contribute to a render's final
peak which `preview.master_gain`'s calibration window never sees. The largest is
recorded at **1.82 dB**: `_apply_fades` runs before `normalize_peak`, so the
render's peak lands after the fade-in completes — somewhere more decayed — while
`master_gain` calibrates against iteration 0, which has no fade. A preview
therefore reads quieter than the render at the same point in the arc, and
quieter reads as *more* eroded.

The plan was to swap `pipeline.py:83-84` so normalization runs on the material
and the fade shapes the result, preceded by a measurement task, because the
arithmetic did not support the recorded attribution (8 seconds of fade across a
20-minute arc decaying to −9 dB accounts for about 0.06 dB, not 1.82).

## Why it was retired

**Every preview of a song shares a single gain.** `preview.render_window`
"applies one gain factor to every window, computed once per `reverb` setting via
`master_gain` and memoized" (`sleepmix/preview.py:101`).

So the ratio between the preview at the start of the arc, in the middle and at
the end is exact. **The 1.82 dB is a uniform offset applied to the whole set,
and a uniform offset does not change any comparison made between points on the
arc** — which is the only comparison the mixer exists to support. The operator's
judgement is "is this too eroded by the middle", not "is this preview at the
same absolute level as a file I will play tomorrow on a different device".

The preview-to-render offset bites only when the two are compared directly, at
matched volume, close together in time. That is not the workflow: tune, render,
sleep to it elsewhere, come back the next day.

This is functional audio, degraded formulaically. What it sounds like at the
beginning, the middle and the end is what needs to be true. Perfect absolute
level-matching is the standard a composition tool would need, and this is not
one.

**The ranking error worth recording:** level-matching was put first on the
remaining-work list on the grounds that it was the only item that changed what
came out of the speakers. True, and incomplete — it changes the *absolute* level,
not the quantity being judged. The fact that disproves it (`one gain factor to
every window`) was already written down, in this repository, and was not
connected to the question.

## What is genuinely still open, and left open

- The four calibration-window gaps in `docs/project-state.md`, with their
  measurements: the fade ordering (1.82 dB), the inter-iteration crossfade
  summing (+0.37 dB dry, ~0.01 dB with default reverb), `output.sample_rate`'s
  absence from `_master_key` (~0.01 dB), and the sound bed's absence from the
  calibration window (+0.03 dB at default gain, and it defaults to off).
- **The sound bed is not in previews at all.** `render_window` sums only the
  configured stems and never calls `build_soundbed`. This is a *character*
  difference rather than a level one — turn on binaural beats or pink noise and
  the preview sounds identical to before — so it is the one item on this list
  that touches the judgement previews exist to support. It is currently handled
  by disclosure: the mixer prints a note beside the section. Whether that is
  enough is worth revisiting once Plan 3f's help text lands, since the two are
  the same kind of problem.

## The two survivors, moved to Plan 3f

1. **Correct the 1.82 dB entry rather than acting on it.** The attribution to
   fade ordering is an inference the arithmetic contradicts. A wrong explanation
   in the documentation is worse than a known gap, because the next person
   builds on it. The measurement is small — render once at defaults, report
   where the un-faded global peak sits, how far above the 99th-percentile
   absolute sample it is, and how many samples wide — and it produces a
   sentence, not a code change.
2. **`output.sample_rate` joins `RenderSession._master_key`.** One line, and not
   really about level: `run_pipeline` resamples before normalizing, so changing
   the output rate today serves a **stale memoized gain** until something else
   clears it. That is a cache bug that happens to live in this file.
