# Esoterica

A collection of found recordings that prime the mind for dreams: strange,
sincere, long-form spoken word, voiced once and then warped by the night
(clear, then on an old radio, then from the next room, then fragments, then
just the shape of a voice).

The design is `docs/superpowers/specs/2026-11-02-esoterica-design.md`. Read its
"What this is, and where it came from" section before writing anything new.
It is the brief.

```
esoterica/
  README.md              this file: the script format and the content rules
  scripts/<show>/<id>.md the scripts (committed)
  library/               voiced audio and manifests (git-ignored):
                         <id>/pNN.raw.wav (paid takes), pNN.wav (with source
                         character), voice.json, recording.json
  audition/              audition excerpts (git-ignored)
  listening/             the listening set from listening.sh (git-ignored)
  listening.sh           makes the listening set (see "The listening set")
  voices.yaml            providers, candidates, and the chosen voice per slot
```

## The script format

A script is a Markdown file at `esoterica/scripts/<show>/<id>.md`. It has two
parts: a front matter block and a body of passages.

### Front matter

A YAML block between two lines that contain exactly `---`. It must be the
first thing in the file.

| Key | Required | Value |
|---|---|---|
| `id` | yes | kebab-case, equal to the filename without `.md` |
| `show` | yes | one of `testimonies`, `sideline`, `addresses`, `stations`, `lessons`, `meditations`, `shuffles` (ASCII; the French show is `meditations`, no accent) |
| `title` | yes | internal only, never spoken |
| `language` | yes | `en`, `fr`, or `en+invented` |
| `speaker` | yes | a prose note: age, manner, how close the microphone is, the room. Invented, never a real person |
| `source_character` | yes | one of `tape`, `room`, `oldmic`, `hum`, `clean` |
| `voice_profile` | no | a short comma-separated list of the voice as the operator imagines it (e.g. `female, older, slow, deep, scratchy`). The operator's words; STOP 2 picks voices against it before the `speaker` note |
| `speed` | no | the provider's speaking rate for this recording, over `voices.yaml` (ElevenLabs 0.7-1.2, Cartesia 0.6-1.5; the parser accepts 0.5-1.5). Recorded per take; changing it makes the takes stale, so re-voice with `--revoice pNN`. **`eleven_v4` ignores it** (measured 2026-11-03); slow v4 down with an inline tag such as `[slowly]` instead |
| `delivery` | no | one or more bracketed ElevenLabs v4 tags sent before every request, e.g. `"[slowly, languidly, like molasses]"`. Recorded per take; a change makes the takes stale. Refused for Cartesia (it would read the tag aloud). One tag only steers the first sentence or two of a long request; see `docs/project-state.md`, "Pace" |
| `pause_stretch` | no | 1.0-4.0, default 1. Free and render-time: `render` lengthens the silences between phrases by this factor (speech untouched). For an end-of-the-night pace |
| `voice` | yes | present but empty (YAML null) until STOP 2 picks one |

**Who speaks.** A show with a recurring host keeps one voice: the same commentator, newsreader, teacher, guide and shuffler every time, so all lessons share one teacher. Testimonies and addresses are different people, so every recording gets its own voice and none repeats. The voice comes from `esoterica/voices.yaml`, keyed by show or, for testimonies and addresses, by recording id.

Example:

```yaml
---
id: the-corridors
show: testimonies
title: The Corridors
language: en
speaker: >
  A woman in her late sixties, talking across a kitchen table ...
source_character: tape
voice:
---
```

### Passages

- The body after the front matter is a sequence of passages.
- Passages are separated by a line containing exactly `[passage]` (no other
  text, no trailing spaces). There is no `[passage]` line before the first
  passage or after the last one.
- Blank lines around a separator, and at the start and end of a passage, are
  ignored. Blank lines inside a passage are paragraph breaks and may be read
  as a slightly longer breath.
- An empty passage (nothing but blank lines and an intensity comment) is
  malformed.
- A passage may begin with an intensity comment as its first non-blank line:
  `<!-- intensity: low -->`, `<!-- intensity: medium -->` or
  `<!-- intensity: high -->`. Without one, intensity is `medium`. This is the
  only HTML comment allowed anywhere in a script body.
- Intensity is how much attention a passage holds. Early passages may be
  `high` or `medium`; later ones are `low`: looser, more textural, losing
  nothing if half-heard. The planner uses it to keep demanding passages early
  in the night.

### Delivery cues

Inline, in square brackets. These six are the only cues allowed, in every
language (a French script still writes `[pause]`, not `[silence]`). The
voicing adapters translate or strip them per provider.

