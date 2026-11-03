# Plan 9: the radio dial — the first iPhone night

**Status:** design written 2026-11-03 from the operator's answers, builder-checked;
awaiting the operator's review. Not yet planned.

**Builds on** `2026-11-02-am-night-design.md` (Plan 7: the scenes, the AM
channel, the warping, the shape of the night) and
`2026-11-02-esoterica-design.md` (Plan 8: the recordings). **Replaces** Plan
7's "Bedtime: what the screen does" and its voice list, link pasting,
"Surprise me", wake-time settings and Stop button: the dial is the whole
interface. Everything else in Plan 7 stands unless this document says
otherwise.

## What this is, in the operator's words

The operator has listened to the Esoterica recordings and wants to hear them
the way they're meant to be heard: in bed, on the phone, drifting. "I'm eager
to test in the app."

The interface came first, on 2026-11-03:

> I think a radio dial might be the UI with a serrated wheel UX, and users
> scroll station to station with static between or mixed over when the
> needle is a little off. That might be the only UI.

And the night, in their answers while this was designed:

- "The slow drift is important - it's part of the central thesis of the
  app." It is in the first version, not deferred.
- "Turning the dial resets the drift. If they're turning they must've woken
  up."
- "We've made big files of the recordings but they should probably be
  segmented so they can drift appropriately – I think they should probably
  space out over time ... getting further apart."
- A segment is "something you can drift into and follow to some logical
  point, and it should divide the episode into chunks", "a minute to a
  couple of minutes"; "use the longest answer that satisfies that".
- "When it hits the end, it should wait for a while and then start again.
  Later a station will have multiple episodes that can play. Or, we might
  have an overnight DJ voice that takes some calls about that story, then
  plays something else, maybe a different station."
- "For the start of the night, you just turn the dial until something
  catches your interest or sounds satisfying and leave it playing."
- At the end: "nothing new plays at the end, you just turn it off."
- "If 'off' is part of the dial then perhaps you have to turn it to make it
  go 'on' at the start."

The feeling to protect: an old radio on the nightstand. You turn it on,
wander the band until something catches, and let it carry you. Nothing to
set up, nothing to decide, nothing to look at once it's going. The night
then does what Plan 7 promised: everything slowly recedes, the way a memory
softens the further you get from it.

## Goals

1. An iPhone app whose only control is a radio dial with a serrated
   thumb-wheel and a needle.
2. Three stations on the dial: **The Lantern Accords**, **the language
   lesson** (Backward Lesson One; *Claude's reading of "the language one":
   it is the voiced lesson the operator liked; Mubba Lesson One is not
   voiced*), and **The Orchard Light**.
3. Static between stations; a needle slightly off a station mixes that
   station with static, more static the further off.
4. "Off" is the end of the dial's travel: the radio starts off, turning the
   wheel out of "off" clicks it on, turning back clicks it off.
5. Each station is its recording, played **segment by segment**, over a bed
   made from the three scenes that exist (pixel waves, soft-mallet chimes,
   low warmth), all through the AM channel.
6. **The drift**, live on the phone: from the moment you stop turning, the
   night's warping deepens over the hours (Plan 7's distance, slowness,
   fragmentation, proportion, the channel's narrowing and fading), and the
   gaps between segments grow.
7. **Turning the wheel resets the drift.** Wherever the needle lands comes
   back clear and close; the drift starts again when you stop.
8. A recording that runs out waits a while, then starts again from the top,
   still deep in the drift.
9. Plays with the screen locked, all night, offline.

## Non-goals (for this plan)

- More scenes, more stations, more episodes per station. The library grows
  later; this plan has to make adding a station cheap (a recording plus its
  segment marks plus a bed recipe), not do it.
- The overnight DJ and call-in show. Only protected (see "Left open").
- Steering by movement (Plan 6/7's accelerometer). The dial is the only
  input this time.
- Wake times, the weekday morning lift, weather and sky, the night log,
  iCloud, and Plan 7's every-night ease toward morning (it needs a wake
  time; see "Settled after the builder check").
