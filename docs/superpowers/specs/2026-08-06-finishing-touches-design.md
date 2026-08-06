# Plan 3g: the sound bed in previews, and help a screen reader can find

**Status:** design approved 2026-08-06, not yet planned.

## What this is for

`sleepmix` separates a song into stems, finds a loop, and repeats that loop for
half an hour while eroding it — the mix disintegrates as you fall asleep. Its
mixer lets you hear any point in that decay arc before committing to a render.

Two things it does not do yet, both recorded as known gaps and both now worth
closing. They are unrelated in subject and share a plan only because each is
small.

## Part 1 — the sound bed in previews

### The gap

`preview.render_window` sums only the configured stems and never calls
`build_soundbed`. `pipeline.run_pipeline` adds the bed before mastering
(`pipeline.py:73-76`). So enabling pink noise or binaural beats changes nothing
you can hear in the mixer, and the mixer currently discloses that with a note
beside the section rather than fixing it.

Every other recorded preview-versus-render difference is a matter of **level**.
This one is **character** — and character is the judgement previews exist to
support. That is why it outranks the level items that were deliberately left
alone when Plan 3e was retired.

### The change

`render_window` builds the bed and adds it after the stem sum and before the
master gain, mirroring where `run_pipeline` puts it.

**The bed is generated per window, not sliced out of a full-length one.** Noise
is stationary and a binaural beat is periodic, so a window-length bed is
perceptually identical to the corresponding slice of a long one — and building
twenty minutes of noise in order to take twenty seconds of it would be absurd.
This is written down because it is exactly the kind of thing a later reader
"corrects" into a slice for the sake of exactness that does not exist.

**The rng is derived from `config.seed`, the way `run_pipeline` derives its own**
(`pipeline.py:45`). This matters less for the audio than for stability:
`master_gain` memoizes a factor measured from one calibration window, and a
window containing freshly random noise would make that factor depend on which
draw happened to occur.

**One honest caveat.** `run_pipeline`'s rng has advanced by an unknown amount by
the time it reaches the bed, so the preview's noise will not be the *same
samples* as the render's at the same position. It is inaudible — noise is noise
— but the documentation must not claim the two match sample for sample.

### Two consequences that must land together

**The calibration window now contains the bed**, which closes the fourth of the
recorded calibration-window gaps: the sound bed's absence, measured at +0.03 dB
at the default `noise_gain_db = -34`. `docs/project-state.md` should record it
as closed by this plan rather than left open.

**`config.soundbed` must join `RenderSession._master_key` in the same commit.**
Today its absence from the key is *correct*, and was verified as such: nothing
in the preview path reads it, so nothing about the bed can move the memoized
gain. The moment `render_window` reads it, that stops being true, and toggling
the bed would serve a factor measured without it.

This is the one place in the plan where a previously-right decision becomes
wrong, and splitting the two changes across commits would ship a real bug in
between. The last plan added `output.sample_rate` to that key and had to revert
it, because `render_window` never resamples and the change was a measured no-op
— **this one is the opposite case, and the test must show it**: a `master_gain`
that genuinely differs with the bed on and off.

### The one place this interprets rather than follows

**The bed is absent when a stem is soloed.** The operator's instruction was
"always, matching the render", and a solo already does not match the render —
the render has every enabled stem. Solo is a diagnostic act, and a bed over an
isolated stem masks the thing it was isolated to hear. Approved as an exception
when the design was presented.

## Part 2 — help a screen reader can find

### The gap

Plan 3f replaced a hover tooltip with visible help text, which fixed sighted and
touch users. It did not fix screen readers: `p.field-help` is a *sibling* of the
control with no programmatic association, so focus landing on the input
announces nothing.

### The change

`span.field-label` becomes a real `<label for=…>`; the help `<p>` gains an id;
the control gains `aria-describedby` pointing at it.

**This needs a new `domId : Target -> String`, and `Config.keyOf` cannot be
reused.** `keyOf` returns the bare field name — it discards the section and the
stem index, because values live in per-section dictionaries keyed by bare name.
That is correct for what it is for and useless as a DOM id: every stem's
`enabled` would collide with every other stem's, and with `stem_decay`'s. Two
functions, two jobs.

`domId` must be stable across re-renders and unique across the page, including
across stems.

### Testing

Both halves are markup, so `elm-test` reaches them through `Main.view` without a
browser — which matters, because nobody in this loop can run a screen reader
either. Assert that every control's `id` matches its label's `for`, and that a
control with help carries `aria-describedby` matching that help's id. Assert
uniqueness across a fixture with more than one stem, since that is the case
`keyOf` would have broken.

## Failure modes the plan must handle

- **A preview that includes the bed while the calibration window does not**, or
  the reverse — the two must agree, or every preview is mis-levelled by the
  bed's contribution.
- **A stale `master_gain` when the bed is toggled**, which is what the
  `_master_key` change prevents.
- **A `domId` that collides** across stems or sections, which would point two
  controls at one label.
- **A test that passes against no association at all.** Every assertion here is
  about attributes that are easy to render as empty strings; each must be shown
  to fail when the attribute is dropped.

## Out of scope

- The remaining calibration-window gaps: the inter-iteration crossfade summing
  (+0.37 dB dry, ~0.01 dB with default reverb) and the fade ordering, whose
  1.82 dB was traced in Plan 3f to a synthetic 30-second test fixture and does
  not describe the mixer's real default.
- A separate audition control for the bed alone. Considered when the design was
  presented and not taken; the bed being in every preview is the whole point.
- A path allow-list for `import_song` and authentication. Ruled out this session
  on the grounds that the server binds `127.0.0.1`, carries a Host allow-list
  against DNS rebinding, sets no CORS headers, and takes JSON-only bodies —
  **conditional on `--allow-remote` never being used**, at which point both
  become necessary.
