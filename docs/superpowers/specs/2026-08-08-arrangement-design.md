# Plan 4: the arrangement — from one loop to a composed mix

**Status:** design approved 2026-08-08, not yet planned.

This is an umbrella design. It describes the end state deliberately, in one
document, and then decomposes into build phases at the bottom. That order was
the operator's choice and the reason is worth recording: the smallest piece of
this (variable gaps between repeats) is also the piece most likely to lock in a
placement model the later pieces cannot live inside. Specifying the arc first
costs some upfront thinking and buys the right to build the small piece first
without regretting it.

## What this is for

Today a mix is one loop, repeated back to back until the target duration is
reached, eroding a little more on each pass. That is the Basinski idea and it
works — but it is one shape, and every mix this program has ever produced has
had it.

The operator wants four things that are all the same thing:

- the loop **spread out** — not back to back, but with growing space between
  repeats
- loops that **overlap and play over each other**
- **several parts of one song** echoing and dissolving in alternating
  segments, rather than a single loop
- **several files** dropped in at once, extracted from and blended into one
  long mix in a bigger pattern

All four are one feature: *placement becomes a first-class thing*. Right now
there is exactly one line in this codebase that decides when a repetition
happens —

```python
stride = max(loop_frames - xfade, 1)          # disintegration.plan_iterations
```

— and it is a constant. Everything upstream of `build_disintegrating_stream`
produces *a loop*; everything downstream (reverb, gain, sum, bed, master) never
learns how many repeats there were or where they sat. The whole of this plan
lives at that seam.

## The invariant this design is built around

`preview.py` opens by stating the property the interactive half of this program
depends on:

> `apply_decay` is a pure function of progress — iteration 400 does not depend
> on iterations 1..399 — so auditioning "what does this sound like two thirds of
> the way through" costs a single loop iteration rather than twenty minutes.

**Any arrangement must remain queryable at an arbitrary point in time without
rendering what precedes it.** This is the single hardest constraint here and it
eliminates the two obvious implementations outright:

- **Generalising `build_disintegrating_stream` in place** — adding gap and
  overlap parameters to the function that already exists. It computes the
  layout *while* it renders, so answering "what sounds at 12:30" means running
  the render loop up to 12:30. Rejected.
- **A lazy generator yielding placements** — memory-light, but a generator can
  only be advanced from the start. Same fatal flaw, and memory was never the
  constraint: the plan for a twenty-minute mix is a few hundred small records.
  Rejected.

What survives is a **pure planner separated from the renderer**, which is
already the house pattern and already for this reason. `plan_iterations` is a
pure planner shared by the batch renderer and the preview. `plan_stem_configs`
is a pure planner, and `pipeline._plan_jobs` says why in its own docstring:
*"Selection lives in `config.plan_stem_configs` so the preview path cannot
drift from what the renderer actually processes."* `plan_arrangement` is that
same move, one level up.

The secondary benefit is large enough to name on its own: **the arrangement
becomes inspectable without audio.** "The gaps widen monotonically", "no
segment outlives its lifetime", "adding a fourth source does not move the first
three" are all assertions against a list of tuples, in tests that need no
Demucs, no librosa and no WAV files.

## The decisions that shaped this

Four questions were put to the operator. Each had a defensible alternative, and
the alternatives are recorded because a later reader will otherwise re-propose
them.

**The arrangement is parametric and seeded, not an explicit placement list.**
The config holds shaping parameters; a seeded generator produces the timeline.
The alternative — a config literally naming every repeat, its time and its
decay — is fully inspectable and gives total control, and is unusable: a
twenty-minute mix is roughly two hundred entries, presets become enormous, and
without a visual editor nobody is hand-editing that. A hybrid (generate, then
patch individual repeats) was also rejected: overrides index into a generated
list, so changing any upstream parameter silently re-points every override at a
different repeat. Same config plus same seed produces the same mix, always, and
a preset stays a handful of numbers.

**Decay runs on a per-segment lifetime, not one global arc.** Each segment is
born, runs its own arc from fresh to ghost, and dies; a fresh segment can enter
against an already-ruined one. The alternative — one slope shared by everything
sounding, which is what the original tape actually did — is simpler and cheaper
and produces a mix with texture but no form. Over twenty minutes the difference
is whether the piece has sections or is one long uniform slope. **Today's
behaviour is the degenerate case of the choice made:** one segment whose
lifetime is the whole mix.