| Cue | Meaning |
|---|---|
| `[pause]` | a short pause, about a second |
| `[long pause]` | a long pause, two to four seconds; in lessons, the listener's turn to repeat |
| `[breath]` | an audible breath |
| `[softly]` | the next phrase quieter, closer |
| `[whisper]` | the next phrase whispered |
| `[laughs quietly]` | a small private laugh |

Any other bracketed text is an error. Use cues sparingly, where a real person
would pause or breathe.

### Shuffles

In a `shuffles` script each passage is one burst: one concrete image per line,
20–40 lines, no cues. The voicing tool spaces the lines 2–3 seconds apart. The
intensity comment is still allowed.

## Voicing

`sleepmix esoterica estimate | audition | voice | render` (in
`sleepmix/esoterica/cli.py`) turns scripts into audio. `estimate` only counts. The two commands that
can spend, `audition` and `voice`, print the characters and estimated cost per
provider first and spend nothing without `--yes`. `render` is free and prints
no cost.

- **Commands:** `sleepmix esoterica estimate` (counts only);
  `audition --slot S | --show SHOW | --all [--yes]` (paid);
  `voice <id> | --all [--yes] [--revoice pNN ...]` (paid); `render <id> | --all`
  (free: no provider, no key, no estimate; `--all` skips recordings with no raw
  takes, "skipped, not voiced", and partly voiced ones, "skipped, partially
  voiced (missing …)"). Never pass `--yes` without reading the estimate. Keys
  live only in the repo-root `.env`.
- **Estimates are exact:** every count is the very requests voicing sends
  (each `[long pause]` segment chunked to the provider's `max_chars`), each
  counted after the provider's cue translation. Pieces and passages already on
  disk are not counted.
- **Voices** come from `esoterica/voices.yaml`: per-provider model, price and
  limits under `providers:`, 2–3 candidates per slot per provider under
  `candidates:`, and the pick per slot under `chosen:`.
- **Audition:** `sleepmix esoterica audition --slot <slot> | --show <show> | --all [--yes]`
  voices about 120 spoken words of the first passage of the first script (by
  id) in each slot (shuffles: the first 16 images) with every candidate, into
  `esoterica/audition/<slot>/<provider>-<voice>.wav`, and lists them (with each
  voice id) in `esoterica/audition/index.md`. Each file has a sidecar
  `<provider>-<voice>.json` naming the provider, model and voice id it was made
  with; if a candidate's voice id (or the model) changes in `voices.yaml`, the
  next `audition` counts that file again and `--yes` replaces it. A file with
  no sidecar counts as unknown and is re-made too.
- **Voicing:** `sleepmix esoterica voice <id> | --all [--yes]` uses the slot's
  `chosen:` voice and writes `esoterica/library/<id>/`.
- **Raw and rendered:** `pNN.raw.wav` is the provider's take (loudness-normalised) and is
  never overwritten. `pNN.wav` is the raw take with the script's `source_character`
  applied, a 10 ms fade at each end and loudness re-normalised;
  `sleepmix esoterica render <id> | --all` re-makes it for free and rewrites
  `recording.json`, which records the character tuning used (`character_params`).
- **Passage files** are named from the passage's 0-based `index`, 1-based on
  disk: index 0 is `p01.wav`, index 1 is `p02.wav`. The manifest's `file` field
  holds that name. Each is mono float32 WAV at 44100 Hz, normalised to
  -24 dBFS RMS over speech frames with peaks at most -3 dBFS.
- **Resumable to the request:** a passage is sent as pieces (its `[long pause]`
  segments, chunked; a shuffle's images). Each piece is saved as
  `pNN.sMM.<key>.seg.wav` the moment it is paid for, so a provider error at
  piece N keeps pieces 1 to N-1 and a re-run sends only N onwards. When all
  pieces are in, `pNN.raw.wav` is written and the piece files are deleted. A
  passage (or audition file) already on disk is never voiced again, and
  `recording.json` is written only when every passage exists.
- **A changed script is caught.** Each take has a sidecar `pNN.raw.json` with
  the sha256 of the passage text it was voiced from (the script's text with its
  cues; the intensity comment is not part of it). If a passage is edited, or one
  is inserted or removed so the numbering shifts, `voice` and `render` refuse
  and name the stale passages. Fix it with
  `sleepmix esoterica voice <id> --revoice p02` (repeatable, or `p02,p03`): it
  prints the estimate and, only with `--yes`, deletes the named stale takes
  (raw, sidecar, piece files, rendered file and the manifest) and voices them
  again. Naming a passage that is not stale is refused; to re-voice a good take
  anyway, delete its `pNN.raw.wav` and `pNN.raw.json` by hand. Recordings voiced
  before sidecars existed are backfilled by `render`: a take with no sidecar
  whose `recording.json` text equals the passage's current spoken text gets one
  (marked `"backfilled": true`).
- **Cues** are translated per provider (ElevenLabs v4 audio tags or ellipses;
  Cartesia `<break>` tags and `[laughter]`) or stripped where the provider has
  no equivalent. `[long pause]` is not sent at all: the tool splits there and
  inserts 3 s of real silence, so the lessons get a dependable answer gap.
- **Shuffles** are voiced one image per request and assembled with 2–3 s gaps,
  seeded from the recording id. A line that opens with a French article
  (`le`, `la`, `les`, `un`, `une`, `des`, `du`, `au`, `aux`, `l'`) is sent as
  French.
- **What is committed:** the scripts and `voices.yaml`. `esoterica/library/`
  (audio, sidecars and the `recording.json` manifests), `esoterica/audition/`
  and `esoterica/listening/` are git-ignored: the audio is large and the
  manifests are derived (a free `render` re-makes them from the raw takes and
  the scripts).

## The listening set

`esoterica/listening.sh` (free, no provider) writes, for passage 1 of every
recording that has a `recording.json`, into `esoterica/listening/`:
`<id>-plain.wav` (the rendered `p01.wav`, character included; not the raw
take), `<id>-near.wav` (`nightctl audition voice
--distance 0`) and `<id>-far.wav` (`--distance 0.6 --fragmentation 0.3`), and
prints RMS, peak and centroid. The near and far files are the first 90 s;
`SECONDS_PER_FILE=150 esoterica/listening.sh` changes that. It builds `nightctl`
in release first.

## Playing a recording through the engine

```
cd swift
swift run -c release nightctl audition voice \
    --file ../esoterica/library/the-orchard-light/p01.wav \
    --seconds 90 --distance 0.6 --fragmentation 0.3 --play
```

## The shows

| Show | What it is | Language |
|---|---|---|
| `testimonies` | Someone recounts a strange inner journey (corridors, thresholds, a presence) as the most important thing that has ever happened to them. You can't tell if they're OK. | `en` |
| `sideline` | Play-by-play and colour commentary of a made-up sport, rules never fully explained, for a regional audience that knows them. Gentle, patient, reverent about small things. | `en` |
| `addresses` | Speeches by invented figures at invented occasions in histories that didn't happen. Grand in cadence, strange in content. | `en` |
| `stations` | News radio (headlines, weather, traffic, time checks) from somewhere else. Calm, routine, impossible. | `en` |
| *(planned)* late-night call-in show | A station on the dial: a soothing overnight host taking calls. The operator's "number 1 sleep request"; added to the station list 2026-11-03, not designed or written yet, so not a `show` value the parser accepts. | `en` |
| `lessons` | A clinical call-and-response course in a "language" that is not a language: reversed English, or one soft word repeated (*mubba*). It must never sound like a real (especially Romance) language. The example sentences widen into a strange, gentle world. | `en+invented` |
| `meditations` | French guided meditations that start conventionally and drift somewhere unexpected. | `fr` |
| `shuffles` | Bursts of rapid, unrelated, concrete sensory images, a few in French. | `en` (some `fr` lines) |

## Content rules

These are binding (from the plan's Global Constraints and the spec's
anti-goals):

- **Intimate delivery, never customer service.** Close, unhurried, a little
  unguarded, with real breath and pauses.
- **Never ironic about spirituality.** The collection toys with it but never
  sneers. No speaker is a punchline; no script winks.
- **Never frightening.** The "is this person OK?" flicker is allowed and
  wanted. Horror, violence, menace, distress, self-harm, illness, injury and
  anything that could wake someone are not.
- **Never introduces itself.** No title, no welcome, no framing narrator, no
  scene-setting. Every recording starts *in medias res*, mid-thought or
  mid-sentence, as if the tape was already running. "I've never told anyone
  this, but…" is an intro.
- **Never concludes.** No summary, no sign-off. The last passage trails off
  mid-clause.
- **No real, named people** depicted, and no cloned voices.
- **No real brand names**, station call signs or products in the audio.
  Invent places, sports, histories, languages and call letters.
- **No dates.** No years, decades or real time zones; "when was this
  recorded?" must stay unanswerable.
- **Followable early, lossless when half-heard late.**

## Writing new scripts

Specific, concrete, sensory detail carries the sincerity: the texture of a
wall, what someone's hands were doing. Come at things sideways. Write for the
ear: sentences a person could say in one breath, small self-corrections,
repetition the way people repeat when something matters. Passages run about
2–5 minutes (roughly 120 spoken words a minute); shuffle bursts 1–2 minutes.
