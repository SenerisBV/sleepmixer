# Plan 5, Phase 3: the ghost — source material and its own double

**Status:** design approved 2026-08-18, not yet planned.

Phase 1 (`docs/superpowers/specs/2026-08-18-night-stream-design.md`) built an
indefinite, self-quieting stream out of synthesized voices. This is the phase
that spec named as the eventual goal and deferred: *source-derived early,
synthesis late*. Phase 2 — the microphone — has been **skipped**, not merely
reordered; see "Why the microphone went away" below.

## What this is for

The operator's first instinct, when asked what an eight-hour night should be
made of, was "source-derived early, synthesis late sounds most interesting,"
with an explicit offer to start without the source-derived half to prove the
concept. The concept is proved: Phase 1 shipped, was listened to, and works.
This is the half that was deferred.

The reason it was worth deferring rather than cutting is that the erosion
which gives this program its character was written for tape and for recorded
material. Phase 1 applies it to synthesized drones, which was a deliberate
stretch — the palette's two generators are *designed to be dirty* precisely
because `apply_decay` behaves best on material that already has noise and
drift in it. Feeding it real recorded audio is the case it was built for.

## Why the microphone went away

Phase 1's spec scheduled adaptive masking — the stream reading the room's own
noise floor through a microphone — as Phase 2, and called it the most valuable
steering input in the design because it was the only closed loop.

It is skipped, and the reasoning is worth recording because it was not a
scoping retreat.

**The operator chose a ceiling that only ever lowers.** Asked what the stream
should do when the room gets noisier, the answer was: the room may make the
stream quieter but never louder. That single choice removes the danger the
microphone was mostly interesting for. A stream the microphone mistakes for
room noise leads to *less* reduction, which tops out at the arc's own ceiling —
so being masked by your own masking becomes impossible by construction, and
the worst case degrades to the feature quietly doing nothing.

**But the loop inverts rather than vanishing.** A quiet room lets the stream
sink; a sunken stream reads quieter still; which lets it sink further. Left
alone that runs to silence — the stream listening to its own absence and
concluding it should disappear. Same feedback, opposite direction, arriving at
11 PM in a quiet house rather than at 4 AM in a noisy one.

**So the work did not shrink as much as the risk did**, and what remained
bought less than Phase 3 does. A microphone varies what already exists; source
material changes what the night is made of. The operator chose accordingly.

**One finding from that discussion is worth keeping**, because it will still be
true whenever the microphone is revisited. The favoured escape from the
feedback loop was spectral subtraction of the known output — and that is the
*only* option with setup-specific work in it, since it needs a model of the
acoustic path from speaker to microphone. There is a better one available for
free: the arc lowpasses everything to `brightness_hz`, sweeping 6000 Hz down to
500 Hz across the night, and after Phase 1's noise-floor fix only **0.85% of
block energy** sits above that ceiling. So there is a wide, known,
guaranteed-quiet band above the arc's own corner where a microphone hears
essentially nothing but the room — and it gets quieter up there as the night
goes on. Measuring the room in the band the stream has vacated is
setup-independent, cheaper than subtraction, and exploits a property this
design already guarantees about itself. Two things could spoil it and both are
a short spike to check: laptop microphones are often bandlimited and noisy
above 8 kHz, and a low rumble has little high-frequency energy to be detected
by.

## The decisions that shaped this

**The dissolve is the material becoming its own ghost.** Four readings of
"source-derived early, synthesis late" were put up. Two independent layers
crossfaded by the arc was rejected as sounding like two things sharing a room
rather than one thing changing. Carrying it inside `apply_decay` was rejected
because that is the most load-bearing and most carefully tested function in the
codebase — Phase 1's own final review found that its noise floor escaped three
of the night's guarantees at once, which is not an encouraging place to add a
feature. A hard handover partway through the night was rejected for putting a
single audible event in the middle of a night every prior decision has spent
itself removing.

What was chosen: analyse the prepared loop, find the pitches actually present
in it, synthesize drones from its own spectrum, and let the real thing give way
to its synthetic double. The two halves are the same material. **The synthesis
is in the source's key because it is derived from it, not because anything
detected a key** — which also means the seed's job shrinks to choosing *which*
material and *when*, never what pitch anything is.

**The transition happens across the night, with occasional ghosts that
outlive.** A voice lives minutes; a night lasts hours; "early and late" could
mean either scale. Within-voice morphing was rejected because every voice would
then perform the same gesture, and a repeated gesture is the failure mode this
design worries about most. Ghosts-outliving-their-source alone was rejected as
the *rule* for the opposite reason: it creates a moment each time — the loop
stops and something remains — and moments wake people.

