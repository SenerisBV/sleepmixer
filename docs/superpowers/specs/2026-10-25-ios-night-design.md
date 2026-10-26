# Plan 6: the night in your pocket — an iPhone app, steered by how you sleep

**Status:** design approved by the operator 2026-10-26. Not
yet planned.

Plans 5.1 and 5.3 (`2026-08-18-night-stream-design.md`,
`2026-08-18-night-ghost-design.md`) built a night-long stream on the Mac: an
unbounded plan rendered a block ahead, synthesized drones, and real recordings
dissolving into drones made from their own spectrum. This plan moves the
*playing* half of that to an iPhone and gives it the steering input it has
never had: the sleeper's own body, sensed as movement by the phone lying on
the mattress.

## What this is for, in the operator's words and situation

The operator plays something every night to fall asleep. Right now it is Max
Richter's *Sleep* or a "choral chill" playlist. They used to use Endel and
stopped because they didn't want to pay for it. Each of those sets a bar, and
the three bars together define the brief:

- **Sleep is consistent and has gone stale.** It works every night, and
  after about ten years it is the same piece. The character has to stay as
  dependable as *Sleep* while the material changes.
- **Endel's variety was the thing they loved.** It changed night to night and
  had "a few different tracks", meaning distinct moods to pick from. This app
  has to vary just as much, and it should have the equivalent of those
  moods.
- **The choral playlist is inconsistent.** Some tracks suit sleep, and the
  next one jolts. That's the failure to design out: nothing sudden, whatever
  material went in.

What the operator pictures, unprompted: *picking some audio tracks — songs,
recordings, etc — that play but become warped and dissolve over time, like
thoughts when falling asleep.* That is close to exactly what the ghost phase
already does on the Mac, so the creative core of this app exists and has
tests. What doesn't exist is a way to have it at bedtime, on the device
that is actually next to the bed, reacting to the night as it happens.