- Plan 7's memory layer (fragments of earlier in the night returning) is
  **not** required for the first version; see "Order of work". The drift
  in this plan is the scenes ageing, the segments spacing out, and distance.
- Link pasting, feeds, downloads. The recordings ship inside the app.
- Re-voicing anything. Segments are cut from the audio already paid for.

## Anti-goals: it fails if…

- **Anything is sudden.** A station change, a segment starting, a reset,
  the radio clicking on: all of them arrive softly. Plan 7's rule stands:
  nothing that goes wrong makes a sound, ceilings only descend (except a
  reset, which the operator caused by turning the wheel).
- **It needs looking at.** No labels to read in the dark beyond what the
  dial itself shows; no settings; no confirmations.
- **The static is harsh.** Static is a texture you could fall asleep to,
  warm AM hiss and soft crackle, not white noise or a scanner shriek.
- **Picking up the phone resets the night.** Only turning the wheel does.
  Unlocking, glancing, a notification: nothing changes.
- **It falls through to the phone speaker** when the Bluetooth speaker or
  headphones drop out (carried over from Plan 6).
- **A segment is cut mid-thought.** A segment ends where a thought ends.

## The dial

**What it looks like** is the builder's, within this: one screen, dark, an
old radio band with a needle, and a serrated wheel you drag with a thumb.
The three stations are marked on the band (*Claude's call: by their titles,
small, so you can find your way back to one*). There is no other screen.

**How it behaves:**

- **Off** is one end of the travel. The app opens with the needle at off
  and silence (*Claude's call: the radio is always off when you open it,
  even if you last left it on a station, because "turn it on" is the
  ritual; it then remembers where on the band you were last, so a short
  turn finds yesterday's station*). Turning out of off: a soft click, the
  sound fades in from nothing over a couple of seconds.
- **The band** after off: static, with the three stations spread across it
  (spacing and order are the builder's). Between stations, static. Near a
  station, that station fades up through the static; dead on it, the
  station alone. How wide a station is and how the blend runs are
  placeholders, tuned by ear.
- **Feel:** the wheel has detents (a light haptic tick, like a serrated
  edge) and a gentle pull toward a station when you're near one, so a
  sleepy thumb can land on it. *Claude's call.*
- **Turning back to off:** a soft click and the sound fades out.
- **Lock screen:** the sound keeps going. The phone's own lock-screen
  controls (*Claude's call*) offer only pause and play; pause fades out,
  play fades back in without resetting the drift.

## The night: the drift

Plan 7's "The shape across the night" and "What may ease and what may only
descend" apply, with one change: **the night's clock is "time since the
wheel last stopped"**, not "time since Start". Turning the wheel resets it.
*Claude's call:* a reset that comes within a minute of the last one (you're
browsing) doesn't count as waking; the drift simply starts when you settle.

- **Settled for the first 20–40 minutes:** the station plays nearly as
  recorded, segments close together, the bed light, the channel present
  but not narrow.
- **Then** the warping deepens on Plan 7's 90-minute cycle over a deepening
  trend; the voice passes through Plan 7's five stages (clear, on the
  radio, next room, fragments, the shape of a voice).
- **The reset** is the one sanctioned rise: clear and close again, faded
  up over a few seconds, never jumped.

**Static drifts too.** If the needle is left between stations, the static
is the station: it drifts like anything else (further away, softer,
narrower). *Claude's call.*

### Settled after the builder check (Claude's calls)

- **Two clocks.** The *drift clock* is time since the wheel last settled
  and drives everything in the drift. The *night clock* is time since the
  radio clicked on; nothing in this plan uses it except as a record. The
  drift curves are scaled to an 8-hour night; past 8 hours on the drift
  clock the drift holds at its late-night shape (the cycle keeps moving).
  **No ease toward morning in this plan** (it needs a wake time, which is a
  non-goal): the radio plays until it is turned off, as the operator said.
- **What a reset restores:** full bedtime values. Drift clock to zero,
  voice stage 1, the brightness ceiling reopened, segment gaps back to
  their early length. It arrives as a fade over a few seconds.
- **What counts as a turn:** the operator's finger moving the wheel past a
  small threshold (a few degrees). The wheel's own settling (the pull
  toward a station, detent animation) never counts. The browsing window is
  measured from the last touch: the drift clock starts when the wheel has
  been untouched for a minute, and turns within that minute are one
  reset.
