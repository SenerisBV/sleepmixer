# Esoterica DM Radio (iPhone)

An old radio on the nightstand. One dark screen, a dim band printed **DM**, a
needle, and a serrated wheel along the bottom. Three stations (The Lantern
Accords, Backward Lesson One, The Orchard Light) with AM static between them.
Everything is played from recordings that ship inside the app; it works offline
and with the screen locked. Design: `docs/superpowers/specs/2026-11-03-radio-dial-design.md`.
Project notes: `docs/project-state.md`, section "Plan 9: Esoterica DM Radio".

## Build and run on your iPhone

You need a Mac with Xcode and XcodeGen (`brew install xcodegen`), pipenv (for
`make stations`, which runs the repo's Python tools), the voiced recordings in
`esoterica/library/` (already there if you've voiced them), and an iPhone on
iOS 18 or later.

1. From the repo root, cut the station files: `make stations`. This writes
   `ios/Esoterica/Stations/` (generated, not committed). It is free; it calls no
   voice service. Without it the app still builds, but each station plays only
   its bed of chimes, waves and warmth, with no speech.
2. `cd ios && xcodegen`. This writes `ios/Esoterica.xcodeproj` (generated, not
   committed). Run it again whenever `project.yml` changes. Run uses Release;
   Debug renders slower than real time (about 0.6x on the Mac), so the sound
   would break up all night.
3. Open `ios/Esoterica.xcodeproj` in Xcode.
4. Select the **Esoterica** target, then **Signing & Capabilities**, and choose
   your team in the Team menu: the team is named "nl.senerisbv". That is the
   team's name, not the bundle id; the bundle id is `nl.senerisbv.esoterica`.
   Signing is automatic.
5. Plug in the iPhone, unlock it, and pick it as the run destination at the top
   of the Xcode window.
6. Press Run (the play button). If the phone says the developer is not trusted,
   open **Settings > General > VPN & Device Management**, tap your developer
   certificate, tap Trust, then Run again. (If Xcode asks for Developer Mode,
   enable it under Settings > Privacy & Security and let the phone restart.)

## Using the dial

- The radio always starts **off**, with the needle at the left end (OFF).
- **Turn the wheel out of OFF to switch on.** You get a soft click and the sound
  fades in over a couple of seconds. Drag along the wheel with your thumb, left
  to right.
- Wander the band. Between stations there is static; a needle a little off a
  station mixes that station with static. When something catches you, let go: the
  needle settles onto the nearest station and leaves it playing.
- **Turning the wheel resets the drift.** Everything comes back clear and close,
  and then, from the moment you stop turning, the night slowly recedes over the
  hours: farther away, slower, in pieces, with growing gaps between segments.
  Picking up the phone, unlocking it or a notification does not reset anything;
  only the wheel does.
- **Turn back to OFF to switch off.** The sound fades out over a second and a
  half. Nothing new plays at the end of the night; you just turn it off.
- If the Bluetooth speaker or headphones drop out, the radio fades to silence
  within about 50 ms (a moment of it may reach the phone speaker before then)
  and stays paused. Turning the wheel, or Play on
  the lock screen, brings it back.

## What is not verified yet

Built and tested in the Swift package and the simulator only. Sound on a real
device, haptics, lock-screen controls and real route changes have not been
tried. See "Known limitations / deferred" in `docs/project-state.md`.
