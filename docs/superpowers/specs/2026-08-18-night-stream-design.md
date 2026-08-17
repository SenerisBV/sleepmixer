# Plan 5: the night — from a finished mix to a stream that never ends

**Status:** design approved 2026-08-18, not yet planned.

This is an umbrella design in the same sense the arrangement design was: it
describes an end state in one document and decomposes into phases at the
bottom. The reason is the same reason, pointing at a different risk. The piece
being built first (a synthesis-only stream) is the piece most likely to lock in
a composition model that the eventual goal — recognisable material dissolving
toward synthesis across a night — cannot live inside. Specifying the whole arc
first costs some thinking now and buys the right to build the small piece
without regretting it later.

## What this is for

Everything this program has produced so far is a *file*. You tune a song, you
render twenty minutes, and you have a thing. The operator named two frictions
with that, and they are not the same friction:

**Authoring is trial and error.** Getting a mix that actually works for sleep
takes many passes over forty-odd controls, and the feedback loop is slow
because the judgement you are making — *can I fall asleep to this* — cannot be
made in a preview window. It can only be made in bed, once, per night.

**What you get is static and finite.** It ends. And the ways of not-ending that
exist in the world all fail in the same shape: a playlist has bad changeovers,
autoplay walks away from what you chose one track at a time until it is playing
something you cannot sleep to at 3 AM, and a single track on loop becomes
monotonous enough to be grating.

