# Plan 3d: presets — configs you save on purpose

**Status:** design approved 2026-08-05, not yet planned.

## What this is for

`sleepmix` takes one song, separates it into stems, finds a loop, and repeats
that loop for half an hour while eroding it. The mixer built in Plan 3b lets
you hear any point in that decay arc while you set it up. But closing the
mixer discards everything you tuned, and there is no way to carry a setup you
like from one song to the next.

The presets table, its routes, and its validation already exist and are
tested. Nothing in the interface reaches them.

## The decision that shaped this

Two mechanisms were on the table: named recipes reusable across songs, and
per-song memory that quietly restores whatever you last had on a song.

**The operator chose defaults-on-open, with saving opt-in.** Reopening a song
gives a clean slate; anything you want back, you save deliberately.

That removes a whole half of the originally-imagined plan — no per-song config
table, no debounced write path, no question of which of two mechanisms wins on
open. **One concept: presets.** The cost the operator accepted is that a
configuration not saved is a configuration lost, which is why saving and
applying must both be one click.

## What a preset carries, and what it does not

This is the part that fails silently if it is wrong, because nobody in this
loop can hear the difference between a mix and a slightly wrong mix.

**Not carried — `loop.start_s` and `loop.end_s`.** A loop region measured in
seconds on one song is meaningless on another. Applying a preset must never
move the current song's loop region. Both are stripped when a preset is saved.
The rest of `LoopConfig` — `bars`, `beats_per_bar`, `crossfade_ms`,
`search_start` and `search_end` — is portable and stays. Note `search_start`
and `search_end` are *fractions* of a track rather than seconds, which is
exactly why they travel where `start_s` and `end_s` do not.

**Not carried — `separation_model`.** Changing it nulls the session's stems, so
the next preview runs a real Demucs separation inside the per-song preview
lock: minutes, no progress reporting, and a screen that already believes itself
playable. `Page/Mixer.elm` withholds a control for it deliberately, by name,
with the reasoning written above the exclusion. A preset must not smuggle one
in through the back door.

**Carried:** stems and their per-stem gain, reverb send, enabled flag and decay
settings; the reverb section; tempo; soundbed; output; and `seed`.

`seed` is a judgement rather than an obvious call. It fixes the random parts of
the decay — dropouts, noise, spectral holes. Carrying it means a preset
reproduces the *same* erosion pattern on a new song rather than a new one of
the same character. That is the more predictable behaviour and the easier one
to reason about, so it travels; anyone wanting fresh randomness changes one
number.

## Server work

**`PUT /api/presets/{preset_id}`** — takes a name and a config, and covers both
renaming and saving over. Today the unique-name constraint means overwriting
requires delete-then-recreate, and a failure between those two loses the preset
outright.

It validates exactly as `create_preset` does, by constructing a `MixConfig` and
letting a `ValueError` become a 400. A preset that could never render must fail
at save, not at render time when the connection to the offending value has been
lost. 404 for an unknown id; 409 when the new name is already taken by a
different preset.

**`songs.last_preset_id`** — a nullable column, set when a preset is applied to
a song or saved from that song's mixer. It exists only so the mixer can say
*"Last used here: Deep erosion"* with an Apply button beside it. **It is never
applied automatically.** That was considered and rejected: a preset that
re-applies itself means editing it silently changes songs tuned weeks ago.
This is a shortcut for the opt-in, not a weakening of it.

A preset deleted while a song points at it leaves a dangling id. The song row
keeps it; the mixer resolves it against the preset list and shows nothing when
it does not resolve. A foreign key with `ON DELETE SET NULL` would be tidier
and is not worth a migration on a table this small.

**`GET /api/config/default`** — returns `MixConfig().to_dict()`.

This closes a defect documented since Plan 3b: a mixer opened at defaults
produces an audibly different mix from `sleepmix render` at defaults, on *every*
stem. `Config.fromSchema` builds each stem from the schema's flat per-field
defaults, while `MixConfig` curates a real starting point — drums disabled,
bass decay disabled, vocals on an `exp` curve to 2200 Hz and −16 dB with
spectral holes at 0.45, other to 2400 Hz and −4 dB. The schema deliberately
does not describe list-typed fields, so there has never been anything for the
frontend to read the curated list from, and hard-coding it in Elm is exactly
the drift the schema exists to prevent.

With "defaults are what you see on open" now being the entire opening
experience, this is the moment. Without it, "always the defaults" means
defaults that do not match the tool's own.

## The mixer's preset bar

Not a screen. Presets are applied in the mixer, so that is where they live; a
separate screen would be a second place to navigate for what is one row of
controls.

- A select of saved presets, ordered by name as the API already returns them.
- **Apply** — replaces the mixer's config with the preset's, leaving the
  current song's loop region and separation model alone. **A field the preset
  does not carry resets to its default rather than keeping whatever the mixer
  had.** Apply means "make it look like this", not "merge this in": a preset
  saved before a config field existed would otherwise leave that field holding
  a value from a recipe the operator thought they had replaced, and no
  screenful of controls would say which fields came from where.
- **Save as…** — prompts for a name, POSTs, and the new preset becomes the
  selection.
- **Save over** — PUTs the current config into the selected preset, after
  confirming, because it is destructive and one click from Apply.
- **Delete** — after confirming.
- The *"Last used here"* line, when the song has a resolvable one.

Applying a preset does not stop playback or leave the mixer. It changes the
config, which fires a preview through `Preview.request` like any other control
change — so you hear the recipe you just applied, which is the point.

## Failure modes the plan must handle

- **A preset saved from one song and applied to another must not carry that
  song's loop.** Tested on both sides: the stripping at save, and the
  preservation at apply.
- **A preset whose config the server rejects** must fail at save with the
  reason, not be stored.
- **A name collision** on Save as… is a 409 and must say so, not fail silently
  or overwrite.
- **A dangling `last_preset_id`** must render as nothing, not as an empty
  entry or a crash.
- **Applying a preset must go through `Preview.request`**, never the port
  directly. Every control change in the mixer routes through the state machine
  that collapses a scrubber drag into one request; a preset apply is a control
  change like any other.

## Testing

The stripping and the merge are pure functions of a config and belong in Elm
where `elm-test` reaches them — the same move that put `Preview.elm`'s
decisions outside the audio port. Cover: a saved preset has no `loop.start_s`;
applying one preserves the song's existing loop; applying one replaces every
carried field; a preset with a partial config does not resurrect stale values
from the config it replaced.

**View-level tests from the start**, through `Main.view`, not a hand-built page
config. The pattern was introduced late in Plan 3c and its absence let three
findings through — a warning could be deleted from a screen with both suites
green. The preset bar gets markup assertions for the buttons and their wiring.

Python covers the new routes: `PUT` for rename, overwrite, 404 and 409; the
default-config route against `MixConfig()`.

## Out of scope

- **Per-song config memory** — explicitly rejected above.
- **Auto-applying a remembered preset** — explicitly rejected above.
- **Preset import/export or sharing.** Local single-user tool.
- **A presets screen.** The bar is the interface.
- **Migrating `songs.last_preset_id` to a foreign key.**
- **Segment selection and arrangement**, a path allow-list for `import_song`,
  streaming peak computation, and authentication — carried forward unchanged.