**Multiple files share one pool, freely interleaved.** Every segment from every
source goes into a single pool and the generator draws from all of them. This
is the general mechanism rather than one of three options: weighting the draw
by time produces "eras" (each file owning a stretch, handing over), and
weighting it flat produces "layered" (all files throughout at reduced gain). So
choosing the pool does not rule out the other two shapes — it makes them
settings rather than separate code paths.

**Both previews are kept.** The existing seamless single-iteration preview is
unchanged and remains the right tool for tuning a stem's decay by ear — you can
sit on a sound while you shape it, which is the whole point. A second entry
point renders a real window of the arrangement at a chosen moment, overlaps and
gaps included, and plays through once. The alternative of replacing the loop
preview with the arrangement window was rejected because every slider nudge
would restart a sixty-second clip instead of updating a sound already playing.
The alternative of *not* auditioning the arrangement at all — judging it only
by rendering — was rejected because it means tuning gap and overlap blind.

## Two kinds of spacing, and why they are separate

The feature requests contained two things that sound alike and are different
axes. Conflating them is the most likely way to get this wrong.

- **Repeat spacing** — the gap between successive repeats *of one segment*.
  This is "the loop breathes": `gap_start_s` growing to `gap_end_s` along a
  curve. A negative gap means a segment overlaps *itself*.
- **Segment overlap** — how much consecutive segments' *lifetimes* overlap.
  This is "segment one is a ghost while segment two arrives clean."

They are independent. A mix can have tightly packed repeats inside widely
separated segment lifetimes, or breathing repeats inside fully concurrent
lifetimes.

## The data model

Three frozen dataclasses, in a new module `sleepmix/arrangement.py`.

```python
@dataclass(frozen=True)
class SegmentInfo:          # what the planner needs to know about a segment
    source_id: str
    index: int
    n_frames: int           # length AFTER time-stretch

@dataclass(frozen=True)
class Placement:            # one repeat, somewhere in the output
    source_id: str
    index: int
    start_frame: int
    decay_progress: float   # 0.0 fresh … 1.0 ghost

@dataclass(frozen=True)
class Arrangement:
    placements: list[Placement]
    n_frames: int
```

**`Placement` carries `decay_progress` rather than letting the renderer derive
it.** That makes the plan self-describing, so a test can assert "the fourteenth
repeat sits at progress 0.6" against plain tuples. A renderer that computed
progress itself would put that arithmetic somewhere no test could reach without
rendering audio.

**`SegmentInfo` is how the planner stays pure while still needing lengths.**
Placement positions depend on how long a segment is, which is a fact about
audio — so lengths go *in* as data. Tests pass invented ones.

## Config: four scalar additions, and no lists anywhere

```python
@dataclass
class ArrangementConfig:
    segments: int          = 1        # loop regions per source   [min 1, max 8]
    gap_start_s: float     = 0.0      # space between repeats, early  [-30 … 120]
    gap_end_s: float       = 0.0      #  ...and late                  [-30 … 120]
    gap_curve: str         = "linear" # linear | exp | log
    segment_overlap: float = 0.0      # 0 sequential … 1 concurrent   [0 … 1]
    lifetime_jitter: float = 0.0      # fraction of span              [0 … 0.5]
    order: str             = "rotate" # rotate | random
```

Registered in `_SECTION_TYPES`, with one field on `MixConfig`. **Every default
reproduces today's behaviour exactly** — one segment, no gaps, no overlap.

The bracketed bounds are `min`/`max` field metadata, not commentary.
`ui/README.md` states the rule they satisfy: bounds are the schema's job, not
the frontend's, because `Config.set` clamps every number to what the schema
declares and *"a control that can produce a value the config refuses turns a
slider into a 400 on a preview, which is a much worse way to find out."*
`MixConfig.validate` gains the matching checks.

`lifetime_jitter` is a fraction of a segment's own span, applied to both its
start and its length from the seeded generator — `0.1` means each lifetime is
displaced and resized by up to ±10% of its nominal span. Capped at `0.5`
because beyond that lifetimes reorder, and `order` is supposed to be the thing
that decides sequence.

`gap_curve` reuses `util.shape_progress`, the same linear/exp/log vocabulary
decay already speaks, rather than inventing a second set of curve names for the
operator to remember.

**Sources are not config.** `run_pipeline` already takes `input_path` as a
parameter rather than a config field, so a list of sources belongs to the render
request and the session. That is also semantically right: a preset is *how to
dissolve*, not *what to dissolve*, so presets stay portable across any set of
songs.