The two reference points are
[youarelistening.to](https://youarelistening.to) and Endel, and the operator's
read on why each works is the thing this design is built out of.

**YALT works because of the speech.** Sparse ambient or post-rock under
police scanners, air traffic control, shipping forecasts, a Bob Ross channel.
The voices float in and out; they are not continuous. The static of the radio
feeds is doing real work — it creates variation while keeping the speech
obscure enough that no narrative forms. The result is a human texture over a
drone, and it smooths over exactly the monotony that would otherwise make the
music grating.

**Endel works because it varies.** The sounds change according to something
outside themselves — time of day, weather, the listener's own state — so it is
never quite the same twice and never has to end.

The thing this design wants is both: a stream that runs all night, that evolves
without becoming energetic, that carries human presence without demanding
attention, and that gets **quieter and sparser as the night goes on** — which
was the operator's own strategy and is the single clearest thing in the brief.

## The invariant this design is built around

`preview.py` opens by stating the property the interactive half of this program
depends on, and `docs/architecture.md` calls it the load-bearing one:

> `apply_decay` is a pure function of progress — iteration 400 does not depend
> on iterations 1..399 — so auditioning "what does this sound like two thirds
> of the way through" costs a single loop iteration rather than twenty minutes.

That property was engineered in — `util.iteration_rng` derives a generator from
`(seed, key, iteration)` alone precisely so that no iteration depends on how
many random numbers its predecessors consumed — and it was engineered in for a
completely different purpose: making a preview cheap.

**It is also, exactly, the guarantee an indefinite stream needs.** A stream
that runs for eight hours cannot be a buffer. It has to be produced in pieces,
ahead of playback, and a piece has to be *correct on its own* — computable
without reference to the seven hours that precede it. That is block
independence, and it is the same sentence as the purity property with the word
"iteration" replaced by "block".

So the invariant for this plan is:

**Any block of the night's music must be renderable without rendering what
precedes it, and must be bit-identical to the corresponding slice of a
continuous render.**

This is asserted numerically rather than argued. See "Testing" below. If it
ever fails, block independence was a hope rather than a property, and the
architecture is wrong rather than buggy.

**The invariant is scoped to the music deliberately, and the speech layer is
excluded from it by necessity.** Live speech cannot be deterministic — a block
rendered thirty seconds ahead of playback would carry whatever transmission was
audible thirty seconds ago, and a sequential render would carry a different one.
That is not a defect to engineer around; it is what *live* means. The
consequence is architectural rather than cosmetic and is worked out under "The
speech layer is mixed at playback" below: the deterministic layer is rendered
ahead, the live layer is summed at the output, and the boundary between them is
exactly the boundary of this invariant.

## The decisions that shaped this

Six questions were put to the operator during design. The answers are recorded
here with their reasoning, because several of them cut off large amounts of
work and the reasons are not re-derivable from the code.

**Who listens, and where the audio is mixed: local now, hosted possibly
later.** "Just me now, and for a while as I tune it. If I end up using it
consistently, it would be great to make it available via web or app."

This decides the legal question about voice feeds almost entirely, and it is
the reason the speech layer is an *interface* rather than a feed integration.
Tuning a public shortwave receiver, or listening to a scanner feed, or playing
media you own, are all ordinary personal listening. Mixing any of them into a
stream other people can hear is redistribution, and the sources YALT itself
uses have closed that door since YALT was built:

- **Broadcastify** — the police-scanner backbone, and what YALT embeds — now
  runs a Developer Program permitting AI/ML, private transcription, research
  and internal dashboards, and explicitly prohibiting consumer-facing scanner
  apps and public redistribution of live audio. YALT survives because the
  *listener's own browser* connects to Broadcastify; the site never touches the
  audio. A server that mixes scanner audio into a stream is doing the thing the
  terms name.
- **LiveATC** is blunter: streams "may not be used in any third-party
  products."
- **OpenMHz** is the friendlier cousin — SDR-captured, per-transmission,
  ~225 US trunked systems, a 30-day archive, and third-party projects pull from
  it routinely. There is no formal public API document. Worth a direct ask
  rather than an assumption if it is ever wanted.
- **KiwiSDR / WebSDR** is what this design uses instead, and not as a
  concession. Roughly 800 public shortwave receivers worldwide, up to eight
  simultaneous connections each, tunable over a websocket with a documented
  Python client (`jks-prv/kiwiclient`), demodulation done receiver-side. You get
  real HF: fading, atmospheric static, signals drifting in and out of
  readability. **The ionosphere supplies the obscurity, so nothing has to
  simulate it**, and it varies on a schedule nobody controls.

**What the music is made of: synthesis first, source-derived material later.**
The operator's preference was for recognisable material early in the night
dissolving toward pure synthesis by the small hours — "source-derived early,
synthesis late sounds most interesting" — with an explicit offer to start
without the source-derived half: "we can start without source-derived if that's
easier to prove out the concept and add it in a future phase if worthwhile."

Starting synthesis-only is the right call and it is genuinely easier. It
bypasses the entire expensive half of the existing pipeline — no Demucs, no
loop detection, no time-stretch, no `RenderSession` staging, no
preview-versus-render level matching — while `apply_decay` applies unchanged,
because it operates on an `AudioBuffer` and does not care where the buffer came
from. The erosion that gives sleepmix its character is preserved; only the
material changes.

**One risk is named now rather than discovered later:** if the synthesis-only
version turns out good on its own, the source-derived phase may never feel
necessary, and designing the handover retroactively is harder than designing it
in. The seam is therefore kept visible throughout — see "How this decomposes".

**Steering inputs: weather, season and moon first; microphone second.** The
operator selected the room's noise floor via microphone, local weather and
season, and moon phase, with "we can do these in phases."

The clock, alarm and sunrise option was framed during design as the baseline
that would come along regardless, and was not separately selected. It is
treated as included, because without it nothing drives the sparseness arc that
is the operator's own stated strategy. If that reading is wrong the design's
spine is wrong, so it is written down here as an assumption rather than left
implicit.

**Solar cycle was floated by the operator and is rejected.** It moves on an
eleven-year timescale, and daily geomagnetic indices are noise to a sleeping
human. It is a *story* input — something true that can be said about the
system — rather than something anyone perceives. Endel's real work is being
done by time of day and circadian phase, with the cosmic material as narrative.
Moon phase survives on the same charge because it is free, arithmetic, and can
be given one small honest job (see "Steering").

**The microphone is Phase 2, and the reason is a specific engineering
problem.** Adaptive masking — the stream rising to cover a passing truck and
sinking when the room goes quiet — is the most valuable input in the list,
because it is the only *closed* loop and the only one that changes what is
heard rather than what the generator abstractly decides. It is deferred because
**the microphone hears the stream.** Naive adaptive masking is positive
feedback: stream rises, mic reads it as room noise, stream rises again, and by
4 AM the listener is being masked by their own masking. Escaping that needs one
of echo cancellation, spectral subtraction of the known output, sampling only
during the stream's own quiet moments, or measuring only in bands the stream
deliberately leaves empty. That is the difference between a weekend and a
month, and it is why something cheaper goes first even though this is worth
more.

**Speech is live, not harvested.** A harvested pool — a daytime job pulling
hours of HF into a store the night draws from — was recommended during design
on robustness grounds: no realtime network dependency, works with the wifi off,
far politer to a volunteer's eight-slot receiver than an eight-hour connection.
The operator chose live anyway, and the reason is the one that matters:

> "Great observation about why live is emotionally load-bearing."

Live preserves the property that *someone is awake somewhere right now*. You
are hearing tonight, not a recording of some previous night. That is a real part
of why YALT works and a pool cannot reproduce it. The cost — a hard network
dependency at the worst possible hour — is answered by the failure rules below
rather than by architecture: the speech layer is allowed to disappear, silently,
and the music continues.

**And a second speech source arrived with it, which reframed the whole
layer.** The operator: "Something I used to fall asleep to was Cheers, and I
think it's possible a lot of things like that might be material in some way."

A police scanner and *Cheers* are **opposite routes to the same
destination.** The scanner is unfollowable *through obscurity* — clipped,
coded, half-buried in static, no thread to pick up. A comfort show is
unfollowable *through familiarity* — you already know how the scene ends, there
is no suspense left, and the laugh track is a room full of people being fine.
Both remove narrative tension; neither makes a claim on your attention. The
unifying principle is that the speech must carry **human presence without a
claim on you**, and there are two doors to it.

The treatments differ, and both are about distance. Radio is distant in
*space*. A comfort show is distant *through a wall* — and that is not a
workaround for the fact that sitcom dialogue is intelligible, it is the actual
thing being reproduced: a TV on in the living room while you fall asleep on the
couch. For a lot of people that muffled-through-a-wall spectrum *is* the sound
of being safe, and it is worth being explicit that this is an emotional target
and not an acoustic accident.

**Control surface: one button, no options.** "Press start, no config to start.
we'll add more buttons someday but want to see how it goes without options
first."

This answers friction one directly and it has a consequence worth stating: with
no config there is no alarm time, so there is nothing for a wake ramp to aim
at. Phase 1 descends toward near-silence over an assumed night and stops. A
system that guesses when you are getting up and is wrong is worse than one that
does not try.

**Architecture: an unbounded plan, rendered a block ahead.** Two alternatives
were put up and rejected.

- **A true realtime DSP graph** — voices, filters and a mixer in an audio
  callback, steering applied instantaneously. This is how Endel-shaped things
  actually work and it is the natural architecture for a hosted browser
  version. Rejected for Phase 1 because `apply_decay` is a buffer transform and
  not a streaming processor, so none of the existing engine survives the move,
  and because realtime discipline (no allocation in the callback, no blocking)
  is a cost paid for the benefit of exactly one steering input — the one that is
  deferred anyway. If a hosted version is ever built, the planner ports and the
  renderer does not, which is the right half to keep.
- **A long render with live layers on top** — ninety minutes rendered offline
  with the existing pipeline, looped, with only speech and level trims live.
  Cheapest by a wide margin, and it fails the brief: a ninety-minute loop is a
  loop, and the seam will be audible by night three. This is the thing the
  operator set out to escape.

## Two nested clocks, and the night one always wins

**This is the core of the design and everything else hangs off it.**

Today's decay arc runs across one loop's repetitions: a voice is born bright
and full, erodes, and the mix ends when the arc ends. One clock, and it is why
the output is finite by construction — the arc has an end written into it
(`amp_end_db`, `lowpass_end_hz`), so a single loop stretched over eight hours
either dissolves to nothing partway through or has to plateau and stop
evolving.

The night model nests two clocks:

- **The night arc.** One monotone descent from start to end, hours long, never
  resets. It governs four quantities: **density** (how much sounds at once, and
  how much space is between things), **brightness** (the lowpass corner),
  **level** (amplitude), and **intelligibility** (see the speech layer). Three
  of those four are the vocabulary the disintegration engine already speaks.
- **A voice's own lifetime.** Minutes, not hours. A voice is born, decays
  through its own arc, and dies. Many come and go across a night.

**A voice born at hour six does not get to start bright.** Its own arc is
scaled inside whatever the night arc permits at the moment of its birth, so it
enters already dark and already quiet, decays from there, and dies. That single
rule is the whole trick:

- The stream never restarts even though its constituents constantly do.
- Nothing can inject fresh energy at 4 AM, because the ceiling has already come
  down. The night arc is not an automation curve laid over the top that a loud
  voice could fight — it is a **constraint on what may exist at all**.
- "Quieter and sparser as the night goes on" is structural rather than
  cosmetic.

The nesting is also what makes the finiteness problem go away without inventing
anything. Each voice's arc still has an end, exactly as today; it is only the
*sequence* of voices that is unbounded. Nothing about `apply_decay` changes.

## The night's length is read from the sky

Sunrise and sunset are arithmetic from coordinates — no network, no key, no
service. At Dutch latitude a December night and a June night are roughly nine
hours of darkness apart across the year, and a stream that knows this is
genuinely a different thing in winter.

So the arc normalises against **time until sunrise**, not against a fixed eight
hours, clamped to a sane band so that starting at 3 AM in June does not
compress the whole descent into ninety minutes. The clamp bounds are a
placeholder (see below) but the shape is: roughly six hours minimum, roughly
ten maximum.

This is the cheapest of every steering input considered, and it is likely to be
the one that most reliably makes winter feel different from summer without
anyone being able to say why.

## The palette

Phase 1 generates its own material. Three rules govern it.

**No transients, ever.** Every voice fades in over seconds and out over
seconds; nothing has an attack. That single rule is most of the difference
between ambient and music, and it is the one that keeps *evolution* from
becoming *energy*. A voice may change what it is doing; it may never *start*.

**One root for the whole night, drifting down.** Voices are drawn from a fixed
consonant interval set — unison, octave, fifth, fourth, and a couple of gentler
thirds and seconds — above a single root chosen from the seed at press-start.
No chord progressions and no key changes, because **a key change is an event,
and events wake you up**. The no-narrative rule that governs the speech applies
just as hard to harmony.

What the root does instead is descend, very slightly, across the whole night —
on the order of a semitone over eight hours. Imperceptible minute to minute,
unmistakable if 23:00 were compared with 05:00. This is also the tape aesthetic
told honestly: tape machines slow as they age, and the descent is the same
gesture the disintegration engine already makes in the frequency domain.

**Both generators are deliberately dirty.** Additive drones — a handful of sine
partials per voice with slow independent detuning and amplitude drift — and
bandpass-filtered pink noise at pitched centres, which buys breathy, bowed,
almost-choral texture with no samples and a very forgiving failure mode.
Neither is meant to sound like a clean synth pad, because a clean pad does not
belong to this family. They are meant to sound like something that was
*recorded* and has since eroded.

**Which is why the synthesis module's job is small.** It produces a buffer of
length *N* at pitch *P* with texture *T*, and hands it off. `apply_decay`,
`apply_reverb`, gain, channel mapping, the seam rule, and the existing sound bed
with its pink noise and binaural beats are all downstream and unchanged. The
erosion is applied to synthesized material exactly as it is applied to a
separated stem today, which is what keeps Phase 1 recognisably the same
instrument rather than a different one wearing its name.

Concurrency and spacing are the night arc's business and not the palette's:
three or four voices sounding near bedtime, nought or one with long silences
between them by the small hours.

## The speech layer

**Intelligibility is a dial, and the night arc turns it down.** This is the
frame underneath both source kinds, and it is the one thing that must not go
wrong — **intelligible speech at 3 AM is the failure mode of the entire
project.** Nearly-followable at 22:30; an unintelligible murmur by 2 AM. Every
treatment below is really a control on that quantity, and it is a governed
output of the arc rather than a per-source setting.

**Radio sources gate themselves, and that is the best thing about them.** HF
and scanner audio is *already* intermittent — transmissions separated by
silence and static. So rather than simulating sparseness with a timer, the layer
runs a squelch-like energy detector on the live feed: real transmissions pass
through at a level the night arc sets, and the inter-transmission static passes
underneath at a much lower one. Real timing, real unpredictability, and the
static the operator specifically identified as doing work — none of it
invented. Treatment on top is band-limiting to roughly telephone bandwidth, a
little reverb, and slow level drift where the ionosphere does not supply enough
of its own.

**Room sources are continuous, not gated, and that is the point.** You do not
hear the TV in the next room intermittently — you hear it constantly and
quietly. So a comfort show gets no gate at all: lowpass somewhere around
700–900 Hz with a gentle slope, a little room reverb, level well down, running
underneath. Two placement models for two psychological mechanisms, which is the
right outcome given they were opposites to begin with.

**Both sit behind one `SpeechSource` interface.** `read(duration) ->
AudioBuffer`, implemented by `RadioSource` and `RoomSource`. This is the seam a
hosted version would need in order to ship radio only, or licensed audio only,
without touching anything else — and it is why the *Cheers* case, which has no
legal feed and never will, is safe as a local capability and unsafe as a hosted
one. The interface is the whole of the answer to that.

**Room sources are in Phase 1 alongside live radio.** The operator's "let's
just do live for now" is read as answering live-versus-harvested, not as
excluding *Cheers*, which arrived in the same message with evident enthusiasm.
The argument for including both is risk: a room source is a local file, a
filter and a gain — no websocket, no receiver etiquette, no network at 3 AM — so
it makes the speech layer provable and the aesthetic auditionable before the
live path exists. If KiwiSDR turns out flaky, there is still a speech layer.

**Receiver etiquette is part of the design, not an afterthought.** One
connection at a time; a cap on how long any single receiver is held; rotation
across receivers through the night; reconnect on drop; back off to a different
box on repeated failure. These are volunteers' BeagleBones with eight slots, and
an eight-hour connection to one of them is impolite in a way that would
eventually get the project blocked — which is a technical risk as well as a
social one.

## Steering: one input, one parameter, monotone, bounded

Everything is fetched or computed once at press-start and held immutable for
the night as a small `NightContext` of scalars. Sunrise, sunset and moon phase
are arithmetic from coordinates. Weather is one call to Open-Meteo, which needs
no key and no attribution, so there is nothing to manage for a personal tool.

The discipline is one input, one parameter, monotone, bounded:

| Input | Parameter | Direction |
|---|---|---|
| Time until sunrise | The night's length | Clamped to roughly 6–10 h |
| Cloud and rain | The noise bed's level and character | Wetter → more bed, softer |
| Wind | Depth of the drones' slow amplitude drift | Windier → breathes more |
| Pressure and its trend | The brightness ceiling | Lower/falling → darker |
| Moon phase | Width of the interval set | Full → more open; new → nearer unison |
| Season (day length) | Brightness ceiling and night length | Deeper winter → darker and longer |

A wet night sounds wet. A windy night breathes. That legibility is deliberate:
each mapping is one scalar to one parameter, monotone and small, so it can be
explained in a sentence and heard as a difference rather than experienced as
randomness. Pressure is folk meteorology and is included anyway, because it is
monotone and harmless. Moon phase is the narrative input, and giving it one
small honest job is better than pretending it does more.

**The whole steering space has to be safe.** Not usually good — good at *every
point*. Steering varies character, never quality, and every range is bounded so
that no combination of weather, moon and season can produce a night that is
bright, dense or alarming. That constraint is what stops this from being a
random number generator with a weather-shaped excuse, and it is a testable
property rather than an intention: sweep the steering space, assert the arc's
ceilings hold everywhere.

## The runtime

### Blocks, and how a voice survives one

The obvious problem with block rendering is that voices last minutes and blocks
last seconds, so every voice spans block boundaries. The existing
`render_arrangement` cannot help: it renders a whole placement into a buffer
sized from a target, and it already reads `loop.n_frames` rather than
`Placement.n_frames` (a known divergence recorded in
`docs/project-state.md`).

Rather than teach the decay engine to render partial placements — a change to
the contract at the heart of this codebase — **a voice is rendered once in full
the moment it is born, held in a small cache, and sliced.** The block assembler
takes whatever falls inside the block it is building. Voices are minutes long
and there are three or four at a time, so the cache is a few tens of megabytes
and `apply_decay`'s contract is untouched.

Blocks can then be short — around ten seconds, with three queued, giving half a
minute of buffer. The headroom is comfortable: the measurements already in
`docs/architecture.md` put `apply_decay` at 23–24 ms and `apply_reverb` at
9–34 ms on a 6.4-second stereo loop, so a minute-long voice costs a fraction of
a second to produce and a night needs a handful per minute. Rendering is not
going to be the thing that breaks.

The arc is evaluated once per block, which is fine for a `NightContext` held
constant all night and too slow for a microphone. That is a feature rather than
a limitation: when the mic arrives in Phase 2 it lands as a **playback-time gain
and EQ trim** rather than a render-time input, which is both faster and half of
the escape from the feedback loop, because a trim applied at playback is a
number you know you added.

### The speech layer is mixed at playback, not baked into blocks

Blocks are rendered ahead of playback and speech is live, and those two facts
are in direct conflict. A block rendered half a minute early would carry a
transmission that was audible half a minute ago — which is perceptually
harmless, since nobody knows what the "correct" moment for a scanner
transmission is — but it would also destroy the invariant this whole
architecture rests on, because a block rendered in isolation could no longer be
bit-identical to a sequential render of the same moment. The determinism is
worth more than the convenience.

So the stream splits in two:

- **The music layer is deterministic and rendered ahead.** Voices, decay,
  reverb, sound bed. Reproducible from `(seed, context, t)` alone, block
  independent, and covered by the invariant.
- **The speech layer is live and summed at the output.** The player holds the
  `SpeechSource`, applies the squelch gate and distance treatment, and mixes it
  into each block as that block is handed to the device.

This costs nothing and buys three things. The invariant survives intact and
stays testable. A speech source that stalls or dies affects only the moment it
dies in, rather than poisoning three already-rendered blocks that will play
anyway. And it puts the live layer in the same place as the Phase 2 microphone
trim, so the player owns exactly the two things that cannot be known in
advance — which is a boundary worth having drawn on purpose rather than
discovered.

The player therefore reads the clock too: the intelligibility ceiling and the
speech level are evaluated at mix time, from the same `arc(t)` the renderer
uses, so the two layers descend together.

### Playback

A Python process owns audio output via `sounddevice`, and Phase 1's one button
is a CLI command: `sleepmix night`, no options.

Three reasons for a process rather than a browser. No tab has to survive eight
hours. No mobile audio-suspension risk. And — the one that pays off later —
when the microphone arrives, capture lives in the same process as output, so the
audio never leaves the machine *and* the exact signal just played is available
to subtract.

The server and Elm shell already exist and adding a button to them later is
cheap. Building it now would be the only part of Phase 1 that is not
load-bearing.

## Failure: nothing that goes wrong at night may make a sound

This is a sleep tool, so failure at 3 AM is the only failure mode that really
counts. The rule is absolute: **degrade silently, never stop, never announce.**

- **Weather unreachable** → neutral defaults, start anyway. Never block the one
  button on a network call.
- **Receiver drops** → rotate to another; on repeated failure, drop the speech
  layer entirely and continue with music alone. No retry noise, and no silent
  gap where a voice used to be that reads as the program having died.
- **Render worker falls behind** → the block queue drains into a bed the
  *player* generates, not the renderer's. Pink noise at the arc's current level
  costs nothing and needs no plan, so it is available precisely when the thing
  that would have supplied a bed is the thing that failed. A quiet bed is an
  acceptable degradation; a buffer-underrun click is not, and a click is exactly
  the thing that wakes someone.
- **A voice raises** → skip it, log it, continue. One bad voice is a few
  seconds of slightly thinner texture, which nobody will notice, and is not a
  reason to stop a night.

The general shape: every error path ends in *less sound*, never in *different
sound* and never in *no stream*.

## Where it lives

A new `sleepmix/night/` package inside this repository, so it can reuse
`audio.py`, `effects.py`, `disintegration.py`, `util.iteration_rng` and the
progress contract without duplicating any of them.

**Dependency direction runs one way**, matching the house rule that `config.py`
must never import `arrangement`: **`night/` may import from `sleepmix/`, never
the reverse.** Nothing in the existing pipeline learns that this exists, so
nothing about the batch renderer, the server, or the mixer can be broken by work
in here.

- `night/clock.py` — the two nested clocks; night length from sunrise; `arc(t)`
  returning density, brightness, level and the intelligibility ceiling.
- `night/context.py` — `NightContext`, the dusk-fetched scalars, the weather
  client, and the sunrise/moon arithmetic.
- `night/plan.py` — the unbounded lazy planner: clock plus context plus seed,
  yielding `Voice` records.
- `night/palette.py` — the two generators.
- `night/speech.py` — the `SpeechSource` interface, `RadioSource`, `RoomSource`,
  the squelch gate, and the two distance treatments. Owned by the player, not
  by the renderer.
- `night/stream.py` — block assembly for the deterministic layer only: the
  voice cache, slicing, summing, and the sound bed. Nothing live reaches here.
- `night/player.py` — output, the block queue, the live speech mix, and the
  degradation behaviour above.

**`plan.py` may not import anything that generates or decodes audio.** This is
the same rule that makes `arrangement.py` testable against invented numbers in
milliseconds, and it is what lets an eight-hour night be planned and asserted in
a unit test that runs in microseconds.

## Testing

**Block independence, numerically.** Block *N* of the music layer, rendered in
isolation, is bit-identical to blocks 0..*N* rendered in sequence and sliced.
Same shape as `test_defaults_reproduce_todays_positions`: a property the whole
architecture rests on, asserted rather than argued. It is testable at all only
because the live speech layer never enters `night/stream.py` — if a future
change routes a `SpeechSource` into the renderer, this test is the thing that
will fail, and it should be read as the design breaking rather than the test
being wrong.

**The planner, against invented numbers.** Because `plan.py` touches no audio,
an eight-hour night is a unit test:

- The arc is monotone in all four governed quantities.
- No voice is ever born above the night's ceiling at its birth time.
- Intelligibility never rises.
- Density never rises.
- The plan is reproducible from `(seed, context)` alone.

**The steering space, swept.** Every combination of bounded steering inputs
produces an arc whose ceilings hold. This is the test that enforces "steering
varies character, never quality."

**Failure paths, driven deliberately.** A weather client that raises, a
`SpeechSource` that raises mid-night, a source that returns short, a render
worker made artificially slow. Each must produce less sound and a continuing
stream, and specifically must not produce a discontinuity.

**No database is involved anywhere in `night/`**, so the test-database
isolation rule does not apply. The existing autouse `isolated_data_dir` fixture
in `tests/conftest.py` covers anything that touches `paths.data_dir()`.

## Placeholders that will want tuning by ear

Recorded here and to be carried into `docs/project-state.md` on
implementation, so they are not later mistaken for considered values:

- **The night-length clamp bounds** (roughly 6–10 hours). Invented, not
  measured. Nobody has slept through this yet.
- **The neutral weather defaults** used when the API fails. They should read as
  an unremarkable night, and "unremarkable" is currently a guess.
- **The interval set** itself, and the semitone-per-night root descent rate.
  Both are the most taste-dependent numbers in the design and both are first
  drafts.

## How this decomposes

**Phase 1 — the synthesis night.** Nested clocks and the sunrise-derived night;
the palette; the existing decay, reverb and bed chain applied to synthesized
voices; the speech layer with both source kinds; weather, moon and season
steering; the block renderer, player and degradation rules; `sleepmix night`.
This is a complete, usable thing on its own — a stream that runs all night,
evolves, and carries voices.

**Phase 2 — the room closes the loop.** The microphone and adaptive masking,
landing as a playback-time trim, with whichever of the four escapes from the
feedback problem proves out. Spectral subtraction of the known output is the
favourite going in, because the output is available in the same process by
construction. This is where the stream starts responding to the actual room
rather than to a forecast of it.

**Phase 3 — source-derived early, synthesis late.** The operator's original
preference and the eventual goal: recognisable material near bedtime dissolving
toward pure synthesis by the small hours. This is where the existing pipeline
comes back — separation, loop detection, time-stretch — and where Plan 4b and
4c's multi-segment and multi-source work becomes directly useful, because each
source can have its own lifetime inside the night arc exactly as a synthesized
voice does.

**The seam Phase 3 needs, kept visible from Phase 1:** `night/plan.py` yields
`Voice` records that name a *source of material* rather than a generator. In
Phase 1 every source is one of the two synthesis textures. In Phase 3 some are
prepared loops from a real song, and the planner's job — deciding what is born
when, at what pitch, under what ceiling — does not change. If a `Voice` ever
grows a field that only makes sense for synthesis, that is the moment Phase 3
got harder, and it should be treated as a design error rather than a
convenience.

## What this deliberately does not do

- **No wake ramp and no alarm time.** There is no config to put one in, and a
  system that guesses when you are getting up and is wrong is worse than one
  that does not try. This arrives with the first button.
- **No web UI.** CLI only. The Elm shell exists and can grow a button later at
  low cost; doing it now adds the only non-load-bearing work in Phase 1.
- **No harvested-pool fallback for speech.** Live was chosen deliberately for
  the *someone is awake right now* property. The failure rules make the speech
  layer disposable instead, which is a different and cheaper answer to the same
  risk.
- **No hosted deployment, no streaming, no second listener.** The
  `SpeechSource` interface is the only concession made to that future, and it is
  free.
- **No learning from skips.** A system that converges on the operator's taste
  over weeks was considered and is genuinely interesting; it needs a feedback
  store and a bias model that do not exist, and it cannot be evaluated until
  there is a baseline to compare against.
- **No persistence beyond the seed.** No night history, no listening record, no
  statistics. The seed plus the date reproduces a night, which is the only
  reproducibility this needs.
- **No solar or geomagnetic input.** Rejected on the grounds above: a story
  input, not a perceptual one.
- **No visual anything.** No waveform, no arrangement view, no now-playing.
  There is nobody awake to look at it.