- **Pause** (lock screen) fades out and back in and does not stop the drift
  clock.
- **Voice stages in this plan:** a segment always plays whole; the voice is
  never chopped inside a segment (a segment is a thought you can follow).
  The deep stages come from distance, the channel's narrowing and fading,
  quieter level, and the growing gaps. "The shape of a voice" is the far
  end of distance: heavily lowpassed, far behind the bed, words lost.
  Fragmentation, slowness and proportion act on the bed, not on segments.
  No varispeed or time-stretch on the voice.
- **The takes are final.** Lantern Accords and Northern Tide were re-voiced
  for the last time on 2026-11-03; Backward Lesson and Orchard Light were
  "great as-is". If a thought boundary has no usable pause, the mark moves
  to the nearest pause; a segment is never cut in a word and never
  crossfaded mid-speech.
- **Stations keep broadcasting (the operator's answer, 2026-11-03):** "When
  you tune away, it keeps broadcasting." Every station's schedule (its
  segments, gaps and end-of-recording waits) runs from the moment the radio
  clicks on, whether you're tuned to it or not, like a real radio. Tuning
  in, you land wherever it is: mid-segment, or in a gap with only the bed.
  That is in medias res and is fine, because a station always arrives
  through static, faded up, never cut in. *Claude's call for the start:*
  each station starts at a random point in its first pass when the radio
  clicks on, so turning it on doesn't always land you at the opening.
  Whether a station off the needle is actually rendered or only its
  schedule advances is the builder's, as long as tuning in sounds
  continuous after the fade.

## A station

A station = **a recording** (its segments) + **a bed** (a recipe over the
three scenes) + the shared **channel**.

### Segments

A segment is the longest stretch of a recording that you can drift into and
follow to a logical stopping point: one thought, one story beat, about one
to two minutes (the operator's rule). Segments divide the whole recording;
there is nothing between them.

- **Where they're marked:** in the script, with a new marker (the builder
  names it, e.g. `[segment]`), placed by Claude at thought boundaries and
  open to the operator to move. A passage boundary is always also a segment
  boundary.
- **The marker must not make the existing takes stale.** Takes are matched
  to their text by a hash; the marker is stripped before hashing and before
  anything is sent to a provider, like the other structural markers.
- **No re-voicing, no credits.** The audio for each segment is cut from the
  existing raw takes, at the pause that falls at the marker. How the cut
  point is found (silence detection guided by the text's position, or local
  speech alignment) is the builder's, with this test: every cut lands in a
  pause, never in a word, and a listening check of every cut by the
  operator is part of the milestone.
- Each segment is rendered with its recording's source character (room,
  hum…) and shipped as its own file, clean of the AM channel (the phone
  adds the channel live).

### Spacing over the night

- Early, segments follow each other with a short natural gap, like the
  recording.
- As the drift deepens, the gap after each segment grows, filled only by
  the bed; late in the night a segment surfaces now and then. The gap's
  growth follows the drift's depth (so it eases a little on the cycle). Gap lengths are placeholders.
- The segment itself gets the voice treatment for the current stage.

### The end of a recording

After the last segment, the station waits (a placeholder, long, longer
later in the night) and starts again from the first segment. A reset by
the wheel doesn't restart the recording; the broadcast carries on and only
the drift resets (so the gaps ahead shorten again).

### The bed

Each station has its own recipe over waves, chimes and warmth (levels, which
scenes, their dials). *Claude's call, from the operator's handing over of
the sleep-stage mapping:* the Lantern Accords sits on warmth (a stone hall,
lamplight), the Orchard Light on chimes, the lesson on waves; each with a
little of the others. Tuned by ear, recorded as placeholders.