The consequence deserves stating plainly, because it removes what looked like
this plan's largest blocker. `config_schema` cannot describe a list — see
`_describe_fields`, which skips `stems` outright, and `ui/README.md`, which
records that `Config.elm` hand-handles `stems` as a documented structural
exception. **Nothing in this design needs that fixed.** Every new control is a
scalar or a `choices` string, so the mixer generates all of them from
`/api/schema` with no frontend change at all. The problem was routed around
rather than solved, and a future feature needing genuinely list-shaped config
will have to solve it properly.

## The planner

`plan_arrangement(segments, config, target_frames, sr) -> Arrangement`, a pure
function of its arguments and `config.seed`. It touches no audio, decodes
nothing and allocates nothing large.

**Lifetimes** are a closed form over N segments:

```
span    = target / (N - (N-1) * segment_overlap)
start_k = k * span * (1 - segment_overlap)
```

At `segment_overlap = 0` the lifetimes tile exactly. At `1`, `span == target`
and every `start_k == 0`, so all segments are concurrent. Everything between
interpolates. `lifetime_jitter` perturbs starts and lengths from the seeded
generator.

**Repeats inside a lifetime** `[t0, t1]`, laid out in two passes.

Pass one places them:

```
pos[0]   = t0
pos[i+1] = pos[i] + seg_len - xfade + gap(i)
gap(i)   = lerp(gap_start_s, gap_end_s, shape_progress(i_frac, gap_curve))
```

stopping at the first `i` whose write head `pos[i] + seg_len` reaches `t1` —
the same rule `build_disintegrating_stream` applies today with its
`if pos >= target_frames: break`, and the reason `plan_iterations` counts
iterations *executed* rather than an upper bound on them.

The `- xfade` term matters more than it looks. It is today's stride, kept
intact, with `gap(i)` added on top — so `gap_start_s = gap_end_s = 0` yields
exactly the positions `plan_iterations` produces now. **The defaults are
bit-identical to the current renderer**, which is a property to assert in a
test rather than hope for, and it is what makes this change safe to land.

**Pass two assigns decay progress, and it indexes by repeat rather than by
time:**

```
decay_progress[i] = i / max(n_repeats_in_lifetime - 1, 1)
```

This is why the layout is two passes: the count is not known until the
positions are laid out, and the progress of the first repeat depends on how
many follow it.

The obvious alternative — normalising a repeat's *position* over its lifetime,
`(pos[i] - t0) / (t1 - t0)` — is wrong, and wrong in a way this codebase has
already been burned by. The last repeat starts a segment-length short of the
lifetime's end, so progress would top out below 1.0 and **the arc would never
reach full decay in output**. That is exactly the defect `plan_iterations`'
docstring records, pointing the other way: an earlier version put
`n_iterations - 1` a full iteration beyond anything the render produced, so a
preview scrubbed to maximum decay auditioned an iteration that did not exist.

Indexing by repeat is also the musically correct reading. The metaphor is tape:
each *pass* through the machine degrades it a little more. Under growing gaps,
a mix should not decay faster per repeat merely because the repeats are further
apart in time.

With `segments = 1` and default gaps, `n_repeats_in_lifetime` equals
`plan_iterations`' `n_iter` and this is character-for-character today's
`iteration / max(n_iterations - 1, 1)`.

**Order** decides which segment takes which lifetime slot. `rotate` draws
round-robin across sources, so `A.s0, B.s0, C.s0, A.s1, …` — which is what
makes multiple files interleave rather than clump. `random` is a seeded
shuffle.

**Determinism.** Jitter and `order: random` draw from
`np.random.default_rng(config.seed)`. Per-repeat decay randomness still goes
through `util.iteration_rng`, which hashes its `stem` argument and therefore
needs no change — the key becomes `f"{source_id}:{seg_index}:{stem}"` with the
repeat index. **Adding a fourth source must not reshuffle the noise in the
first three**, which a global placement index would have done.

## The render path

`run_pipeline` takes a list of sources. The stage order barely moves:

```
for each source:  separate → stems → find_loops(reference, cfg, n=segments)
                  slice + seamless + stretch each segment  → SegmentInfo
plan_arrangement(segments, config, target_frames, sr)      → Arrangement
for each stem NAME: place every matching placement into one stream
                    → reverb once → gain → sum
bed → master
```

**Reverb still happens once per stem name, over the whole stream** — not per
placement. That is what lets a segment's tail bleed across a gap into the next
one, which is most of what "echo and dissolve" actually sounds like. It also
stays cheap: within a stem name `reverb_send` is constant and convolution is
linear, so summing two sources' vocals and reverbing once is identical to
reverbing each and summing. The non-linearity `preview.py` warns about is
across *differing* wet scales, which cannot arise inside one stem name.

**The seam rule.** Consecutive repeats can now relate three ways and the
renderer needs one rule:

| overlap | treated as | why |
|---|---|---|
| ≤ `xfade` | equal-power crossfade | it is a join — today's behaviour |
| > `xfade` | additive sum | deliberate stacking: two voices, not one seam |
| gap > 0 | nothing; silence between | the loop breathing |

Crossfading a deliberate four-second stack would duck both voices through the
overlap, which is the opposite of what "play over each other" means.

`cancel.check()` moves from per-iteration to per-placement.

## The preview paths

- **`render_window(session, progress, segment=0, ...)`** — today's function with
  one new argument. One iteration, seamless, ~100 ms, still bit-reproducible
  against the render pre-reverb. Unchanged in behaviour when `segments = 1`.
- **`render_arrangement_window(session, at_s, length_s)`** — new. Filters the
  plan to placements overlapping that span, renders each at *its own* decay
  progress, places them at their relative offsets, sums, reverbs and masters.
  Plays through once. Costs a handful of `decayed_iteration` calls.

Answering "what sounds at 12:30" is a filter over a few hundred tuples —
microseconds, no audio touched. The invariant holds.

## What breaks: `master_gain`

`preview.master_gain` measures one window and justifies it explicitly:

> decay only removes energy, so the peak falls monotonically across the arc and
> iteration 0 is the loudest window this module can produce.

**With overlap that is simply false.** Two fresh segments coinciding at minute
eight beat one fresh segment at minute zero, and a gain calibrated at frame 0
would leave the render's true peak above target.

The plan supplies the fix. For each placement compute the amplitude the decay
arc will leave it at —

```
proxy = db_to_amp(lerp(amp_start_db, amp_end_db,
                       shape_progress(decay_progress, curve)))
```

— summed over the placements concurrent at each candidate frame, taking the
argmax. Render *that* window and measure its real peak. The proxy only has to
rank candidates, not predict a level: the measurement is still a real render of
a real window, exactly as today. It remains one measured window — it merely
stops assuming it knows where. At `segments = 1, segment_overlap = 0` there is
never more than one concurrent placement and the proxy falls monotonically, so
the argmax lands on frame 0 and the behaviour is exactly today's.

Candidates are the placement start frames themselves rather than a sweep over
every frame: the sum of concurrent amplitudes only changes where a placement
begins or ends, so a few hundred candidates cover it exactly.

`RenderSession._master_key` gains `config.arrangement`, on the same test its own
docstring already applies: not whether a real render reads the field, but
whether *the calibration window's own output* depends on it. It does — the
arrangement decides which window gets measured.

## Sessions and memory

`RenderSession._prepared` rekeys from `stem` to `(segment_index, stem)`, and
`_loop_point` becomes a list from a new `find_loops`. An `ArrangementSession`
holds one `RenderSession` per source.

**Memory is the real cost and belongs in writing rather than in a later
surprise.** One five-minute stereo source is roughly 425 MB of decoded stems —
and that is *today's* footprint for a single song, not a regression. Three
sources is 1.3 GB. Two mitigations: prepared segments are small (~15 s each),
and `separate()` is already disk-cached, so raw stems can be released once every
segment is prepared and re-read from cache in seconds — no Demucs — if a loop or
tempo change invalidates them. There should also be a configured cap on
concurrent sources rather than letting it grow until the machine swaps.

## Segment discovery

`find_loop` becomes `find_loops(buf, cfg, n) -> list[LoopPoint]`, with
`find_loop` retained as `find_loops(...)[0]`.

The extension is smaller than it sounds. `_librosa_loop` already scores *every*
candidate start beat by `_seam_similarity` and keeps only the best; returning
the top N non-overlapping candidates is a sort and a greedy walk over scores
that are already computed. The `_fixed_tempo_loop` fallback and the
`_explicit_loop` short-circuit both stay: an explicit `start_s`/`end_s` pair
still produces exactly one segment, which is how a region dragged on the
waveform continues to work.

## Failure modes

Every one of these follows the rule this codebase already holds: silence must
never look like success. `NothingToRender` exists because a one-frame WAV behind
a 200 is worse than an error.

| Situation | Behaviour |
|---|---|
| Plan comes out empty (`segments=0`, or gaps so wide nothing fits) | Raise `NothingToRender`, naming the cause |
| `find_loops` yields fewer segments than requested | Degrade, **but report the real count** — the API returns segments-found alongside segments-requested |
| Negative gap exceeds segment length | `min` bound in schema metadata so the control cannot produce it, *and* clamped at plan time, since the schema cannot know segment length |
| High overlap with many segments → N fresh voices at once | Not an error: a `Warn`-style sentence, the pattern `Warn.forSource` already establishes |