The biometric idea came from the operator ("deep sleep creating more brown
noise or restlessness creating more echoey melodies"), and they explicitly
handed the sleep science to Claude: *"I'm not an expert on sleep, so I will
follow your lead on what kinds of sounds are best paired with what stages, as
long as it's dynamic and varies night-to-night."* The mappings below are
therefore Claude's call throughout. "Dynamic" and "varies night to night" are
the operator's hard requirements.

**Who it's for:** the operator, as a personal tool, the way Endel was. It also
sometimes plays for their two-year-old. The operator was explicit that this
needs **no child mode, no volume caps, and no special handling**: "Treat it
as for me, like endel, which it is." Don't add one.

## Goals

1. **A native iPhone app that plays the night stream**, composed live on the
   phone from prepared material. It doesn't play a pre-rendered file: every
   night is composed fresh, and no two are the same.
2. **Steered by movement**, sensed by the phone's own motion sensors while it
   lies on the mattress. No wearable, no extra hardware. (The operator
   considered Apple Watch, Oura, Polar, Whoop and Emfit and chose the phone
   alone: "I don't know most of those, so we should just use the iphone
   itself.")
3. **Preparing tracks is close to zero effort.** The operator named this as
   *the* friction ("the friction is really just about preparing the audio").
   Turning sound on at night is a habit, and getting new tracks in is where
   it would die.
4. **Choose or be surprised**: pick specific tracks or packages at bedtime,
   or press "Surprise me."
5. **Weekday mornings land gently** before the operator's own alarm.

## Non-goals (for this plan)

- **Preparing material on the phone.** The operator chose "chopping on the
  Mac and the phone just plays." Moving preparation onto the phone stays
  possible later. The kit format below is the boundary, and nothing on the
  playback side should assume where kits come from.
- **Apple Music.** It would be ideal, and the operator doesn't expect it.
  Catalog tracks are DRM-locked. Purchased or ripped tracks in the library may
  be readable later, which would be a future source of kit input, not this
  plan.
- **Being the alarm.** The operator's regular alarm stays exactly as it is.
  The app never sets, reads or replaces it. (Apps can't read Clock alarms
  anyway, which is why the wake time is entered in the app.)
- **The live speech layer** (HF radio and the room folder, `night/speech.py`).
  *Claude's call:* left out of the iPhone app for now. It needs a network all
  night, the operator didn't mention it, and their own description of the
  night is about their tracks dissolving. The Mac keeps it.
- **Wearables and the microphone.** See goal 2. The microphone also has its
  own unresolved feedback problem, recorded in `docs/project-state.md`.
- **App Store distribution.** It's a personal tool, installed via Xcode or
  TestFlight on the operator's paid developer account (see "Decisions from
  the builder check").

## Anti-goals: it fails if…

- **Anything at night makes a sudden sound.** That includes a crash, a
  Bluetooth dropout, a bad file, a steering decision, or a sudden movement
  from the sleeper. The night stream's existing rule, *nothing that goes
  wrong at night may make a sound*, carries over unchanged.
- **Restlessness makes it busier.** Steering may only ever make the stream
  *steadier* in response to movement (see "Steering by movement"). A stream
  that answers tossing and turning with new events is a feedback loop aimed
  at wakefulness.
- **Two nights sound the same,** or a night sounds like a playlist with
  seams in it.
- **Adding a track takes more than dropping a file.**
- **It's patronising.** No volume caps, child modes or warnings (see "Who
  it's for").

## Constraints

- **The phone can't run the Python engine.** numpy, scipy, pedalboard and
  Demucs don't exist on iOS. The playback engine is rewritten in Swift.
- **The Mac is usually on at home** (the operator confirmed this), so a
  background job on the Mac can do the preparing.
- **Audio goes out through a Bluetooth speaker or the phone's own speaker**
  (the operator uses both). With the phone speaker, the phone is also lying
  on the mattress it's sensing.
- **It must work with the wifi off** once kits are on the phone. Weather
  follows the existing rule: one fetch at Start, and neutral weather if that
  fails.
- **The existing invariants hold in the Python reference**: block
  independence, the plan importing no audio code, and the whole steering
  space being safe.

## How it works, end to end

### 1. Adding a track: the drop folder (Mac side)

There is a `Sleepmix` folder in iCloud Drive with an `Inbox` inside it. The
operator drops audio files into `Inbox`, either from Finder on the Mac or from
the Files app on the phone. Nothing else is required of them.

A background job on the Mac watches `Inbox`, runs the existing preparation
(`night/prepare.py`: separate, drop drums, find loops, stretch, extract the
pitch set) on anything new, and writes a **kit** into `Sleepmix/Kits/`. The
source file moves from `Inbox` to `Sleepmix/Originals/` when it's done, so
`Inbox` only ever holds work not yet done. A file that fails to prepare
(not audio, or too short) moves to `Sleepmix/Couldn't prepare/` with a
one-line reason next to it. It is never retried in a loop and never silently
dropped.

*Claude's calls:*
- The job runs as a launchd user agent, installed by a new CLI command (for
  example `sleepmix night install-watcher`) and removable by its counterpart.
  It prepares one file at a time, at low priority, since separation spins the
  fans. It only needs to be fast enough that something dropped in the
  afternoon is ready by bedtime.
- Delivery is through iCloud Drive (Apple to Apple, nothing to configure
  beyond being signed in, works offline once downloaded). AirDrop was
  considered and rejected because it's a manual step on every track.
- The Python code stays the one and only preparer. This plan adds a watcher
  and a kit *exporter*, not a second implementation of preparation.

### 2. The kit format: the boundary between the two halves

A kit is one folder per prepared source, self-contained, with **relative**
paths. Today's `SourceProfile` stores absolute Mac paths, which mean nothing
on a phone. Proposed shape:

```
Kits/<source_id>/
  kit.json        # format version, source_id, display title, sr,
                  # loops: [{file, frames}], pitch_set, prepared_at
  loop-0.wav
  loop-1.wav
  loop-2.wav
```

`kit.json` carries a **format version** from day one, because this is now a
contract between two codebases in two languages. The display title comes from
the file's tags if present, and otherwise from its filename. The loops stay
WAV: they are short (`LOOPS_PER_SOURCE = 3`, about two bars each), so size
doesn't matter, and decoding them is trivial in Swift.

The phone treats `Kits/` as read-only and works out everything else
(packages, history, settings) itself. Deleting a kit on the Mac removes it from
the phone's collection the next time the app looks. A kit that's referenced by
a package but has disappeared is skipped silently at bedtime and shown as
missing in the collection.

### 3. Bedtime: the collection screen (layout B, chosen by the operator)

The app opens on the operator's collection: **packages** and **single
tracks**, each with a tick box. There's a **"Surprise me"** switch at the top
and a **Start** button at the bottom showing how many tracks tonight will be
made from. The screen is dark throughout. Tracks still preparing on the Mac
appear greyed out with "preparing" and can't be ticked.

- **Packages** are named sets of tracks the operator makes in the app ("Rainy
  Sunday"). They're this app's version of Endel's moods. *Claude's
  interpretation of "packages", offered to the operator during design and not
  contradicted.* A track can be in any number of packages.
- **Surprise me** draws tonight's tracks from the whole collection. *Claude's
  call:* it picks between four and six tracks (a placeholder) and leans away
  from tracks used in the last few nights, so "surprise" actually surprises.
- **Selections are remembered:** the app opens with last night's choice
  ticked, so an ordinary night is one tap.
- After Start, the screen goes dark. Tapping it shows a minimal "Stop" and
  how long the night has left.

### 4. Through the night: what it sounds like (Claude's call)

The stream is the existing night stream, ported. Arc, voices, ghosts and
handovers all work as the ghost phase designed them. Tonight's chosen tracks
become `NightContext.sources`, so they're fixed at Start and never change
while someone sleeps, which is the same rule the Mac follows. Weather, moon,
season and the seed all still apply, so two nights from the same package
still differ.

**Steering by movement** is new, and it's the one live input. See its own
section below.

### 5. The end of the night

- **On a weekday with a wake time set**, the night's length is "until the wake
  time", replacing "until sunrise" (still clamped as `night_length_s` clamps
  today). The **morning lift** starts 25 minutes before the wake time (a
  placeholder): *if the sleeper is stirring*, the arc relaxes upward, getting
  a little brighter and fuller, never louder than the arc's own start and
  never sudden. If they're still, it holds dark and lets the alarm do its
  job. The idea is to avoid being in the deepest, stillest part of the night
  when the alarm goes off. This is the best-supported use of movement data
  there is, and it's modest.
- **On other days**, the night follows sunrise as it does now.
- **After the night's end**, the stream holds at its quietest and then fades to
  silence over a few minutes. *Claude's call:* about 30 minutes after the end
  (a placeholder), so a lie-in isn't interrupted by the stream stopping, but
  it also doesn't play all day.
- The wake time is set once in settings, with a time and the weekdays it
  applies to. It's in-app only, and the alarm itself is untouched.

## Steering by movement

### What the phone can sense

The phone on the mattress reads its accelerometer through CoreMotion while
the app plays audio in the background (the audio background mode keeps it
running all night). From that it derives two live signals:

- **Restlessness**, from 0 to 1: how much the sleeper has moved recently.
  This uses movement counts per 30-second epoch, the standard actigraphy
  approach, normalised against *this night's own* quiet baseline. Where the
  phone sits relative to the body changes every night, so absolute
  thresholds would be meaningless.
- **Awake**, a yes/no: sustained movement over several minutes, distinct from
  a single turn-over.

Hard parts the builder has to handle, named now:

- **The phone speaker on the mattress vibrates the phone.** Audio sits at
  tens to thousands of Hz, and body movement is below about 5 Hz. Lowpassing
  the accelerometer signal well below audio frequencies, and checking with
  the stream playing at bedtime volume on a real mattress, should separate
  them. That has to be measured, not assumed.
- **The phone isn't on the bed** (on the nightstand, or knocked onto the
  floor). A signal with no micro-movement at all for a long stretch reads as
  "no information". Steering then returns smoothly to neutral, and the night
  plays exactly as it would with no steering.
- **Picking the phone up** to stop the night or check the time is a huge
  spike. It must count as at most "awake", never anything worse, and it must
  never cause a sudden change in the sound (see below).

### What movement does to the sound

This applies the night stream's own rule: *one input, one parameter, monotone,
bounded, and the whole steering space safe*. It also carries over the
microphone discussion's key choice, *may make it quieter, never louder*,
which here becomes **movement may only make the stream steadier, never
busier.**

| State | What the stream does | Why |
|---|---|---|
| **Still** (low restlessness) | Steering is neutral: the arc and plan run as designed, wandering, ghosting and handing over. | Stillness correlates with deeper sleep, when people are hardest to wake. The night can afford its variety here, which is where "dynamic" lives. |
| **Restless** (rising restlessness) | Fewer new voices are born, the noise bed rises a little, and the brightness ceiling lowers a little. Restlessness gates *births*: it never cuts off a voice already sounding, and it never adds anything. | Light sleep is fragile. A new event during a turn-over is most likely to tip someone into waking. Steadier sound masks better and asks for less attention. |
| **Awake** (sustained movement) | "Fall back asleep" mode: births nearly stop, the bed rises to a steady cover, the brightness ceiling drops to near the night's floor, and whatever is already sounding is allowed to finish. It holds for a while after movement settles, then lets the night resume. | Lying awake at 3 AM is when the stream is most useful. The sound should be the least interesting thing in the room. |
| **Stirring near the wake time** | The morning lift (see above). | Surface gently instead of being yanked up by the alarm. |

**The morning lift, made precise (Claude's call, settled after the builder
check).** The lift is a **mix-stage change only**: the brightness ceiling and
bed level relax upward. It **never adds voices.** Births stay under the arc's
density, so movement still never makes the stream busier, even in the
morning. The lift is bounded by the arc itself: at most, the ceilings return
to their value **one hour into the night**, not to the bedtime ceiling (0 dB,
6 kHz), which would be nearly no bound at all. `clock.py`'s "ceilings that
descend" rule then holds in the sense that matters: the lift only ever
revisits a level the night already passed through. Inside the lift window,
**the lift overrides "awake"**. Someone moving 20 minutes before their alarm
is surfacing, not lying awake at 3 AM, and dragging them back down then is
the wrong job. The swept-steering test asserts the lift's bound across the
whole window.

**Other steering rules settled after the builder check (Claude's calls):**
- Restlessness never suppresses a voice that covers a handover
  (`HANDOVER_COVER_S`). A ghost's hand-off is exactly the continuity that
  keeps the night from having seams.
- A gated birth is decided by the trace value at that voice's *birth* block,
  so re-planning the same window in a later block (the planner re-walks from
  voice 0) gives the same answer.
- `source_id` must stay stable when a file moves from `Inbox` to
  `Originals`. It's derived from content, not path, for kits.
- The phone keeps a local copy of every kit it has seen, so iCloud offloading
  a file can never leave a night without its material.
- Location for weather and sunrise comes from the phone, asked for once,
  with the existing neutral fallback if it's refused.

Every parameter moves **slowly**: changes are smoothed over minutes, not
seconds, and the "awake" mode eases in and out. A sudden change in response to
a sudden movement is itself a sudden sound.

Restlessness only ever lowers density, brightness and the start of new
material, and it may raise the bed's level only within a fixed, small bound.
So the swept-steering test generalises directly: sweep weather × moon ×
season × restlessness × awake, and assert the arc's ceilings hold everywhere.
The phone signal is one more bounded scalar in a table that is already safe by
construction.

### How a live input fits a deterministic plan

The night plan is deterministic and block-independent: any block can be
rendered from `(NightContext, block index)` alone. A live input breaks that
unless it's handled deliberately. The design is:

- **Movement becomes a recorded trace,** the smoothed steering state sampled
  once per block. The plan reads the trace only up to the time it's planning
  for. Given the same `NightContext` and the same trace, the night is
  reproducible, and the block-independence property becomes "independent
  given the trace". That is the same kind of exception live speech already
  has, but narrower, because the trace is saved.
- **Gating must not shift the RNG.** The plan already has this discipline
  ("every draw a step might need happens unconditionally, before any branch").
  A birth suppressed by restlessness still consumes its draws, so a restless
  ten minutes doesn't reshuffle the rest of the night. That keeps "the night
  you would have had" well defined, which matters for the replay below.
- **About 30 seconds of lag is fine.** Blocks are rendered about half a minute
  ahead (`BLOCK_S = 10`, three queued). Sleep states change over minutes, and
  the steering is deliberately slower still. *Claude's call:* bed level and
  brightness may be applied at the mix stage, after the block is rendered (the
  way speech intelligibility is today), for faster response. Births are
  planned with the slight lag.

### The night log, and replaying it

Every night writes a small log to `Sleepmix/Nights/` in iCloud Drive: the
`NightContext` (seed, weather, moon, sources), the movement trace, and the
steering state per block. Two reasons:

1. **Tuning.** None of the steering numbers have been heard by anyone asleep.
   A log is the only way to find out the next morning what the stream did
   while you were out.
2. **Replay on the Mac.** The Python reference can render a logged night
   offline, or render the same night with different steering numbers. This
   is how the mappings get tuned without sleeping through each candidate.

## The two codebases

### Python remains the reference

**The steering is designed and tested in Python first, then ported.** It's the
cheapest place to get it right. Recorded or invented movement traces make
unit-testable inputs, the existing test suite (663 tests) already pins down
what a correct night is, and the plan-without-audio rule means a whole steered
night can be planned and asserted in microseconds. Concretely, this plan adds
to the Python side:

- movement trace and steering state types (with no audio imports, under the
  same AST guard as `plan.py`)
- restlessness and awake gating in the planner, using the
  unconditional-draws rule
- the morning lift and wake-time night length in the arc
- the swept-steering test extended to the new axes
- kit export, the Inbox watcher and its launchd install/uninstall commands
- replay of a night log

### Swift is a port, checked against the reference

The iPhone app (Swift, SwiftUI, AVAudioEngine) contains a port of the
planner, arc, palette, decay and block renderer, plus the iOS-only parts:
collection UI, motion sensing, iCloud kit reading, the night log, and audio
session handling.

**Parity is what makes the port trustworthy.** At the *plan* level it should
be exact: for a given `NightContext` and trace, the Swift planner emits the
same voices (birth frame, length, pitch, texture, gain, decay endpoints) as
Python. The Python side generates golden fixtures, and the Swift tests assert
against them. At the *audio* level exact parity isn't expected (different
DSP, different reverb), so it's checked by measurable properties: level
ceilings, brightness ceilings, no clicks at block seams, and finally by ear.

The randomness has to match for plan parity. Python uses numpy's
`default_rng([seed, sha256(key)[:8], iteration])` (`sleepmix/util.py`). The
builder chooses between porting numpy's SeedSequence and PCG64, plus the
specific draws used, faithfully into Swift, or replacing both sides' night
RNG with one simple, specified generator. The second changes every existing
night's sound, which is acceptable because nobody has slept through enough
of them to be attached to a specific one. It does require regenerating any
golden values in the Python tests.

### Audio session behaviour on the phone

- Background audio, mixing with nothing, and staying active when the screen
  locks.
- **The output route changes at night** (the Bluetooth speaker dies or goes
  out of range): fade to silence and stay silent. *Never* fall through to the
  phone speaker. *Claude's call*, from the "nothing that goes wrong may make a
  sound" rule. The night keeps time silently, so if the route comes back the
  stream can resume quietly at the right point in its arc.
- **Interruptions** (a call, Siri): standard iOS handling, then fade back in.
- **The phone runs out of kits partway through, or a loop fails to decode**:
  that voice is silent, and the synthesized voices carry on. The same
  degradation as the Mac's.

## Later: a bundled library (the operator's idea, deferred on purpose)

On approving this design, the operator said the friction of loading songs is
the part they're "not thrilled about". Endel ships its own library of sounds
for its collages, and this app could do the same by **coming preloaded with
kits**, so a first night needs nothing dropped into any folder. They called it
"not an immediate blocker — we can build as-is and see if we want to add that
later." So it's out of this plan's scope, and it's written down here so
nobody forgets it.

What this design already gives that idea for free, so it costs little later:

- **An empty collection is already a complete night.** With no sources, the
  planner falls back to Phase 1's synthesized drones and noise bands, which
  were listened to and work. The app should treat zero kits as a normal
  state, not an error, and that is the floor any library builds on.
- **A bundled kit is just a kit.** The kit format (section 2) is
  self-contained with relative paths, so a library is a set of kit folders in
  the app bundle, read by the same code as iCloud kits and marked read-only
  in the collection. They'd be prepared once on the Mac by the same Python
  preparer.
- **What it would need that this plan doesn't decide:** where the recordings
  come from (field recordings, public-domain or CC0 material, or the
  operator's own), and their licensing. The "Music you didn't make" section
  of the README already limits renders of others' music to private
  listening, and anything shipped inside the app has to be material that's
  clear to ship.

## Placeholders (to be tuned by ear, recorded in project-state when built)

Every one of these is invented, in the spirit of the existing placeholder
lists:

- Surprise-me track count (4–6) and its "recently used" lookback
- Morning-lift window (25 min) and how far it lifts
- Fade-out time after the night ends (30 min)
- Restlessness epoch (30 s), the baseline window, and the smoothing time
  constant
- Awake detection: how much movement for how long, and the hold time after
  it settles
- How much restlessness lowers density and brightness and raises the bed
- The accelerometer lowpass cutoff that rejects the speaker

## Left to the builder

- Minimum iOS version, project structure, and how Swift tests run
- How the Mac watcher detects new files (FSEvents or polling) and how it
  handles files that iCloud is still downloading
- The RNG choice above
- Reverb on iOS (AVAudioUnitReverb versus a port of the existing Schroeder
  fallback), judged by ear against the Mac
- Where packages and settings are stored on the phone
- The visual design of the collection screen beyond layout B and "dark"

## Order of work (suggested)

1. **Spike: motion overnight**, run alongside step 2 (see "Decisions from
   the builder check"). A throwaway iOS app that plays audio in the
   background and logs the accelerometer all night, with the phone on the
   mattress and the speaker playing. It answers whether background motion
   reads survive a whole night, how much speaker vibration leaks through,
   how much a second sleeper registers, and (for the record) the battery
   cost.
2. **Python: steering, kit export, watcher, night log replay**, with tests.
3. **Swift: the port**, plan parity first, then audio.
4. **The app: collection, Start, steering, morning, log.**
5. **Sleep on it.** It isn't done until the operator has slept a few nights
   with it and the placeholders have been heard.

## Decisions from the builder check (the operator's answers, 2026-10-25)

- **Distribution: a paid Apple Developer account.** The operator has one or
  will get one. So the app installs once and stays installed (no 7-day
  expiry), and it can use the **iCloud capability with its own container**.
  `Sleepmix/` is that container's Documents folder, visible in Finder and
  Files as an iCloud Drive folder. Install is via Xcode or TestFlight to the
  operator's own phone. No App Store.
- **Steering is a layer, not a prerequisite.** If the motion spike fails, the
  operator still wants the app without steering. It's tracks dissolving and
  a different night every time, an Endel replacement either way. So **the
  spike runs alongside the rest, not in front of it.** Kit export, the
  watcher and the Swift port don't wait on it. Steering is built so that
  "no steering" is a first-class state (the neutral trace), and the app is
  complete and useful in that state.
- **The bed is sometimes shared.** The phone can't tell whose movement it's
  feeling. So: (a) a per-night **"Don't steer tonight"** switch on the
  collection screen, remembered like the selection, which plays the night
  with the neutral trace; (b) the motion spike also measures how much a
  second sleeper's movement registers from the operator's side of the bed;
  (c) the night's own baseline normalisation is per night anyway, so a
  shared night doesn't poison the next solo one.
- **The phone is a recent iPhone, plugged in overnight.** Battery isn't a
  design constraint, and the spike doesn't need to pass a battery budget,
  only record it. Memory still matters: an app in the background gets far
  less than a Mac process, and the current renderer holds whole voices
  (about 53 MB on average, up to 87 MB, in a 256 MB cache, with a brief peak
  during decay of many times a voice's size). The builder should measure the
  port's peak against the iOS background limit early, during the Swift port,
  and restructure to chunked voices only if measurement says it's needed.

The suggested order of work becomes: **(1)** Python kit export and watcher,
plus the motion spike alongside; **(2)** Swift port and app without steering,
which is the first milestone: a usable app; **(3)** Python steering, then its
port; **(4)** sleep on it.
