# The window: weather outside the radio (design, 2026-11-04)

Status: draft for the operator's review. First of four projects agreed on 2026-11-04,
in this order: (1) this sound library, (2) the fast-food gospel station, (3) the
call-in show, (4) the master DJ. Builds on Plan 9 (Esoterica DM Radio,
`docs/superpowers/specs/2026-11-03-radio-dial-design.md`), which is on `main`.

## Intent and the why

The operator heard Esoterica DM Radio on their phone for the first time on
2026-11-04: "Holy cow this sounds and feels fantastic. I love it." Their next
direction: "we're just going to add more content and build out the sound
library." Today there are only three generated beds (low warmth, felted chimes,
pixellated waves), and every station mixes the same three.

They asked for: "a felted rain sound, pixellated thunder, a glassy or pixellated
stream, and maybe a very soft, pixellated crickets and/or fireplace."

The decisive detail came when asked where the rain is: "The felted rain is
falling on my window." Rain on your window is not on the radio; it is in the
room with you. So these sounds are **a new layer outside the radio**: "The
weather should be like through an open window. It's near but not on top of us."

What the words mean, in the operator's own confirmation: "felted is what you did
to the chimes, pixellated the waves - both were great." Felted = the chimes'
treatment (soft, no hard attacks, edges taken off). Pixellated = the waves'
treatment (sample-and-hold rate reduction plus bit reduction plus a gentle
lowpass, so it reads as *remembered*, warm rather than harsh).

How the night treats it, in their words: "Maybe we have steady sounds like rain
that stay consistent all night, and maybe the inconsistent sounds like thunder
that could eventually startle recede."

The feeling to protect is the one the operator just validated on the phone: an
old radio on the nightstand, nothing to set up, the radio slowly receding. The
window adds the room around the radio. When the radio has drifted far away, the
weather is what is left.

## Goals

- A **window layer** mixed after (outside) the radio: it never passes through a
  station's Fragmenter, Distance, AM channel, or the static. It sounds the same on
  any station, between stations, and on pure static.
- Five new generated sounds, all pure DSP (no samples, no API calls, no credits):
  - **Felted rain** (steady): many soft drops with no hard transients, plus a
    soft wash, as heard on a window pane close by.
  - **Pixellated thunder** (sudden): distant rolls, never a close crack.
    Pixellated like the waves.
  - **Glassy or pixellated stream** (steady): a brook beyond the window. The
    builder may pick glassy (resonant, bell-like bubbles), pixellated, or a blend;
    whichever sounds best by ear.
  - **Soft pixellated crickets** (steady): very quiet, sparse chirping.
  - **Fireplace** (steady crackle + sudden pops): see "The fire is in the room".
