# Plan 7: the AM night — scenes that become their own memory, and a voice to fall asleep to

**Status:** design approved by the operator 2026-11-02 ("Yes this all sounds great"). Not yet planned.

**Supersedes** most of `2026-10-25-ios-night-design.md` (Plan 6) and all of
`../plans/2026-10-26-ios-night-6a-kits-and-inbox.md` (Plan 6a). What carries
over from Plan 6 is listed by name in "What carries over from Plan 6" below;
anything not listed there is dead. Plan 6 was approved and planned but nothing
of it was built, so nothing is being torn out.

## What this is, and why it changed

The operator came back to the project "clearer about what this app should
do." Their words, which are the brief:

> Endel isn't really songs, it's soundscapes. We should have a library of
> components for soundscapes … and then we should warp them throughout the
> night in patterns to help the user sleep. … I'm not sure I've seen warping
> elsewhere, or at least, not how I'm thinking about it (sounds getting
> hollow, distant, slowed down, etc).

Every plan before this one was built on the operator's **songs**: separated
by Demucs, chopped into loops, dissolved into drones made of their own
spectrum. That's what made the iPhone design need a Mac in the background
preparing files, and it's where the operator kept feeling friction. This plan
drops songs as the material. The night is made from **generated scenes**, and
the operator's own contribution moves to **voices** (spoken word) that need no
preparation at all.

### The warping: a sound becoming its own descendant

Asked what happens to one sound between 11 PM and 3 AM, the operator said:

> It feels a little ghostly, like it's echoing in another room, recognizable
> but like a descendent of the original. It's slower, maybe breaking into
> pieces or only some segments are playing. I'm thinking about how dreams
> replay experience incompletely and with different proportions, and
> likewise, a warm memory the further you get from it.

This is the heart of the app and the part the operator believes is new.
Nothing is *replaced* through the night. What plays at 3 AM is *derived from*
what played at 11 PM, and still recognizable as its descendant, the way a
memory is still the same memory as it fades. Four movements, in their words
and in audio terms:

| Their words | In audio |
|---|---|
| echoing in another room | duller, more reverberant, less direct sound, as if through a wall or doorway |
| slower | stretched in time, slightly lower |
| breaking into pieces, only some segments playing | fragments drop out, gaps open, a scrap repeats |
| different proportions (dreams) | not uniform shrinking: one detail swells out of scale while the rest recedes |

Its purpose is the memory analogy: familiar enough that nothing new or
alarming arrives, distant enough that nothing pulls attention.

### The AM character

The operator wants generated sounds that "feel closer to AM radio" rather
than realistic nature recordings. Their examples of what they hear in it:

> rich round chimes, waves that feel pixellated, sleeping on a train, wind
> through a long vent, carolers, someone upstairs practicing an instrument

None of those is a radio sound. "AM" is the **channel** they all come through:
warm, narrow, slightly broken, made rather than recorded. When asked what
Claude would have expected from "AM sounds", Claude separated the channel
(band-limited, hiss, slow night-time fading, faint bleed of another station,
squashed and warm, mono) from the content (voices, music, commercials, thin
and low-fi). The operator confirmed both: the channel and the scene library
belong in this plan; AM *content* (commercials, station IDs and the like)
waits for the late-night DJ.

A note that shaped the design: real AM at night already *does* what the
warping does. After dark the signal bounces off the ionosphere, distant
stations come in, and they swell and sink. **The channel's fading is part of
the warping, not a filter on top of it.**

### The voice, and the late-night DJ it leads to

The operator's "number 1 sleep request":

> in movies, we used to see late night call in shows with strange, sleepy
> calls to a soothing overnight dj. If I could bring back anything it would
> be this.