## How it gets made

- **One Swift package (`NightEngine`), shared by the Mac tool and the
  app**, as Plan 7 set. The app is a new iOS target. SwiftUI for the dial.
- **A real-time engine.** Today the factory renders offline. The app needs
  the scenes, the warping and the channel running live on the audio thread:
  no allocation, no locks, no unbounded work per buffer. The known
  real-time hazards in `project-state.md` ("For the iPhone (real-time
  safety)") are this plan's work: chimes' per-strike allocation, waves'
  per-wave filters, cold seeks.
- **The planner.** Plan 7's planner, built now, with the dial's clock: it
  owns the drift curves, the segment schedule and the reset, and has no
  audio imports (Plan 7's rule). It must be testable by jumping to any
  minute and by simulating a turn of the wheel at any minute.
- **The Mac tool** (`nightctl`) can play or render a station's night from
  any minute and simulate wheel turns, so a night can be heard without the
  phone.
- **Audio session** (Plan 6, carried over): background audio, mixes with
  nothing, active with the screen locked; on route loss fade to silence and
  never fall through to the speaker; interruptions fade back in.
- **Level matching** (Plan 7): every segment is played at a common target
  loudness; the three stations sit at the same level as each other and as
  the static.
- **Memory on the phone matters** (Plan 7): measure the engine's peak
  against the iOS background limit early.
- **Device and account:** the operator's recent iPhone, plugged in; a paid
  developer account (Plan 6's builder check). Installing to the phone is
  something the operator does from Xcode; the plan must say exactly how.

## Left open (protected, not designed)

- **More episodes per station:** a station's recording becomes a list; at
  the end of one, the next plays after the wait.
- **The overnight DJ / call-in show:** a source that can talk about what
  just played and then hand over to another recording or another station.
  The station's "what plays next" decision lives in one place in the
  planner so that it can later be handed to a DJ.
- **Schedules** (the operator, 2026-11-03: "Later we should add schedules
  so that tuning can start a station in medias res"): a station's
  programme laid out in time, so that what's on at a given moment is
  decided by the schedule. The broadcast model above is the ground for it:
  the planner already answers "what is this station playing at minute N".
- **A growing scene library:** a bed is a recipe over named scenes, so a
  new scene is a new name, not a new kind of station.

## Placeholders (to be tuned by ear, recorded in project-state when built)

- Station width on the band; the blend curve from static to station; the
  pull toward a station
- Static's level and texture
- Fade times: on, off, reset, pause/play
- The "browsing" window for resets (about a minute)
- Segment gaps: early, and growth with drift depth
- The wait at the end of a recording, early and late
- Each station's bed recipe
- All of Plan 7's drift placeholders (cycle, trend, stage timings, warp
  ranges, channel)

## Left to the builder

- The dial's visual design, within "The dial"
- The segment marker's name and the cut-finding method
- Station order and spacing on the band
- Package and target layout (subject to the planner having no DSP
  dependency), minimum iOS version, how the app's tests run
- How the recordings are bundled (format, compression), within the phone's
  memory and the app's size
- Whether the bed's scenes are generated live or partly pre-rendered, as
  long as they still age with the drift and the result is not an audio
  track on a loop

## Order of work (suggested)

Each milestone is something the operator can hear.

1. **Segments.** The marker, Claude's marks in the three scripts, the cuts,
   per-segment renders. The operator listens to the cuts.
2. **A station's night on the Mac.** The planner with the dial's clock, the
   segment schedule and spacing, the bed, the drift; `nightctl` renders a
   station's night from any minute and simulates a turn.
3. **Real time.** The engine runs live (Mac first), with the real-time
   hazards fixed and memory measured.
4. **The dial on the phone.** The app, the three stations, static, off/on,
   the reset, background audio and route rules. **First night in bed.**
5. **Sleep on it.** Tune the placeholders by ear over a few nights.

Plan 7's memory layer (fragments of earlier in the night returning) comes
after milestone 5, once the operator has heard a night without it.