The chosen shape is a birth ratio as the eventless default, with outliving
ghosts as an occasional event rather than the norm.

**"Occasional" needs one qualification, or this contradicts the handover
rule below.** An outliving ghost happens in two circumstances and they are
not the same: *systematically* at every handover between sources, where it is
the structural device that hides the seam, and *occasionally* within a
source's stretch, where it is the flourish. The first is not a stylistic
choice and cannot be tuned down to nothing without reintroducing the event it
exists to cover; the second is the one whose frequency is a placeholder.

**Preparation never happens at bedtime.** Demucs on a laptop spins the fans up
for several minutes, next to the bed, which defeats the entire product. So
`sleepmix night` stays optionless and instant and uses only what is already
prepared, and a separate `sleepmix prepare` does the expensive work whenever it
suits. A folder was chosen over the existing web library because a tool whose
premise is one command should not require a web interface to have been used
first — and it mirrors how a comfort show already reaches the speech layer.

**Clearly music, not identifiable.** Asked whether the source should be
recognisable, the operator chose obscurity over familiarity — which is the
opposite of the choice made for the speech layer, and deliberately so. A
comfort show works *because* you know it; a piece of music you can name has
form, and form creates expectation. This is the same axis the speech layer's
"two doors" section describes, and music takes the other door.

## A ghost is its own `Voice`, not a mode of one

**This is the load-bearing decision and it is what makes the rest small.**

The planner emits source voices and ghost voices as separate records. That one
choice delivers both halves of the chosen dissolve with no special case:

- **The birth ratio** is the relative gain of a co-located pair. Early in the
  night the planner emits pairs weighted heavily toward the loop; late in the
  night it emits ghosts alone.
- **A ghost that outlives its source** is the same pair with a later death on
  the ghost. Nothing new is needed; the lifetimes simply differ.

The alternative — one `Voice` carrying a blend parameter that changes over its
life — needs a second mechanism for outliving, and puts a time-varying quantity
inside a record whose whole value is being a static description of one thing.

Phase 1's spec anticipated this exactly: *"`night/plan.py` yields `Voice`
records that name a source of material rather than a generator... If a `Voice`
ever grows a field that only makes sense for synthesis, that is the moment
Phase 3 got harder, and it should be treated as a design error rather than a
convenience."* No such field was ever added. The seam held.

## `sleepmix prepare` and the `SourceProfile`

`sleepmix prepare` walks a sources folder under `paths.data_dir()`, and for
each song not already cached it runs the pipeline this repository already has:
`separation_process.run_separation` (killable, subprocess-isolated),
`analysis.find_loop`, and `timestretch`. It writes a `SourceProfile`.

A `SourceProfile` holds:

- the stems kept, as cached audio on disk
- a small number of short loops, already stretched — enough that a stretch of
  the night has internal variety without any one of them recurring often;
  two to four is the first draft and is a placeholder
- **the pitch set** — the frequencies actually present in each loop
- the loop's length, and enough metadata for the planner to reason about it

**The pitch set is extracted by spectral peak-picking with octave folding, not
by chroma or key detection.** "Its own ghost" should be true in the specific
sense: the drones sound at frequencies that are physically in the material, not
at the notes of a key some estimator inferred from it. Octave folding keeps the
set compact and lets a ghost sound an octave from where the source did without
inventing a pitch. Key detection would produce a more musicological answer and
a less honest one.

**Nothing in a `SourceProfile` is audio as far as the planner is concerned.** It
is a path, a length and a list of numbers. `night/plan.py` keeps its AST guard
and its no-audio rule unchanged, and an eight-hour night still plans in
microseconds. This is the same discipline `arrangement.py` lives by, for the
same reason.

## Sources take turns, and the handover is covered by the mechanism already chosen

Concurrent voices drawn from *different* songs would be mud — different keys,
different rooms, different tape. So **one source holds the stage at a time**,
for a stretch of the night, and concurrent voices within that stretch come from
the same source: its several loops, at several pitches from its own set.

Handing from one source to the next would be an event, except that it is
covered for free by the thing the operator already chose. **The outgoing
source's ghosts outlive it and overlap the incoming source's loops.** At the
moment of handover you are hearing the double of the last piece of music while
the next one arrives underneath. The gesture the operator selected as an
occasional flourish turns out to be the structural device that makes
large-scale form possible without a seam.

**The planner prefers a next source whose pitch set is close to the outgoing
one.** That is a cheap sort over lists of numbers at plan time — no audio, no
new dependency — and it means the overlap during a handover is consonant rather
than a collision. With one source in the folder the rule is inert.