- **Nobody chooses the weather.** The dial stays the only control (Plan 9: "That
  might be the only UI"). Each night picks its own weather from the night's seed.
- **Steady sounds stay steady all night.** They do not follow the drift.
- **Sudden sounds recede.** Thunder (and the fire's loud pops) get rarer and
  softer as the night goes on, until they stop (Claude's call on "until they
  stop": by full drift they are silent).

## Non-goals (for now)

- No weather control in the UI; no settings screen.
- No weather that changes the radio (e.g. thunder adding crackle to the AM
  channel). Tempting, but it is a separate idea; note it, do not build it.
- No new station beds. The stations keep their three beds as they are.
- No recorded samples.

## Anti-goals (would be a failure even if it technically works)

- **Startling.** Anything that could wake the listener later in the night:
  sudden loud thunder, a sharp pop, a crack. Thunder is always distant.
- **Harsh pixellation.** Pixellated means warm and remembered, like the waves,
  never a gritty bitcrusher.
- **On top of us.** The weather must not crowd the radio or sit dry and close in
  the ear. It is through an open window.
- **Monotony.** Every night should not sound like the same rain loop. Nights
  vary (the standing rule: the night must stay dynamic and vary nightly).
- **Breaking the current feel.** The radio, the drift, the static and the wheel
  were validated on the phone; this layer adds to them and changes none of them.

## How it behaves

### Steady vs sudden

| Sound | Kind | Over the night |
|---|---|---|
| Felted rain | steady | constant all night |
| Glassy/pixellated stream | steady | constant all night |
| Soft pixellated crickets | steady | constant all night |
| Fireplace crackle | steady | constant all night |
| Fireplace loud pops | sudden | rarer and softer, then none |
| Pixellated thunder | sudden | rarer and softer, then none |

"Constant" means the sound's own character stays the same; it still varies
naturally within itself (the rain swells and eases a little, the crickets pause)
so it does not read as a loop.

### The wheel does not bring sudden sounds back (Claude's call)

Turning the wheel resets the radio's drift because "if they're turning they must've
woken up." The window is not the radio, and thunder getting louder again after you
touch the dial helps nobody. So the sudden sounds recede on **time since the radio
was switched on**, not on the wheel-reset drift. Concretely: they read
`Drift.level(clock: secondsSinceSwitchOn, seed:)` directly, not the `DriftClock`.
Switching off and on again starts a fresh night (same as Plan 9), which does reset
them.

### The fire is in the room (Claude's call)

A fire is inside, not outside the window, so it sounds a little closer and drier
than the window sounds (less of the "open window" softening). Its steady crackle
stays all night; its occasional loud pops are sudden sounds and recede.

### Each night's weather (Claude's call, a starting set)

The night's seed picks one weather from a small set, for example:

- rain alone;
- rain with distant thunder early in the night;
- crickets and the stream;
- the fire alone.

Builder's choice whether to add more combinations or weight them. Weather stays
the same for the whole night (Claude's call): no changes mid-night in this first
version. Rain starting or stopping during the night is a possible later idea.

### On, off, and the radio

- The window layer plays whenever the radio is on, from the moment it switches on,
  at whatever the needle is doing (station, static, between).
- Switching off fades the window out with everything else (same 1.5 s fade).
  "You just turn it off" means the whole night ends.
- Lock screen / app closed: same as the radio; it keeps playing.

### Level (Claude's call, tune by ear)

Quiet enough that the radio is still the main thing when you are awake and
listening; present enough that it carries the night once the radio has receded.
A starting guess is about 6 to 10 dB under a station at drift zero. Record the
value as a placeholder.

### Space

The engine renders mono today and copies it to both stereo channels. The window is
a chance to use width: a gentle stereo spread makes "through an open window"
easier to hear apart from the radio. Builder's choice whether to render the window
in stereo; if so, the radio stays mono in the middle and the window is wide.

## Constraints

- Everything is generated in Swift DSP like the existing scenes (`swift/Sources/NightDSP/Scenes/`),
  real-time safe (no allocation per block, no locks on the audio thread), and rendered
  on the existing render thread ahead of playback (Plan 9's ruling).
- Must keep the existing performance headroom on the phone (Release renders at about
  44x real time today); the window layer must not cost more than the three stations
  together.
- Seeded and repeatable like every other scene (`NightRandom`), so tests can check it.
- No API calls, no credits, no network in tests.
- Every invented number is a placeholder and goes in `docs/project-state.md`.
- Works offline on the phone; nothing new to download or bundle.

## What's left to the builder

- The synthesis of each sound, guided by the felted/pixellated meanings above and
  the existing ChimesScene and WavesScene code.
- Glassy vs pixellated (or both) for the stream.
- The exact weather set, weights, levels, and how thunder's rarity and softness map
  onto the drift.
- Stereo or mono for the window.
- Auditioning (Claude's call): the operator listens on the phone, as with Plan 9
  ("Let's not play on the mac"). The builder may still render short WAVs with
  `nightctl` to check sounds themselves.
- Tests: a peak bound per sound (like `peakIsBounded`), seek/repeatability, sudden
  sounds silent at full drift and not revived by a wheel touch, the window unaffected
  by the needle position.