They deferred designing that ("I'll need to think about how though so let's
start with the other stuff"). But when import complexity came up, the
operator proposed a route that serves both:

> assume it's spoken word — audiobooks, speeches, podcasts, etc — and let
> them enter urls that the app will download. This might be a way to address
> the late night dj aspect without trying to generate voices or needing to
> understand and pull apart songs.

So this plan has a **voice layer**: spoken word from links, which starts clear
and gradually changes (the operator: "the voices probably start clear and
gradually change") along the same descendant path as the scenes. The DJ show
is a later layer that sits in the same slot. Nothing here designs it, but
nothing here may make it harder (see "Left open for the DJ").

### Unpredictable, or it's just an audio track

On whether the app should pick the scenes: "Yes exactly, it shouldn't be
predictable or else it could just be an audio track." This is the operator's
standing rule, the same one Plan 6 recorded as "two nights sounding the same"
being a failure. The sleep-stage mapping is Claude's call throughout (the
operator handed it over in Plan 6 and it stands), on the condition that it's
dynamic and varies night to night.

## Goals

1. **An iPhone app** that plays a night made of generated AM scenes, warped
   across the night into their own descendants, with an optional spoken-word
   voice that drifts from clear to murmur. The operator: "this needs to be an
   iphone app for it to get used."
2. **A built-in scene library** (no imports) in the AM character, starting
   from the operator's six examples.
3. **The voice is the one bedtime choice.** Pick a podcast feed or link
   you've added, something from a curated starter list, or "Surprise me".
   The app picks the scenes and how they warp.
4. **Adding a voice is pasting a link.**
5. **Every night is different**, and different again under the same voice.
6. **Steered by movement, and gentle on weekday mornings**, as Plan 6
   designed (carried over).
7. **A Mac test tool** on the same engine, so sounds are tuned by ear in
   seconds without installing on the phone.

## Non-goals

- **Importing your own audio as scene material.** Songs, field recordings and
  "extract components from audio" are later possibilities (the operator:
  "perhaps later adding the ability to extract components from audio"). The
  operator: "We can always expand later."
- **YouTube, Spotify, Audible, or any login-gated feed.** Public podcast RSS
  feeds and direct audio-file URLs only. YouTube downloading is fragile and
  against its terms.
- **Choosing scenes at bedtime.** Possible later if the operator misses it;
  not now.
- **The late-night DJ / call-in show.** Deferred by the operator.
- **AM content beyond voices** (commercials, station IDs, music beds). Part
  of the DJ conversation.
- **Porting the Python engine.** It isn't ported. See "How it gets made".
- **App Store distribution.** Personal tool, paid developer account, Xcode or
  TestFlight (carried over from Plan 6).

## Anti-goals: it fails if…

- **Anything at night makes a sudden sound.** This is the project's oldest
  rule and it gets new enemies in this plan:
  - *AM crackle is a transient by nature.* Crackle and static are soft
    texture, always below the level at which a single tick reads as an
    event. No pops.
  - *Heterodyne whistles are famously irritating.* A whistle, if present at
    all, is very faint and early-night only.
  - *Tuning sweeps* (the dial moving) are a phrase, not a click. Early night
    only, slow, and never across a loud station.
  - *Podcasts insert ads* that are far louder than the host, and LibriVox
    readers vary wildly in level. A loud ad at 2 AM is a sudden sound. The
    voice layer **level-matches** everything it plays (see "Voices").
- **It sounds like a cheap synth.** "Generated" must read as *made and
  eroded*, the family the existing palette was written for ("not trying to
  sound like a synthesiser… like something that was recorded and has since
  eroded"), not a keyboard demo. A scene that can't clear this bar ships
  later rather than ships bad.
- **Restlessness makes it busier** (carried over).
- **Two nights sound the same**, or a night sounds like a playlist with
  seams.
- **A voice demands attention late at night.** Intelligibility only falls as
  the night deepens. Nothing turns the voice back up into clarity after it
  has left, except the morning lift (which is bounded, see below).
- **Adding a voice takes more than pasting a link.**
- **The night refuses to start.** No voice ready, no network, a broken feed:
  the night plays without a voice, silently degraded, never an error screen
  in place of sound.
- **It's patronising.** No volume caps, child modes or warnings. Level
  matching in the voice layer is *matching*, not a cap.

## How it gets made (Claude's call, offered to the operator and accepted)

The operator said the iPhone is the destination and left the route to Claude,
"only if it's mostly reusable." The route:

**One Swift engine, as a Swift package, used by two front ends:**

1. **`NightEngine`** (Swift package, platform-neutral, no UIKit/AppKit):
   scenes, the AM channel, the warping, the night planner and arc, voice
   treatment, the mixer. Everything that decides or makes sound.
2. **A Mac test tool** (command line is enough): renders an excerpt of a
   night to a WAV, or plays live, and can **jump to any time of night** ("what
   does 3 AM sound like tonight?"), or **audition one scene in isolation**,
   with or without the channel and at any warp depth. This is the tuning
   instrument.
3. **The iPhone app** (SwiftUI, AVAudioEngine): bedtime screen, background
   audio, downloads, motion sensing, the night log.

**The Python engine is a reference for rules, not code.** It stays in the
repo, working, untouched. What carries forward from it are its hard-won
invariants, which this design restates as its own:

- **Nothing that goes wrong at night may make a sound.** Every failure ends
  in less audio, never different audio, never a stop.
- **Ceilings only descend** (the arc), except the bounded morning lift.
- **No transients.** Everything fades in and out.
- **The plan imports no audio.** The planner is pure data and arithmetic, so
  an eight-hour night can be planned and asserted in microseconds. In Swift
  this means the planner lives in its own module (target) with no dependency
  on the DSP module, and that separation is what makes the engine testable
  other than by ear. **This replaces Plan 6's Python-golden-fixture parity
  as the testing story.**
- **A swept-steering test** asserts the ceilings hold over every combination
  of steering inputs.
- **Gating never shifts the randomness**: a suppressed event still consumes
  its random draws, so a restless ten minutes doesn't reshuffle the rest of
  the night.
- **The excerpt tool must build the engine exactly as the app does.** The
  Python project learned this the hard way: three listening artefacts were
  rendered from a configuration nobody could actually run (see
  `docs/project-state.md`, "Three listening artefacts…"). Concretely, the
  app and the Mac tool construct the night through the same single factory
  function, and the tool may only *override* named fields on top of it.

## The scenes

A **scene** is a generator with a recipe and a set of named **elements**,
the parts it's made of. Elements matter because "different proportions" acts
on them: the warping can swell one element and recede the rest. Every scene is
deterministic given a seed and a time, so any moment of a night can be
recomputed.

The starter library, from the operator's examples (the element lists are
Claude's suggestion; the builder may change them):

| Scene | Kind | Elements (suggested) | Difficulty |
|---|---|---|---|
| **Rich round chimes** | tones | strike, body partials, long bloom, beating between near partials | easy |
| **Tones / drones** | tones | fundamental, upper partials, slow beating | easy (Python palette has one) |
| **Pixellated waves** | rhythmic texture | swell, break, hiss of the wash, rendered at low resolution (bit depth and sample rate stepped down) so it reads as *remembered* surf | easy–medium |
| **Sleeping on a train** | rhythmic texture | rail clack pattern, low rumble, carriage sway, a far-off horn | medium |
| **Wind through a long vent** | rhythmic texture | breath of air, the tube's resonance (pitched), rattles | easy–medium |
| **Carolers** | distant people | voices on chords, a melody line, breath between phrases | **hard** |
| **Someone upstairs practicing** | distant people | a phrase, its mistakes and restarts, the pause, heard through the floor | **hard** |

**The two "distant people" scenes are a known risk.** Synthesized choir and
synthesized instrument practice are easy to make cheesy. The AM channel and
distance forgive a lot (nobody hears a caroler through a wall in detail), but
the builder should **phase them after the four easier scenes** and is free to
use small bundled, clearly licensed or self-made samples as raw material
inside a generator (for example single sung vowels resynthesised) if pure
synthesis can't clear the "cheap synth" anti-goal. The scene is still a
generator; it just isn't required to be built from oscillators alone.

**A night uses a few scenes, not all.** The planner picks tonight's scenes,
leaning away from recent nights, and lets them come and go across the night
under the arc. *Claude's call:* two to four scenes present at any one time
early, thinning to one or two late (placeholders).

## The AM channel

Everything (scenes and voice) passes through the channel. Its parts:

- **Narrow band:** no deep bass, no sparkle; roughly a small speaker's range.
  The corners narrow across the night (this is where the old arc's brightness
  ceiling lives now).
- **Hiss and crackle:** soft, continuous, below event level. Never pops.
- **Night fading:** slow swells and sinks of the signal, including the
  frequency-selective kind that makes the tone shift as it fades. *This is
  one of the warping's tools*, and it deepens across the night.
- **Bleed:** another station faintly underneath, early in the night, made
  from the night's own material (a fragment of a scene or voice) so it never
  introduces anything foreign.
- **Whistle and tuning sweeps:** optional, faint, early-night only.
- **Squash and warmth:** gentle compression and saturation. Mono.

The channel is applied per source before mixing, not once at the master, so
the voice and a scene can sound like they're on different stations or in
different rooms. *Claude's call.*

## The warping

### Two layers, both Claude's call

The operator's idea needs 3 AM to be *recognizably derived from* 11 PM. With
generated scenes there are two ways to get that, and they sound different, so
the design uses both:

1. **The scene ages.** A scene's own recipe drifts: its tempo slows, its
   elements re-weight (one swells, the rest recede), its pitch sinks a
   little, its texture coarsens. Generated sound is what makes this possible:
   slowing a generator isn't a time-stretch artefact, it's the thing itself
   played slower.
2. **The night remembers.** The engine keeps a record of what actually played
   earlier (the **memory**). Later in the night, fragments of it return:
   incomplete, slowed, out of proportion, from another room. That's the
   dream replay the operator described ("dreams replay experience
   incompletely and with different proportions"). A chime phrase heard
   clearly at 11:20 PM may come back at 3 AM as two notes of it, half speed,
   behind a wall.

Then both pass through **distance** (another room: lowpass, more reverb,
less direct sound, the channel's fading).

The warp has four depth controls the planner sets over time, matching the
operator's four movements: **distance**, **slowness**, **fragmentation**,
**proportion**. Each is 0 at "heard plainly" and rises.

### Memory without real-time history

The Mac tool must be able to jump straight to 3 AM, and the phone may need to
recover mid-night. So the memory can't be "whatever happened to be recorded
while playing." **The memory is recomputed, not recorded:** because scenes
are deterministic, a fragment of what played at 11:20 PM is re-synthesized
from the plan for 11:20 PM when it's needed. The planner decides *which*
earlier moments return and when; the renderer regenerates them and applies
the warp. Voice fragments work the same way: the voice file plus the offset
it was at is enough to fetch the fragment again. The movement trace is saved
(see "Steering"), so a steered night is reproducible from its context plus
its trace, as Plan 6 already established.

### The shape across the night (Claude's call)

The operator handed the sleep science to Claude. The shape:

- **First 20–40 minutes (falling asleep):** scenes plain-ish, voice clear,
  the channel present but light. Warping starts gently. This is the stretch
  where content can be followed if you want it.
- **Through the night:** warp depth follows a **cycle of about 90 minutes**
  (the length of a sleep cycle), deepening through the early part of each
  cycle and easing a little toward its end, on top of an overall trend that
  deepens across the night. The cycle length, phase and depth are drawn per
  night so no two nights align (placeholders).
- **Deepest stretches:** mostly memory, little that's new; the voice is the
  shape of a voice; the channel's fading is at its widest.
- **Toward morning:** the trend eases back somewhat, so waking feels like
  walking back into the room. Bounded: it never returns to the bedtime
  clarity. On weekdays with a wake time, the morning lift (carried over)
  governs the last stretch.

### What may ease and what may only descend (Claude's call, settled after the builder check)

The cycle and the morning both *ease* the warp, and the arc says ceilings
only descend. They don't conflict, because they act on different things:

- **Ratchets (only ever go one way):** overall level, the brightness
  ceiling (the channel's upper band corner), and the **voice stage**. These
  are the arc's ceilings. A voice that has reached "next room" never comes
  back to "on the radio", whatever the cycle does.
- **Free within their range:** slowness, fragmentation and proportion. The
  cycle moves these up and down freely; easing them makes the night less
  broken, not louder or brighter.
- **Distance is in between:** its reverb and directness may ease with the
  cycle, but its lowpass can never open above the current brightness
  ceiling. Easing distance can only bring a sound closer *inside* the room
  the arc already allows.
- **The every-night ease toward morning** is bounded like the lift: at
  most, the ratchets return to their **one-hour-in** values, never to
  bedtime. On weekdays with a wake time, the morning lift governs the last
  stretch instead, with the same bound. Neither moves the voice stage
  backwards except the weekday lift, which may bring the voice back at most
  to stage 2 ("on the radio").

The swept-steering test asserts: the ratchets never rise outside the
morning windows; inside them they never exceed their one-hour-in values;
distance's lowpass never exceeds the brightness ceiling; and all of this
holds across every combination of steering inputs.

## Voices

### Where voices come from

- **Podcast feeds** (public RSS): paste the feed's link once. The app
  fetches new episodes as they appear.
- **Direct file links** (an MP3/M4A URL): paste a link to one recording.
- **The links people actually copy** are resolved too (*Claude's call,
  settled after the builder check*, because "adding a voice is pasting a
  link" would otherwise fail on the most common case):
  - an **Apple Podcasts** page link (what the Podcasts app's share sheet
    gives, and how the operator would add Alan Watts) is turned into its
    feed through Apple's public podcast lookup;
  - an **Internet Archive** item page is turned into its audio files through
    archive.org's public metadata API.

  Anything else that isn't a feed or an audio file gets a plain "couldn't
  find audio at that link" and nothing is added.
- **The starter list:** a curated catalogue of links (feeds and files) that
  ships with the app. **The audio isn't bundled, only the links**, so the app
  stays small and nothing questionable sits inside it. Claude curates a
  starter version: LibriVox readings (public-domain books; LibriVox
  publishes per-book feeds), historic public-domain speeches and fireside
  chats, NASA mission audio, and old-time radio episodes from the Internet
  Archive, which suit the AM sound especially well. The builder must check
  each entry's status. The operator is in the Netherlands, and US public
  domain isn't EU public domain, so items whose status is murky are left out.
  (For a personal tool installed from Xcode this is low-stakes, but the list
  should still be clean.)
- **Classic audiobooks lead the starter list** (the operator's suggestion,
  after approval: "public domain audiobooks, perhaps of classics, might be
  good for starter seeding"). Rules for choosing them (*Claude's calls*):
  - **Author died more than 70 years ago**, so the text is public domain in
    the Netherlands as well as the US. Translations count separately: use
    old translations (for example George Long's 1862 *Meditations*), not
    modern ones.
  - **LibriVox recordings only**, which LibriVox dedicates to the public
    domain.
  - **Solo readers, not group recordings.** LibriVox's collaborative
    recordings change reader every chapter, and a new voice with a new level
    and accent is exactly the kind of jolt the night is built to avoid.
    Prefer well-regarded solo readers.
  - **Gentle and low-stakes.** Digressive, pastoral, reflective or comic
    books suit sleep. Thrillers, horror and cliffhangers don't. Suggested
    seeds (for the builder to verify and complete): *The Wind in the
    Willows*, *Walden*, *Three Men in a Boat*, *The Natural History of
    Selborne*, *The Voyage of the Beagle*, *Moby-Dick* (long and
    wonderfully digressive), *Pride and Prejudice*, *The Secret Garden*,
    *Anne of Green Gables*, *Meditations* (Long translation). Leave out
    *Dracula*, Poe and anything else written to keep you awake.
- **Alan Watts**, whom the operator named, is still under copyright and so
  isn't in the starter list. His official podcast is a public feed, so he's
  the obvious first link the operator adds.

### Getting it onto the phone before bed

The night must work with the wifi off (carried over). So:

- Downloads happen **when the voice is added, and in the background** before
  bedtime (feeds refresh in the background as iOS allows; the app also
  refreshes on open).
- The app keeps **a few hours ahead** per voice, downloaded, and prunes
  what's been played (placeholder: about 3 hours). For an episodic feed
  that's the next few episodes; for a serial one it's the chapters after
  "last clear".
- **Starter-list voices are kept ready in rotation** (*Claude's call,
  settled after the builder check*): a handful of starter entries (placeholder:
  4) are always downloaded to the same few-hours depth, and the set rotates
  over time. A starter entry the operator picks, or one Surprise me draws, is
  always one that's ready, so the starter list works offline on the first
  night. Entries not in tonight's rotation show as "downloading" until
  they're fetched.
- The bedtime screen shows a voice that isn't ready as "downloading" and
  doesn't let it be the night's voice until it is. "Surprise me" only draws
  from voices already on the phone.
- If tonight's voice is missing or fails to decode at night, **the night
  plays without a voice**. Never an error in place of sound.

### What happens to a voice through the night

The same descendant path as the scenes, applied to speech:

1. **Clear:** thin and AM-coloured, but followable. The falling-asleep
   stretch.
2. **On the radio:** narrower, with fading; you catch most of it.
3. **Next room:** through a wall; you catch phrases.
4. **Fragments:** pieces of it, slowed, repeating, from memory as much as
   from the present.
5. **The shape of a voice:** cadence and warmth, no words.

*Claude's call:* the voice isn't present all night. Early it's continuous;
later it comes and goes, leaving stretches of scenes alone, and its returns
are often *memory* (earlier passages) rather than new material.

### Level matching (a hard requirement, not a tuning knob)

Every voice file is measured (integrated loudness, e.g. LUFS) when it's
downloaded and played at a common target level, and a **short-term limiter
with a slow release** sits on the voice path to catch ads and outbursts
inside a file. The aim is that no passage of any voice is ever sudden
relative to the one before it. This is matching, not a cap: the night's own
volume is whatever the operator set.

### Which part plays tonight

A voice is one of two kinds (*Claude's calls, settled after the builder
check*):

- **Episodic** (most podcasts, the speeches, old-time radio): each night
  starts on a different episode, leaning away from recent ones.
- **Serial** (an audiobook, whether it's one long file or a LibriVox feed of
  chapters): it's one continuous recording across its files, in order, and
  each night picks up near **where it was last clear**: the position at
  which last night's voice passed from stage 2 to stage 3 above, wound back
  a few minutes. By the murmur stages nobody was listening. *Claude's call,
  made when the operator didn't answer this question directly.* The builder
  may refine "last clear".

**Telling them apart:** a feed that declares `<itunes:type>serial</itunes:type>`
is serial, LibriVox feeds are serial, a single file is serial, and
everything else is episodic. The voice's detail view has a switch to
correct the guess.

**When the night outlasts the material** (an episode is 30–60 minutes, a
night is about 8 hours): the voice **continues into the next episode or
chapter** by the same rule. A serial voice reads on in order; an episodic
one picks another episode. By then the voice is in its late stages anyway,
so this mostly supplies new murmur, and the memory supplies the rest. If
nothing more is on the phone, the voice draws only from memory for the rest
of the night.

### Surprise me

Draws the voice from everything on the phone (the operator's feeds and links
plus the starter list), leaning away from recent nights.

## Bedtime: what the screen does

- Opens on the **voice list**: the operator's voices, then the starter list,
  with **Surprise me** at the top, and last night's choice preselected so an
  ordinary night is one tap. A "no voice tonight" option exists.
- **Add a voice:** paste a link. The app works out whether it's a feed or a
  file.
- **Start.** The screen goes dark. A tap shows a minimal Stop and how long
  the night has left.
- **Settings:** wake time and weekdays; "Don't steer tonight" (carried over,
  also reachable from the bedtime screen).
- Dark throughout. Visual design beyond that is the builder's.

## What carries over from Plan 6 (by name)

From `2026-10-25-ios-night-design.md`, unchanged unless this document says
otherwise:

- **"Steering by movement"**, entire: restlessness and awake from the
  accelerometer, normalised per night; the "steadier, never busier" table;
  slow smoothing; the movement trace recorded per block; gated events still
  consuming their random draws. In this plan, "births" means new scene
  entrances, new voice passages and new memory returns; restlessness gates
  all three and never adds anything. Steering may also *hold* warp depth
  (not deepen it suddenly) while restless.
- **"The end of the night"** and **the morning lift, made precise**: weekday
  wake time sets the night's length; the lift relaxes ceilings upward only
  to their one-hour-in values, never adds events, overrides "awake" inside
  its window. In this plan the lift also eases warp depth back (a little
  clearer, a little closer), within the same bound.
- **"Audio session behaviour on the phone"**: background audio; on route
  loss fade to silence and never fall through to the phone speaker;
  interruptions fade back in.
- **"The night log"**: context, trace and steering state per block, saved to
  the app's iCloud container. Replay now happens in the **Mac test tool**
  (same engine), not in Python.
- **"Decisions from the builder check"**: paid developer account and the
  iCloud container; steering is a layer and "no steering" is first-class;
  "Don't steer tonight" for shared beds; recent iPhone, plugged in, so
  battery isn't a constraint but **memory is** (measure the engine's peak
  against the iOS background limit early).
- **Weather and sky**: one weather fetch at Start with a neutral fallback;
  sunrise and moon from location; they steer the night as in the Python
  engine (the builder chooses which parameters they touch in this design).

**Dead from Plan 6:** the drop folder and Mac watcher, the kit format, song
preparation on the Mac, the collection screen with packages and track ticks,
Python-as-reference with golden-fixture parity, and the "bundled library of
kits" idea (replaced by the scene library). **Plan 6a is dead in full.**

## Left open for the DJ

Not designed, only protected:

- The voice layer is one **slot**: a source of speech with a treatment path.
  A DJ show (host plus callers) should be able to be a different kind of
  source in the same slot, or a second slot, without changing the scene
  engine.
- AM content (commercials, station IDs, time and weather, music beds) goes
  through the same channel and so needs nothing new from it.
- The Python `night/speech.py` "through a wall" and live-radio ideas are the
  nearest prior art; read them when the DJ is designed.

## Placeholders (to be tuned by ear, recorded in project-state when built)

- Scenes present at once (2–4 early, 1–2 late)
- The 90-minute cycle's length, phase and depth range, and the overall trend
- Voice stage timings, and how often the voice comes and goes later
- Memory: how far back fragments reach, how often they return, fragment
  length
- Each warp control's range (how slow is "slowest", how far is "next room")
- Channel: band corners over the night, hiss level, fade rate and depth,
  bleed level and when it stops
- Voice target loudness and limiter settings
- Hours kept downloaded ahead per voice (about 3), starter entries kept
  ready in rotation (4), "recent" lookback for Surprise me
- Audiobook rewind from "last clear" (a few minutes)
- All Plan 6 steering placeholders, carried over

## Left to the builder

- Package and target layout (subject to the planner having no DSP
  dependency), minimum iOS and macOS versions, how tests run
- The RNG: one simple, specified generator in Swift (no Python parity to
  keep)
- The DSP for each scene, the reverb, the channel; judged by ear
- Whether the memory re-synthesises at full quality or a cheaper preview
  quality (it's going to be distant anyway)
- Feed parsing, download scheduling, storage location
- Which steering parameters weather and moon touch
- The exact element lists per scene
- Whether "distant people" scenes use small licensed or self-made raw
  material

## Order of work (suggested)

This is several pieces of work under one design. Each milestone is
something the operator can hear.

1. **Hear two scenes through the channel.** Swift package skeleton, the Mac
   tool, chimes and pixellated waves, the AM channel. Audition in isolation.
   *Start the motion spike from Plan 6 alongside, on the phone.*
2. **Hear a night.** The planner and arc, the warping (both layers), the
   90-minute shape, the rest of the easier scenes (drones, train, vent). The
   Mac tool can jump to any time.
3. **Hear a voice.** Feeds and links, downloading, level matching, the voice
   treatment stages, audiobook resume, the starter list. In the Mac tool
   first.
4. **The phone.** The app: bedtime screen, background audio, offline
   downloads, route rules, night log. First usable milestone: an iPhone
   night with no steering.
5. **The distant people.** Carolers, upstairs practice.
6. **Steering**, from the spike's findings, then the morning lift.
7. **Sleep on it.** Not done until the operator has slept a few nights and
   the placeholders have been heard.