The night's root follows the source in play rather than the seed, with Phase
1's slow descent applied on top. With an empty sources folder the whole system
degrades to exactly Phase 1 — seed-rooted, purely synthetic — which is also the
honest state before `prepare` has ever been run.

## What "form never asserts itself" means in numbers

Recognisability is not a switch; it is the sum of four quantities, and all four
are first drafts nobody has heard:

- **Loop length 4–12 s.** Long enough not to stutter, short enough to carry no
  phrase. `analysis.find_loop` currently targets musically-sensible bar counts;
  the night wants notably shorter than a render does.
- **Time-stretched to roughly 0.5–0.7×**, which pulls gesture below the rate at
  which the ear tracks phrasing.
- **Lowpassed by the arc from birth**, which is already true — even at 22:30
  the ceiling is about 6 kHz, so nothing is ever heard at full bandwidth.
- **The birth ratio is capped below 1.0.** Even the most source-derived voice of
  the night carries some of its own ghost. **You never hear the unprocessed
  loop alone**, at any hour, which is the single most direct implementation of
  "clearly music, not identifiable."

## What carries over unchanged

Phase 3 adds a kind of voice. It does not restructure the night.

- **The two nested clocks**, and the rule that a voice born at hour six may not
  start bright. A source voice is built under the arc's ceilings exactly as a
  synthesized one is.
- **Block independence.** A prepared loop is a deterministic file on disk; a
  ghost is a deterministic function of its profile's pitch set. `render_voice`
  gains two branches and stays pure. The invariant needs no new argument.
- **The speech layer**, mixed live at playback, still excluded from that
  invariant by necessity.
- **The steering table**, including the row that still does nothing — see
  below.
- **Degrade silently.** A profile that fails to load costs its voice, not the
  night.

## Failure modes

- **Sources folder empty, or `prepare` never run** → pure Phase 1. Not an
  error, and the CLI should say which mode it is in at startup, where it
  already prints two lines.
- **A `SourceProfile` that will not load** → skip that voice, keep the night.
  Phase 1's final review moved degradation granularity from the block to the
  voice for exactly this class of failure.
- **A profile whose loop file has gone** (the operator moved a folder) → the
  same, and `prepare` re-derives it next time it runs.
- **`prepare` interrupted** → the separation cache is already written
  atomically by a staging-directory rename, so a killed prepare leaves either
  the previous complete profile or none.

## Testing

- **Block independence, again and specifically for source voices.** The
  existing check must extend to a night with sources in play, including across
  a handover, where two sources' material overlaps.
- **The planner, against invented profiles.** Because `plan.py` still touches
  no audio, an eight-hour night with six sources taking turns is a unit test:
  that handovers are always covered by an outliving ghost, that the birth ratio
  is monotone and never reaches 1.0, that no voice is born above the arc's
  ceiling, and that the next-source preference actually reduces pitch-set
  distance.
- **The pitch set against known material.** Synthesize a buffer with known
  partials, run the extractor, assert it finds them and folds octaves.
- **`prepare` is idempotent** and re-running it costs nothing for an unchanged
  source.
- **The empty-folder path** produces bit-identical output to Phase 1 at the
  same seed. That is the strongest available statement that this phase is
  additive.

## Placeholders — every one of these wants ears

Recorded here so they are not later mistaken for considered values, in the
tradition `docs/project-state.md` keeps:

- Loop length 4–12 s, the time-stretch range 0.5–0.7×, and how many loops
  `prepare` extracts per source (two to four).
- The birth-ratio cap, and the curve by which the ratio falls across the night.
- How long a source holds the stage before handing over.
- How often a ghost outlives its source — "occasional" is not yet a number.
- The peak-picking threshold: how many partials make a pitch set, and how loud
  a peak must be to count.

## What this deliberately does not do

- **No microphone.** Skipped, with the reasoning above and the empty-band
  finding preserved for whenever it is revisited.
- **Wind → drift depth is still a dead steering row.** It was offered as
  smaller work and passed over for this. One of six rows still does nothing,
  and `docs/project-state.md` says so.
- **No ambient light, no twilight-keyed arc.** Both were considered in the same
  discussion. Ambient light is the most interesting non-audio input available —
  a room going dark is the best proxy for *you have actually gone to bed*,
  which nothing in the system knows — and it may not be readable at all on
  Apple Silicon. It needs a spike before it needs a design.
- **No recognisable playback of a named piece.** The operator chose obscurity;
  the birth-ratio cap enforces it.
- **No per-source treatment settings.** Tempting, and it would let a field
  recording and a record be handled differently — but a decision per song is
  precisely the trial-and-error friction this whole project set out to remove.
- **No web UI for `prepare`.** The library screen already exists and can grow
  one later; the point of this phase is that one command works without it.