The second row is the one most likely to be got wrong. A track too short to
yield five non-overlapping eight-bar loops must not quietly render one segment
and look like success — that is precisely the class of plausible lie the
`Warn` module and the strict decoders exist to prevent.

**N sources means N separations before a render can begin, on one worker.**
This is a job-model change — a render that depends on N separation jobs — and it
makes `Warn`'s existing single-worker sentence more load-bearing, not less. It
is the largest non-audio risk in this plan.

## Testing

The planner being pure is the payoff: most of this runs in milliseconds against
invented `SegmentInfo`, with no audio, no librosa and no Demucs.

**`tests/test_arrangement.py`** — defaults reproduce today's placements exactly;
gaps widen monotonically when `gap_end_s > gap_start_s`; `segment_overlap = 0`
tiles lifetimes and `1` makes them concurrent; the same seed yields an identical
plan and a different seed does not; adding a fourth source moves neither the
first three's placements nor their rng keys; no placement starts past
`target_frames`; an empty plan raises rather than returning `[]`.

**The decay arc reaches both ends, in every lifetime.** Its own test, asserted
per segment and across gap settings: the first repeat sits at exactly `0.0` and
the last at exactly `1.0`. This is the guard on the two-pass layout — the
time-normalised formula rejected above passes every other test in this file
while quietly capping the arc below full decay, which is inaudible in a diff
and obvious only in a twenty-minute render nobody re-listens to. It is also the
same defect `plan_iterations` was fixed for once already, and a test that would
have caught it the first time belongs here now.

**Renderer** — against small synthetic buffers, in the style the suite already
uses: overlap ≤ `xfade` crossfades, overlap > `xfade` sums, and `gap > 0` leaves
actual silence.

**Bit-identity regression** — render a fixture with arrangement defaults and
assert it matches the pre-change renderer. This is the test that makes the whole
change safe to land, and it is only available because the defaults were designed
to reproduce today.

**`master_gain`** — two overlapping fresh segments select a window that is not
frame 0; `segments = 1` still selects frame 0.

**Preview parity** — `render_arrangement_window` at T carries the same pre-reverb
material the full render carries at T, mirroring the existing preview/render
bit-identity check.

**Schema round-trip** — every new field survives `/api/schema` → `Config.encode`
→ `MixConfig.from_dict`. `docs/project-state.md` already flags that
`Fixtures.elm` and the server schema are verified independently and never
against each other; this change adds fields at exactly that seam, so the
Python-side round-trip carries more weight than usual.

Test isolation needs no new work: `tests/conftest.py` already points
`SLEEPMIX_DATA_DIR` at `tmp_path` under an `autouse` fixture for every test
whether it asks or not, and `fake_separate` keeps Demucs out of the suite.

## How this decomposes

Three plans, in this order. Each is independently shippable and audible.

**Plan 4a — placement.** `arrangement.py` with the planner and its tests,
`ArrangementConfig`, the renderer reading a plan, the seam rule, `master_gain`'s
argmax, and the bit-identity regression. Still one segment and one source, so
`find_loops` and the session changes are not needed. Delivers breathing and
self-overlapping loops. **No frontend work whatsoever** — the mixer generates
the new section from the schema.

**Plan 4b — segments.** `find_loops`, `RenderSession` rekeyed to
`(segment_index, stem)`, per-segment lifetimes exercised for real, the
segments-found-versus-requested report, `render_window`'s `segment` argument.
Delivers alternating segments that dissolve on their own clocks.

**Plan 4c — sources.** `ArrangementSession`, multi-source `run_pipeline`, the
job model for a render depending on N separations, the source cap and stem
release, multi-file upload and the renders/queue screens catching up. The
largest, and the only one that touches the store and the job queue.

`render_arrangement_window` and its button belong to 4b — it is not useful with
one segment and no overlap, and it is essential the moment there is more than
one thing sounding.

## What this deliberately does not do

- **No visual arrangement editor.** The operator ruled it out, and it is what
  makes the parametric model the right choice rather than a compromise.
- **No per-source config.** All sources are shaped by one global config. Per-source
  gain or tempo would need the schema to describe lists, which nothing else here
  requires.
- **No tempo or key alignment across sources.** Every source is slowed by the
  same `tempo.speed`; sources at different original tempos will not be
  rhythmically aligned. For this material that is acceptable and arguably
  desirable, and revisiting it is a separate question.
- **No explicit placement overrides.** Rejected above, and it should stay
  rejected unless a visual editor ever exists to make overrides addressable.
