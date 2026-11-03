# Project state

## Where the project is heading (2026-11-02): Plan 7, the AM night

**Read this first.** On 2026-11-02 the operator redirected the project. The
night is no longer made from their songs. It's made from a built-in library
of **generated scenes with an AM-radio character** (soft-mallet chimes,
pixellated waves, sleeping on a train, wind through a long vent, carolers,
someone upstairs practicing), which **warp across the night into their own
descendants**: further away, slower, in pieces, out of proportion, "like
dreams replay experience incompletely and with different proportions, and
likewise, a warm memory the further you get from it." The operator's own
contribution was to be a **spoken-word voice from a pasted link** (podcast feeds,
audiobooks, speeches) that starts clear and drifts to a murmur. **Since
2026-11-02 the voice layer is Esoterica instead:** generated found-recording
spoken word (testimonies, a made-up sport's commentary, speeches from histories
that didn't happen, news radio from somewhere else, clinical lessons in a
"language" that isn't one, French meditations, bursts of images), voiced by
text-to-speech and warped by the same channel as the scenes. Link import is
still a door, now left ajar (see "Plan 8a" below). Their "number 1 sleep
request", a late-night call-in show with a soothing overnight DJ, is deferred
until they've thought about how; the voice layer is built so it can grow into it.

- **Design:** `docs/superpowers/specs/2026-11-02-am-night-design.md`,
  approved 2026-11-02, on branch `feat/am-night`. **Plan 7a (two scenes through
  the channel, a Mac audition tool) is built and tested; the operator has not
  listened yet.** Plan 7b (soft-mallet chimes, three tone dials, a low-warmth
  scene, after the operator's first listen) is built too; the new set awaits
  them (section "Plan 7b"). **Plan 8a (the Esoterica starter set: scripts, voicing, a file source in the
  engine) is built; four recordings are voiced and the listening judgement is
  outstanding** (section "Plan 8a" below). More scenes, the planner and the app
  are not planned or built.
- **Superseded, never built:** Plan 6 (`2026-10-25-ios-night-design.md`)
  except the sections Plan 7 keeps by name (steering by movement, the
  morning lift, audio-session rules, the night log, the builder-check
  decisions), and Plan 6a (kits and the drop folder) in full.
- **How it's built:** one Swift package (`NightEngine`) shared by a Mac
  tuning tool and the iPhone app. The Python engine below is **not ported**;
  it stays in the repo, working and untouched, as the reference for the
  rules that carry forward (nothing that goes wrong makes a sound, ceilings
  only descend, no transients, a planner with no audio imports, steering
  gates never shift the RNG, excerpt tools build the engine exactly as the
  app does).
- **Placeholders:** Plan 7 lists its own (section "Placeholders"). Plan 7a's
  and 7b's are copied here, by name and value, in their sections; later plans
  add theirs.

Below Plan 8a come the Plan 7a and 7b sections (the Swift engine); after them,
the Python engine and the web mixer as built through Plan 5, Phase 3.

## The app's UI idea: a radio dial (operator, 2026-11-03)

In the operator's words: "I think a radio dial might be the UI with a
serrated wheel UX, and users scroll station to station with static between
or mixed over when the needle is a little off. That might be the only UI."

What that implies, as Claude reads it (not designed yet): the shows are
stations on one dial (testimonies, sideline, addresses, strange stations,
lessons, méditations, shuffles, and the late-night call-in show the operator
added to the station list the same day). A serrated thumb-wheel moves a
needle; landing between stations gives AM static, and being slightly off a
station mixes that station with static, which fits the AM channel the engine
already has (distance, fragmentation). Possibly no other screen at all. The
iPhone app is not planned or built (Plan 6's iOS design was superseded), so
this is the starting picture for the app milestone, alongside the planner and
a real-time engine, which the app also needs.

## Plan 8a: the Esoterica starter set (2026-11-03, branch `feat/esoterica`)

**What this is, in the operator's spirit.** Esoterica is a collection of found
recordings that prime the mind for dreams: strange, sincere, long-form spoken
word, delivered intimately (never customer service), never ironic about
spirituality, never frightening (the "is this person OK?" flicker is wanted),
never concluding (the last passage trails off mid-thought) and never
introducing itself (every recording starts in medias res, as if the tape was
already running). Inspiration is Storm-style found recordings. It is generated,
not recorded: Claude writes the scripts, text-to-speech voices them once, a
light "where was this found" texture is added, and the night engine then warps
each recording like the scenes: clear, then on an old radio, then from the next
room, then fragments, then just the shape of a voice. Design:
`docs/superpowers/specs/2026-11-02-esoterica-design.md` (read "What this is, and
where it came from" first; the STOP 1 amendments at its end record the
operator's changes to the lessons and to who speaks).

### What shipped

| Piece | Where | State |
|---|---|---|
| Nine scripts (eleven thousand words), seven shows | `esoterica/scripts/<show>/<id>.md` | written; operator read them at STOP 1 and kept all but Aurish |
| Script parser, manifest, `.env` reader | `sleepmix/esoterica/{script,manifest,env}.py` | built, tested (the separate `cost.py` estimator was deleted in the final review: the CLI's billed-character count is the only estimator) |
| Providers (ElevenLabs, Cartesia), voicing, CLI | `sleepmix/esoterica/{providers,voicing,cli}.py`, `esoterica/voices.yaml` | built; `estimate`, `audition`, `voice`, `render` |
| Source character (tape, room, oldmic, hum, clean) | `sleepmix/esoterica/character.py` | built; free, re-renderable |
| Engine file source and `nightctl audition voice --file` | `swift/Sources/NightDSP/Sources/FileSource.swift`, `Primitives/WAVReader.swift`, `NightCLI` | built, tested |
| The listening set | `esoterica/listening.sh` -> `esoterica/listening/` | made; **not yet listened to** |

Pipeline: script -> voice (`sleepmix esoterica voice`, paid) -> raw takes
`esoterica/library/<id>/pNN.raw.wav` (never overwritten) -> free `render` applies
the source character and normalises -> `pNN.wav` + `recording.json` (the manifest)
-> the Swift engine plays `pNN.wav` as a `VoiceClip` through the same
Fragmenter -> Distance -> AM channel chain as the scenes.

**There is no planner or app wiring.** Nothing yet decides which recording plays
when in a night; `nightctl audition voice` is the only consumer of the library.

### Scope change at STOP 2: only four recordings are voiced

At STOP 2 the operator said "Let's just do a few to start". Voiced:

| Recording | Show | Voice (ElevenLabs `eleven_v4`) | Character |
|---|---|---|---|
| `the-lantern-accords` | addresses | Harriet | room |
| `backward-lesson-one` | lessons | Peter | clean |
| `the-orchard-light` | testimonies | Julian | oldmic |
| `northern-tide-final` | sideline | Bill | hum |

**Unvoiced, pending the operator's listening:** `the-corridors`,
`la-maison-sous-la-mer`, `mubba-lesson-one`, `qvel-the-far-shore`,
`shuffles-one`. Their voices are already picked in `voices.yaml` `chosen:`, so
once the operator is happy, `sleepmix esoterica voice --all` (it prints the
estimate and needs `--yes`) finishes the set. `sleepmix esoterica render --all`
skips them with a "skipped, not voiced" line; `render <id>` for one of them
still fails with "raw takes missing".

### The voices chosen, and why

Chosen by Claude, from each script's `voice_profile` (the operator's words) and
the candidates' library descriptions, **not by ear**; the operator accepted the
picks at STOP 2 after hearing the audition. All eight are ElevenLabs
`eleven_v4` (Cartesia was audition-only and won no slot):
the-corridors = Blue (older, low, gritty), the-orchard-light = Julian (old
British man, deep, a little rough), the-lantern-accords = Harriet (older,
refined, commanding), sideline = Bill (old man, friendly, comforting),
stations = Daniel (clear, authoritative news voice), lessons = Peter
(middle-aged, even, the clinical teacher), meditations = Mila (native French,
made for meditation), shuffles = Matilda (alto, clinical, verified French).
Reasons for each are in `voices.yaml` beside `chosen:`.

**Who speaks (operator's rule from STOP 1).** One voice per show for sideline,
stations, lessons, meditations and shuffles ("we should keep one voice for the
language"). Testimonies and addresses are different people, so each recording
gets its own voice, and a test enforces that none repeats (addresses were
Claude's extension of the operator's testimony rule). As the library grows the
testimony voice pool has to grow with it.

### Characters and credits spent

| What | Provider | Characters |
|---|---|---|
| Audition (40 files, 8 slots) | ElevenLabs `eleven_v4` | 14,703 |
| Audition (same files, other candidates) | Cartesia `sonic-3.6` | 10,394 |
| The four recordings | ElevenLabs `eleven_v4` | 27,114 |

ElevenLabs total about 41,817 of the operator's 265,000 credits (1 credit per
character for v4). The whole starter set is estimated at 57,134 characters, so
the five unvoiced recordings need roughly 30k more. Shared-library ElevenLabs
voices worked by id without being added to the account.

### Pace: the end-of-the-night re-voice (2026-11-03, branch `feat/esoterica-pace`)

**What the operator asked.** After listening, backward lesson and orchard light
are "great as-is". The Lantern Accords and Northern Tide should be slower:
"speech more like an elderly person, or more deliberately slow and leisurely, a
kind of end-of-the-night vibe". Of four free offline test versions (speech
time-stretched to 85% or 75% with ffmpeg `atempo`, pauses 1.6x or 2.2x longer),
they said "for lantern accords, slower would be acceptable, but in both
versions, I would prefer much slower if it were naturally revoiced". The
"much slower" version was 75% speech and 2.2x pauses.

**What was built.** Two optional script keys (`esoterica/README.md` documents
them):

- `speed`: the provider's speaking-rate setting for this recording,
  overriding `voices.yaml`. It is recorded in each take's sidecar
  (`pNN.raw.json` gains `"speed"`; a sidecar without it means the default), is
  part of the piece-cache key, and a change makes the takes stale, so
  `voice <id> --revoice pNN` is the deliberate way to re-voice at a new speed.
- `pause_stretch`: free and render-time. `render` lengthens every silence of at
  least `PAUSE_MIN_S` between two stretches of speech by this factor (digital
  silence inserted mid-pause, speech samples untouched, raw takes untouched),
  before the source character. The manifest's `character_params` records it
  when it is not 1.

Both scripts now carry `speed: 0.7` and `pause_stretch: 2.2`. Rendered, the
Lantern Accords is 10.9 min (was 8.3) and Northern Tide 15.6 min (was 12.0),
all of the gain from the longer pauses.

**What went wrong: `eleven_v4` ignores `speed`.** Both were re-voiced at 0.7
(17,398 characters) and the raw takes came back the same length as at 0.85.
A 79-character test sentence then measured, on the sideline voice (Bill):
`eleven_v4` 5.52 s at speed 0.7 and 5.52 s at 1.2 (identical), against
`eleven_multilingual_v2` 7.52 s at 0.7 and 4.13 s at 1.2. So the v4
model ignores the setting, and the `speed: 0.85` in `voices.yaml` has never
applied to any v4 take either. The API reference documents `speed` with no
model restriction, which is why it was trusted; it should have been checked
with one short sentence first. The re-voiced takes are good new takes at the
old pace, not slower ones. The 0.85 takes they replaced are kept, untouched, in
the git-ignored `esoterica/library/_superseded/<id>-speed-0.85/`.

**What does slow v4 down** (same sentence, same voice): an inline tag before
the text. `[slowly]` 6.40 s, `[tired, speaking very slowly]` 6.24 s,
`[drowsy] [slowly]` 6.00 s, against 5.36-5.52 s plain: about 15% slower,
natural, in v4's own performance. `eleven_multilingual_v2` at 0.7 is about
30-35% slower but is a different (less emotive) model, so it changes the
recorded voice and needs a full re-voice. Samples for the operator:
`bill-v4-plain.wav`, `bill-v4-slowly.wav`, `bill-v4-tired.wav`,
`bill-v4-drowsy.wav` and `bill-v2-speed0.7.wav` in the session scratchpad
(`.../scratchpad/v4tags/`). **Decision pending with the operator**: v4 with a
slow tag, v2 at 0.7, or the current takes with longer pauses only.

**Spend.** The re-voice 17,398 characters plus the speed and tag tests 768:
ElevenLabs total now about 59,983 of 265,000 credits. Then a tag test in the two real voices
(Harriet, Bill; one sentence each, 1,308 characters): plain / `[slowly]` /
`[languidly]` / `[slowly, languidly, like molasses]` / `[very slowly, sleepy,
drawn out]` gave Lantern 8.16 / 10.00 / 9.04 / 10.16 / 10.48 s and Northern
7.04 / 8.24 / 7.44 / 8.24 / 8.32 s (scratchpad `molasses/`). Total about 61,291.

**Tag references, by ear (the operator, 2026-11-03).** "Molasses was the best
over both. Sleepy was probably best on Northern Tide, but molasses was a close
second, and it was the best on Lantern Accords." They asked for these to be
kept because the differences are subtle and may suit different places:

| Tag | Heard as |
|---|---|
| `[slowly, languidly, like molasses]` | best over both; the one in use |
| `[very slowly, sleepy, drawn out]` | probably best on Northern Tide (Bill); a candidate for other sleepy, older voices |
| `[slowly]` | as slow as molasses by the numbers |
| `[languidly]` | barely slower; changes tone more than pace |

**The `delivery` key and a second miss.** A script's `delivery` (one or more
bracketed tags) is sent before every request, recorded in the sidecar, part of
the cache key and counted in the estimate; a change makes the takes stale; it
is refused for Cartesia, which would read it aloud. Both scripts got
`delivery: "[slowly, languidly, like molasses]"` (their `speed: 0.7` removed,
it does nothing on v4) and were re-voiced: 17,853 characters. The raw takes
came back the same length again (Lantern 8.2 min, Northern 11.9 min). A
request here is about 1,600 characters (a passage is one request unless a
`[long pause]` splits it), and one tag at the start wears off after the first
sentence or two; the one-sentence test could not show that. A realistic test
then (Harriet, three paragraphs of Lantern p01, 2,242 characters), speech time
with silences removed: plain 20.5 s; tag at the start 22.7 s (+11%); tag before
every paragraph 23.9 s (+17%); tag before every sentence 25.3 s (+23%, but 80%
more characters). Files: scratchpad `molasses-long/`. The molasses takes on
disk are kept as they are; the takes before them are in
`esoterica/library/_superseded/` (`-speed-0.85`, `-speed-0.7-ignored`).
**Decided (operator, 2026-11-03): per paragraph, plus ellipses.** "One per
paragraph is better - I think one per sentence risks feeling disjointed", and
"Ellipses make sense" (v4 reads punctuation as pacing). Voicing now puts the tag
before every paragraph that has words (`voicing.with_delivery`, constant
`DELIVERY_EACH = "paragraph"`; a cue-only paragraph like `[pause]` gets none).
The placement is in the piece-cache key and in each sidecar
(`delivery_each`), so the molasses takes, voiced with one tag per request, now
show as stale ("its delivery tag was placed once per request"). Estimate for
the re-voice: Lantern 7,886, Northern 11,682 characters (before any ellipses
are added to the scripts). Not spent yet; waiting for the operator's go.

**Ellipses probe (2026-11-03, 1,227 characters).** The first four worded
paragraphs of Lantern p01 with ellipses added by hand and the tag before each
paragraph, Harriet, one request. Speaking rate against the full p01 takes
(same voice, same kind of text): speech only (silence removed) 3.88 words/s vs
4.00-4.14 for every earlier take (~3-6% slower); overall 2.66 vs 2.73-2.78
words/s (~4%). The numbers say the levers are small on this voice; the
operator's ear decides. File: scratchpad `ellipses/lantern-e-paragraph-ellipses.wav`
(rendered with room character and pause_stretch 2.2; `.raw.wav` beside it).

**Final re-voice (operator: "It starts really slow, then speeds up. I think this
is as good as we'll get for now and am ok with just proceeding").** Ellipses
added by hand through both scripts (60 in Lantern, 90 in Northern Tide, weighted
toward paragraph ends, where the speed-up is heard), tag before every paragraph,
19,913 characters. Overall rate, raw takes: Lantern 2.80 -> 2.70 words/s (8.5
min raw, 11.0 rendered); Northern 2.69 -> 2.61 (12.3 raw, 16.0 rendered). The
previous takes are in `_superseded/<id>-molasses-start/`. A naturally slow voice
is the remaining lever, untried. ElevenLabs total now about 102,526 of 265,000.

**Placeholders** (Claude's, tune by ear):

| Name | Value | Where |
|---|---|---|
| `PAUSE_THRESHOLD_DB` | -45 dBFS (20 ms RMS) | `voicing.py`: below this is a pause (raw takes are at -24 dB speech RMS) |
| `PAUSE_MIN_S` | 0.12 s | `voicing.py`: shorter silences are gaps inside words, not stretched |
| `PAUSE_WIN_S` | 0.02 s | `voicing.py`: the analysis frame |
| `pause_stretch` | 2.2 | both scripts: the operator's "much slower" test version |
| `speed` | 0.7 | both scripts: ElevenLabs' floor; **no effect on `eleven_v4`** |

### Provider facts (read from live docs and free APIs, 2026-11-03)

- **ElevenLabs:** `POST /v1/text-to-speech/{voice_id}`, header `xi-api-key`; model
  `eleven_v4` ("most emotive"; 10,000-char request limit; French; no style or
  speaker boost; no SSML breaks, pauses come from ellipses; **ignores the
  `speed` voice setting**, measured 2026-11-03, see "Pace" above); inline audio tags
  like `[whispers]`, `[exhales]`; `pcm_44100` output needs the Pro tier, so
  `pcm_24000` is requested and resampled; $0.08 per 1,000 characters.
- **Cartesia:** `POST /tts/bytes`, `Cartesia-Version: 2026-08-14`; model
  `sonic-3.6`; `generation_config` speed 0.6-1.5, emotion (English only);
  inline `<break time="1s"/>`; no whisper or breath control; native
  `pcm_f32le` at 44.1 kHz; the docs give ~1 credit per character and no USD
  rate; no documented per-request limit.
- The full source list is in `.superpowers/sdd/2026-11-03-esoterica-8a-starter-set/task-3-report.md`.

### Every placeholder, by name and value

All Claude's choices, none heard yet beyond the audition; tune by ear. The
characters can be re-tuned for free because the raw takes are kept.

| Name | Value | Where |
|---|---|---|
| Loudness target | -24 dBFS RMS over 20 ms frames above -50 dBFS | `voicing.py` `TARGET_RMS_DB`, `GATE_DB`, `FRAME_S` |
| Peak ceiling | -3 dBFS, smooth limiter (5 ms window) | `voicing.py` `PEAK_DB`, `LIMIT_WINDOW_S` |
| Chunk join | 250 ms silence, 10 ms raised-cosine edges | `voicing.py` `CHUNK_GAP_S`, `EDGE_S` |
| `[long pause]` | 3.0 s of real silence (split, never sent) | `voicing.py` `LONG_PAUSE_S` |
| Shuffle gaps | uniform 2-3 s, seeded `default_rng([crc32(id), passage_index])` | `voicing.py` `SHUFFLE_GAP_S` |
| ElevenLabs settings | stability 0.5, similarity_boost 0.75, speed 0.85; `pcm_24000` resampled to 44.1 kHz | `voices.yaml`, `providers.py` |
| Cartesia settings | speed 0.8, emotion `calm` (English only); price $0.00005/char (unverified); `max_chars` 1000 (docs state none) | `voices.yaml` |
| Request timeout | connect 10 s, read 300 s | `providers.py` `TIMEOUT` |
| Audition excerpt | ~120 spoken words cut at a sentence end (91-145 in practice); shuffles 16 images | `cli.py` `AUDITION_WORDS`, `AUDITION_SHUFFLE_LINES` |
| Cue translation | see the voicing table below | `providers.py` |
| Character recipes | tape, room, oldmic, hum, clean: see the character table below (room: custom IR, -60 dB at ~0.38 s, ~15% wet; oldmic: 150-5000 Hz, tanh 1.3, RMS matched; hum: 50 Hz + harmonics at -55 dBFS, 5 ms fade-in) | `character.py` |
| Character seed | crc32(script id), passage index | `voicing.py` |
| Render edge fade | 10 ms raised cosine at both ends of every rendered `pNN.wav`, after the character, before normalising (tape hiss and hum would otherwise start/stop dead) | `voicing.py` `RENDER_EDGE_S` |
| Piece cache key | first 10 hex of sha256(provider, model, voice_id, language, piece text) in `pNN.sMM.<key>.seg.wav` | `voicing.py` `piece_cache` |
| FileSource fades | 50 ms raised-cosine fade-out over the file's last 50 ms (silence after); 5 ms raised-cosine fade-in at sample 0 (the 5 ms is invented) | `FileSource.swift` `fadeSeconds`, `fadeInSeconds` |

### Known follow-ups

- **Chimes should sit quieter under a voice.** A spoken word is more
  attention-grabbing than the scenes; mixing the scene levels under it is the
  planner's job, which does not exist yet. Nothing in 8a sets relative levels.
- **The link-import door is open.** `nightctl audition voice --file` plays any
  mono/stereo WAV, and a manifest can describe any audio, so a pasted-link
  import (podcasts, audiobooks, speeches) only needs a downloader and a manifest
  writer. Not built; the spec still calls it a later door.
- **Animal-language lessons are parked** (STOP 1, 2026-11-03). The operator
  offered an animal as one direction for the lesson language: birds, whales, or
  "a non-specific animal that just growls, roars, and makes other guttural
  inarticulate noises" (not a dog or cat). Text-to-speech can't make those
  sounds convincingly; building it means ElevenLabs' sound-effects endpoint and a
  new pipeline step that places each generated call after the teacher's line. Of
  the three directions, reversed English and a repeated nonsense word became
  `lessons/backward-lesson-one.md` and `lessons/mubba-lesson-one.md`.
- **The listening judgement is outstanding.** The operator has heard the
  audition (the voices) but not the voiced recordings with their characters,
  nor them through the engine. `esoterica/listening.sh` makes that set (see
  below). Everything in the tables above, the characters especially, was
  chosen by measurement and reasoning, not by ear.

### Final review fixes (2026-11-03)

The whole-branch review found the voicing safe for money in the happy path but
not around the edges. What changed, and why it matters:

- **Resume at the request.** `voicing._voice_pieces` caches every provider
  response as `pNN.sMM.<key>.seg.wav` (atomic, dot-prefixed temp, then rename)
  before the next request; MM is the 1-based piece number, `<key>` 10 hex of
  sha256(provider, model, voice_id, language, piece text), so a cache can only
  be reused for exactly the request it answered. When every piece is cached the
  raw take is assembled (byte-identical to an uninterrupted run, tested), written,
  and that passage's caches are deleted. A complete `pNN.raw.wav` stays
  authoritative and is never re-sent. One planner (`passage_pieces`,
  `shuffle_pieces`) drives voicing, `estimate`, `voice`'s remaining count and the
  audition count, so the estimate is the exact request list, and pieces already
  cached are not counted.
- **Stale-script guard.** Each raw take has a sidecar `pNN.raw.json`: index,
  `text_sha256`, provider, model, voice_id, `backfilled`. The hash is of the
  passage's neutral text as the script holds it (`Passage.text`: cues included,
  intensity comment not), the text voicing chunks and sends; cue translation is
  code, so it is not hashed. The sidecar is written just before the take's first
  request. `voice` (before any estimate or spend) and `render` (before writing
  anything) compare every take with the current script and refuse, naming the
  passages, when its text changed, when an inserted or removed passage shifted
  the numbering, or when a take has no passage any more. The fix is
  `sleepmix esoterica voice <id> --revoice p02` (one script id only; repeatable
  or comma-separated): it prints the estimate and the files it would delete, and
  only with `--yes` deletes the named takes' raw, sidecar, piece caches, rendered
  file and `recording.json` (which describes the old takes; `made_at` is lost),
  then voices them. Naming a passage that is not stale is refused, so a good paid
  take cannot be thrown away by a typo. `render --all` refuses a stale recording
  with a message, carries on with the rest and exits 1 at the end.
- **Backfill (one-off, free).** The four voiced recordings predate sidecars. A
  take with no sidecar whose `recording.json` `text` equals the passage's current
  `spoken_text` counts as current, and `render` (or `voice`) writes its sidecar
  with `"backfilled": true` and the voice from `voice.json`. Weakness, accepted
  because it only applies once: manifest text has cues stripped, so a cue-only
  edit made before the backfill would go unseen. Run on the real library on
  2026-11-03 after checking all four manifests equal the current scripts: 17
  sidecars written, all 17 `*.raw.wav` byte-identical before and after (sha256).
- **`render --all` on a partly voiced recording** prints "skipped, partially
  voiced (missing p02.raw.wav, …)" and carries on; `render <id>` still fails
  clearly.
- **An unused `voice.json` binds nothing.** If a recording directory has a
  `voice.json` but no paid audio (no raw take, no piece cache: the first request
  never succeeded), the next `voice` rewrites it instead of refusing a different
  voice. Raw takes and caches are found by exact-name helpers (`raw_takes`,
  `segment_caches`), never a `p*.raw.wav` glob.
- **Rendered files fade at both ends.** `render_character` applies a 10 ms
  raised-cosine fade (`RENDER_EDGE_S`) after the character and before
  normalising; tape hiss had stopped dead on the last sample. Tested on the
  file's last samples.
- **The manifest records the character tuning.** `recording.json` gains
  `character_params`: the recipe constants of the script's kind by name (from
  `character.character_params`) plus `render_edge_s`. A retune rewrites the
  manifest (keeping `made_at`). The field is defaulted, so `format_version` stays
  1 and older manifests still read (nothing outside Python reads the manifest).
- **Audition files know their voice.** Each `esoterica/audition/<slot>/<provider>-<voice>.wav`
  has a sidecar `<provider>-<voice>.json` (provider, model, voice_id, name),
  written before its request. A file whose sidecar is missing or names another
  voice id or model is counted again and replaced with `--yes`; `index.md` shows
  each voice id and marks such files stale. Filenames did not change, so the 40
  paid audition files kept their names; their sidecars were backfilled once from
  `voices.yaml` (the `candidates:` block is unchanged since c72a1a5, the commit
  before the audition ran), all 40 WAVs byte-identical.
- **One estimator.** `cost.py` (`estimate`, `CostEstimate`) counted cue-stripped
  text and only its tests used it; deleted.
- **Tests never see a key.** The autouse fixture also unsets
  `ELEVENLABS_API_KEY` and `CARTESIA_API_KEY` (pipenv loads `.env` into the
  environment, so this mattered).
- **Decision: manifests live with the audio, git-ignored.** `recording.json`,
  the take sidecars and all audio sit in `esoterica/library/`, which is
  git-ignored. The audio is large and binary; the manifest is derived (a free
  `render` re-makes it from the raw takes and the committed scripts), so
  committing it would only add churn. The cost: the library exists on one
  machine; a lost disk means re-voicing (only the paid takes are irreplaceable).

### The listening set

`esoterica/listening.sh` (free: no provider, no key) takes passage 1 of every
recording that has a `recording.json` (unvoiced ones are skipped) and writes
into the git-ignored `esoterica/listening/`: `<id>-plain.wav` (the rendered
`p01.wav`, source character included; not the raw provider take), `<id>-near.wav` (`nightctl audition voice --distance 0`, clear through
the AM channel) and `<id>-far.wav` (`--distance 0.6 --fragmentation 0.3`). The
near and far files are the first 90 s (`SECONDS_PER_FILE` overrides). Its
output includes RMS, peak and spectral centroid for each file; the plain files
read below -24 dB because that figure is over the whole file, silences included,
while the -24 target is over speech frames only. Listen near and far and ask:
does the voice still carry? does the character read as "found"? is the far
version a dream or just an annoyance?

### Source character (Plan 8a Task 4): built

`sleepmix/esoterica/character.py`: `apply_character(x, sr, kind, seed)`. Each script's
`source_character` is a light "where was this found" texture.

**Raw / render split, and why.** Paid takes must never be overwritten by a placeholder
effect. `voice` writes each provider take (loudness-normalised) to `pNN.raw.wav` and
never touches it again; resumability, `voice.json`, the resume guard and the cost
estimate (`_remaining`) all look at raw takes and piece caches only (see "Final
review fixes" below). A free, re-runnable step
(`voicing.render_character`, CLI `sleepmix esoterica render <id>|--all`) applies the
character, re-normalises to -24 dBFS speech RMS / -3 dBFS peak and atomically rewrites
`pNN.wav` (what the manifest points at). Seed is crc32 of (script id, passage index), so a
render is deterministic. Character can therefore be re-tuned by ear at no cost. Rendered
files alone never imply a paid voice. A library voiced before this split (bare `pNN.wav`,
no raws) would need re-voicing; none exists yet.

**Placeholders (all in `character.py`, tune by ear):**

| Kind | Recipe |
|---|---|
| tape | wow 0.4 Hz +-3 cents; flutter 7 Hz +-1 cent; hiss -52 dBFS RMS; 2nd-order 7 kHz lowpass |
| room | dry voice plus a synthetic tail (own impulse response, not `sleepmix.effects`: pedalboard cannot go below ~0.6 s to -60 dB and its wet/dry gains are not energy-true): flat-spectrum random-phase noise, -60 dB at 0.4 s (measured 0.38 s), 5 kHz one-pole damping, tail = 15% of output energy across 100-4000 Hz (measured 14.8%); no RMS matching (mean +0.6 dB; `normalise` sets level) |
| oldmic | tanh drive 1.3 (`tanh(1.3x)/1.3`), 2nd-order 150-5000 Hz bandpass; RMS matched to input (the band takes a few dB off broadband sound; `normalise` sets final level) |
| hum | 50 Hz + 2nd + 3rd harmonics, each -55 dBFS, random phase, 5 ms fade-in (and, like every kind, the 10 ms render edge fade at both ends) |
| clean | identity |

### Voicing (Plan 8a Task 3): built and run

`sleepmix esoterica estimate | audition | voice` in `sleepmix/esoterica/`
(`providers.py`, `voicing.py`, `cli.py`) with `esoterica/voices.yaml`. Provider
facts were read from the live docs and the providers' free listing APIs on
2026-11-03 (sources in `.superpowers/sdd/2026-11-03-esoterica-8a-starter-set/task-3-report.md`).
The audition ran at STOP 2 and `voices.yaml` `chosen:` is filled (see above);
`voice` refuses to run for a slot with no chosen voice.

**Voicing placeholders and cue translation** (Claude's choices, to tune by ear; the summary table above lists them too):

| Name | Value | Where |
|---|---|---|
| ElevenLabs model | `eleven_v4` | voices.yaml |
| ElevenLabs stability | 0.5 (valid whether v4 takes 0/0.5/1 steps or a range) | voices.yaml |
| ElevenLabs similarity_boost | 0.75 (provider default) | voices.yaml |
| ElevenLabs speed | 0.85 (docs floor 0.7) | voices.yaml |
| ElevenLabs output | `pcm_24000`, resampled to 44.1 kHz (44.1 kHz PCM needs the Pro tier) | providers.py |
| Cartesia model | `sonic-3.6` | voices.yaml |
| Cartesia speed | 0.8 | voices.yaml |
| Cartesia emotion | `calm` (English only; omitted for French) | voices.yaml |
| Cartesia max_chars | 1000 (docs state no limit) | voices.yaml |
| Cartesia price_per_char | $0.00005 (unverified: docs give ~1 credit/char; $/credit is third-party) | voices.yaml |
| Chunk gap | 250 ms | voicing.py `CHUNK_GAP_S` |
| Chunk edge fade | 10 ms raised cosine | voicing.py `EDGE_S` |
| `[long pause]` | 3.0 s of real silence (split, not sent) | voicing.py `LONG_PAUSE_S` |
| Shuffle gaps | uniform 2–3 s, seeded crc32(id) + passage index | voicing.py |
| Loudness target | -24 dBFS RMS over 20 ms frames above -50 dBFS | voicing.py |
| Peak ceiling | -3 dBFS, smooth limiter (5 ms window) | voicing.py |
| Audition excerpt | ~120 spoken words, cut at a sentence end; shuffles 16 images | cli.py |
| `[pause]` | ElevenLabs `…`; Cartesia `<break time="1s"/>` | providers.py |
| `[breath]` | ElevenLabs `[exhales]`; Cartesia stripped | providers.py |
| `[softly]` | ElevenLabs `[softly]`; Cartesia stripped | providers.py |
| `[whisper]` | ElevenLabs `[whispers]`; Cartesia stripped | providers.py |
| `[laughs quietly]` | ElevenLabs `[laughs]`; Cartesia `[laughter]` | providers.py |

**Known gaps:**
- Library (shared) ElevenLabs voices among the candidates do not appear in
  `GET /v1/voices/{id}` for this account, but the audition and the voicing
  worked with them by id (no add needed).
- The API key lacks `user_read`, so the subscription tier could not be read.
- **Resume is per request, not per passage** (final review). Earlier this
  section said every passage was "resumable exactly"; that was false: a
  passage's pieces were held in memory and written only when all succeeded, so
  a failure re-billed the earlier pieces. Now each provider response is cached
  as `pNN.sMM.<key>.seg.wav` the moment it arrives; a re-run sends only the
  failed piece onwards. What is still paid twice: a request that timed out or
  failed after the provider had already billed it (next bullet).
- Shuffle French detection is an article heuristic, not a language model.
- **A timed-out request may still be billed.** The read timeout is 300 s; if a
  provider finishes a generation after the client gave up, it may charge for
  it, and the rerun pays again for that passage.
- **Cartesia price and limit are placeholders:** $0.00005/char (third-party
  plan pricing; Cartesia's docs give only ~1 credit/char) and a 1000-character
  request limit (Cartesia documents none).
- **ElevenLabs audio is requested as 24 kHz PCM and resampled to 44.1 kHz,**
  because 44.1 kHz PCM output needs the Pro tier.
- **Estimates count what is sent:** characters after each provider's cue
  translation (Cartesia's `<break time="1s"/>` is longer than `[pause]`), with
  `[long pause]` excluded because it is never sent.
- **Resume never mixes voices:** each recording directory gets a `voice.json`
  (provider, model, voice_id) before its first request; `voice` refuses, before
  spending, to resume a recording with a different voice, or one whose
  passages have no record of their voice. A `voice.json` with no paid audio
  beside it binds nothing (final review).
- ElevenLabs `language_code` is sent only for French (the API reference says
  an unsupported code is ignored but lists no models that accept it).

## Plan 7a: two scenes through the channel

**Status (2026-11-02): built and tested; not yet listened to.** Plan 7a is the
first slice of Plan 7: prove the sound before building anything around it. It
is a Swift package at `swift/` that renders two generated scenes (at the time
rich round chimes, since rebuilt as soft-mallet chimes in Plan 7b, and pixellated
waves) through the AM channel, warps them along the four
dimensions (distance, slowness, fragmentation, proportion; Plan 7b adds the
three tone dials ring, softness and vibrato alongside them), and lets the
operator audition any combination from a Mac command line. There is no app, no
planner, no voice layer, no night log, and no engine that runs in real time yet.
The slice exists so the operator can hear whether the character is right before
the machinery that schedules it gets built, and **the milestone is not done
when the tests pass; it is done when they have listened** (see "The listening
judgement is outstanding" below).

**What shipped** (branch `feat/am-night`, plan
`docs/superpowers/plans/2026-11-02-am-night-7a-two-scenes-through-the-channel.md`):

- **`NightPlan`**: pure Swift, imports only Foundation. `NightRandom` (SplitMix64
  over a `(seed, stream, index)` key; the one specified generator),
  `WarpDepth` (four values in 0...1), `ChannelSettings` (clamped; `.early` is
  the one preset), `Curve` (a value as a function of the night's second),
  `SceneKind`. A test fails the build if any file in it imports anything but
  Foundation, and another does the same for `NightDSP` against platform
  frameworks.
- **`NightDSP`**: Biquad, a small Schroeder `Reverb`, `Envelope`, a float32 mono
  `WAVWriter`, and `Analysis` (FFT-based centroid, band ratios, RMS, peak) as
  primitives; `ChimesScene` and `WavesScene`; `Fragmenter` and `Distance`; the
  `AMChannel`; and `NightFactory`, the single place the chain is assembled.
- **`NightCLI` and `nightctl`**: `nightctl scenes` and `nightctl audition
  <scene> ...` (options: `--seconds --at --seed --distance --slowness
  --fragmentation --proportion --no-channel --sample-rate --out --play`).
  Validation rejects out-of-range input with a message and exit 64 before any
  render or write.
- **The listening set**: `swift/listening/render.sh` regenerates eight 60-second
  WAVs (seed 1) and `measurements.txt`. The WAVs and the measurements file are
  git-ignored; the script is the record.
- **Docs**: `swift/README.md`, the section "The Swift engine (Plans 7a and 7b)" in
  `docs/architecture.md`, and this section.

**Test count: 80 tests, all passing** with `cd swift && swift test -c release`
(NightPlan 8, NightDSP 68 in 6 suites, NightCLI 4; parameterised tests count
once per function, not per case). Release mode matters: per-sample DSP in debug
is 10 to 50 times slower and the suite renders minutes of audio. These are pure
unit tests; there is no database, so the standing test-database rule has
nothing to apply to here.

### The measurement table

Produced by `swift/listening/render.sh`: seed 1, 60 s, 44.1 kHz. "plain" is
warp 0 through the channel; "mid" is `--distance 0.5 --slowness 0.5`; "far" is
`--distance 1 --slowness 1 --fragmentation 0.6 --proportion 0.8`; "no channel"
is plain with `--no-channel`. Levels are after the master guard. **The chimes
rows are the 7a bells, superseded by Plan 7b; the waves rows stand.**

| File | RMS (dB) | Peak (dBFS) | Centroid (Hz) |
|---|---|---|---|
| `chimes-plain.wav` (bells, superseded by Plan 7b) | -26.3 | -14.0 | 656 |
| `chimes-mid.wav` (bells, superseded by Plan 7b) | -32.7 | -16.1 | 692 |
| `chimes-far.wav` (bells, superseded by Plan 7b) | -30.4 | -17.3 | 924 |
| `chimes-nochannel.wav` (bells, superseded by Plan 7b) | -21.1 | -7.6 | 507 |
| `waves-plain.wav` | -36.8 | -20.4 | 977 |
| `waves-mid.wav` | -37.4 | -20.1 | 939 |
| `waves-far.wav` | -36.6 | -17.8 | 1033 |
| `waves-nochannel.wav` | -32.5 | -14.9 | 339 |

These are measurements, not verdicts. They say the files are finite, bounded,
and different from each other in the directions the design intended on some
axes and not on others (the "far" chimes (bells, superseded by Plan 7b) have a higher centroid than the plain
ones, which looks like the reverse of what "further away" suggests. It was
checked by rendering the same far warp with `--no-channel` (seed 1, 60 s):
chimes go from a centroid of 507 Hz plain to 438 Hz far (363 Hz with distance
1 alone), and waves from 339 Hz plain to 162 Hz far (165 Hz with distance 1
alone). So distance does darken the content, as designed; the brighter
reading *with* the channel (chimes 656 to 924 Hz) is consistent with the
channel's fixed noise floor: its hiss and crackle stay put while the content
falls (chimes RMS drops from -26.3 to -30.4 dB), so the floor's share of the
spectrum grows. The stronger evidence is at fragmentation 1: the chimes'
centroid is 1854 Hz with the channel against 586 Hz without, and the waves'
is 1891 Hz against 310 Hz, because the noise floor fills the silent cells.
That matters for the planner: as content recedes, the channel's noise has to
come down with it, or the far end of the night gets hissier and brighter
instead of further away. The waves' centroid also rises with the channel
(939 to 1033 Hz), but their with-channel RMS does not fall, so the
"floor outgrows the content" explanation is not established for them.
Nobody has listened to either,
and these are centroids, not a judgement of how it sounds. Whether any of it is a warm
memory of a train, or merely a quiet hum, is not something a number can say.
Two things the table does show plainly: the channel takes about 5 dB off the
bell chimes' (superseded by Plan 7b) RMS and 6 dB off the peak at plain warp, and it moves waves' centroid
from 339 Hz to 977 Hz (the channel removes the body below 180 Hz and adds hiss
and saturation harmonics, so "the channel makes it brighter" is the truth even
though "the channel makes it narrower" is also the truth).

### Before the planner moves anything

Preconditions found by the final whole-branch review of Plan 7a. None is a
bug in the shipped audition tool (it holds the warp constant); each becomes
one the moment a planner moves the controls.

- **I1, the warp is not level-neutral.** Measured over 120 s and 3 seeds:
  proportion 1 raises waves by +4 dB peak and +2.3 dB RMS, and chimes (bells, superseded by Plan 7b) by +2 dB
  peak; slowness 1 raises waves by up to +3.5 dB peak; distance 1 raises the bell chimes (superseded by Plan 7b)
  seed 3 without the channel from -19.5 to -17.0 dB RMS and from -5.0 to -3.5
  dBFS peak; the combined far warp raises waves without the channel from -15.9
  to -8.3 dBFS peak. Causes: the proportion rule (+6 dB favoured, -12 dB
  receded) does not preserve power; slower waves overlap more; and reverb
  build-up exceeds the direct-sound loss. The spec's ratchet says the free
  controls must not make the night louder. The fix belongs to the planner:
  power-preserving proportion, reverb-compensated distance, or a per-source
  level stage under the ratchet.
  **Plan 7b update (final review).** Distance is still not level-neutral for
  the new scenes, and the warmth is the worst case. Measured over 120 s with
  `--no-channel`, `--distance 1` against plain (the warmth seed 3 figures
  were re-measured and reproduce): warmth seed 3 rises +3.8 dB RMS (-23.6 to
  -19.8) and +5.7 dB peak (-10.5 to -4.8 dBFS, past the master guard's -6 dBFS
  knee); warmth seed 1 falls -4.8 dB RMS; chimes seed 3 falls -1.4 dB RMS but
  peaks +2.3 dB (-6.1 to -3.8 dBFS). The likely cause is Distance's per-seed
  reverb resonating with the warmth's sustained low partials (44 to 130 Hz),
  with reverb decay up to 4.5 s at distance 1 (not isolated further). **The
  planner needs a distance level-compensation stage**, and it has to be
  per-seed-aware or measured, since the sign of the change differs between
  seeds. What 7b did fix for the new scenes: slowness 1 lowers the chimes by
  4 to 5 dB RMS and leaves the warmth about unchanged; proportion 1 is neutral
  (within 0.1 dB) for both, because it is power-preserving. The waves keep the
  old I1 behaviour above.
- **Ring ramp rate (Plan 7b).** A step in ring from 1 to 0 gives about +1.4 dB
  in theory, peaking about 1 s after the step. Measured over 40 seeds,
  windows at 300 to 305 s average about +0.9 dB with peaks up to +1.7 dB.
  Ramping ring over a few tau (tau is up to 4.2 s) removes it. The spec's
  direction (ring lengthening into the night) gives a dip, not a rise, so this
  matters only for a planner that shortens ring.
- **I2, per-source seeds.** `NightFactory` derives component seeds as
  `hash(seed, i, 0)`. In a mix of several sources, every source's channel would
  get identical hiss and crackle, and every Fragmenter would drop out in the
  same cells. Use `hash(seed, component, sourceIndex)`.
- **I3, the crackle clamp.** `ChannelSettings` allows crackle up to -20 dBFS
  whatever the hiss level, and crackle continues through the fragmenter's
  silent cells. Make it structural, like the octave rule: crackle <= hiss - 6 dB.
- **M5, constant-settings assumptions.** On a seek, Distance and AMChannel
  start their glides at the target, which the 6 s lead-in settles to about e^-3
  of the lag under a moving curve. The waves' hold grid re-latches once per
  256-frame block when the rate changes. There is no test with a moving curve
  for the scenes or Distance; the first planner test should seek into a moving
  warp.
- **M6, Distance's lowpass is unconnected to the channel's high corner.** At
  distance 0 it sits at 8000 Hz, and the spec requires distance's lowpass never
  to exceed the brightness ceiling.
- **M7, the factory renders offline only.** The app needs a streaming
  `NightGraph.render(into:)` with the same chain and guard, which `audition`
  should wrap, to keep the one-factory rule.
- **Cleanups for the planner milestone:** make `Distance.cornerHz` internal,
  and sanitise `startSecond` in Distance and Fragmenter like the scenes do.
- **Test note (final review):** `everyCornerIsSafe` cannot fail without the
  master guard at present: unguarded 30 s renders from second 600 peak at 0.54
  at most, below the guard's knee. It is a backstop contract (peak <= ceiling),
  not evidence the guard is exercised; the guard's own unit tests cover that.


### Every placeholder, by component

**Every number below is invented or interpreted and none has been heard.**
Values marked *(brief)* came from the plan; the rest were chosen by an
implementer to make the brief's sentence into code, and are named in the code
under a labelled constants block (`// MARK: - Invented values` or `// Invented`).
All of it is a placeholder in the user's sense: record it, don't forget it,
expect to retune it by ear. File paths are under `swift/Sources/`.

**The master guard and factory** (`NightDSP/NightFactory.swift`):
lead-in 6 s (a seek starts every component 6 s early and discards that much;
it is at least the 4.5 s reverb tail plus filter settling); render block 4096
frames; guard knee -6 dBFS (0.5011872); guard ceiling -1 dBFS (0.8912509),
`k + (c-k)·tanh((|x|-k)/(c-k))` above the knee, unity below, continuous in
value and slope, NaN to 0; component seeds are `hash(seed, 0..3, 0)` for scene,
fragmenter, distance, channel; the tool's defaults are 60 s, seed 1, 44100 Hz;
`nightctl` accepts a sample rate of 8000 to 192000 and a length up to 3600 s.
The warp and the channel settings are `Curve.constant`: the tool has no way
yet to vary them over time. The channel preset is `.early`.

**Channel preset `.early`** (`NightPlan/ChannelSettings.swift`): low corner
180 Hz, high corner 4500 Hz, hiss -48 dB, crackle -54 dB, fade depth 0.25,
fade rate 0.05 Hz, squash 0.5. The clamps are: low 40...1000 Hz, high
800...8000 Hz (always at least an octave above low, by raising the high
corner), hiss and crackle -96...-20 dB, depth 0...1, rate 0.005...1 Hz, squash
0...1. `.early` is the only preset; the later-night presets don't exist yet.

**Chimes: superseded by Plan 7b (kept as history).** The bell recipe
described in this paragraph was removed in 7b; see "Plan 7b" for what the
chimes are now. Only the grid values (cell, offset, density, pitch set, root
range, lookback) carried over.

**Chimes (the 7a bells)** (`NightDSP/Scenes/ChimesScene.swift`):
*(brief)* cells 2.2 s; a strike exists when `unit < 0.6/(1+2·slowness)` and
sits 0...1.6 s into its cell; slowness is read once at birth; the pitch is a
two-octave major-pentatonic degree `[0,2,4,7,9,12,14,16,19,21]` over a
per-seed root, lowered by 3 semitones at slowness 1; the strike is bandpassed
noise with attack 0.02 s and decay 0.08 s; body partials at ratios
`[1, 2, 2.76, 4.07]` with decays `[6, 3, 2, 1.2]·(1+2s)` seconds and amps
`[1, 0.5, 0.35, 0.2]`; bloom with attack 1.5 s and decay `12·(1+s)` s;
beating pair at ±0.35 Hz with decay 8 s; the favoured element in a strike gets
+6·p dB and the others -12·p dB; lookback 60 s. *Invented:* root log-uniform
over 196...392 Hz; mallet band centre 2× the strike's fundamental, capped at
2500 Hz, Q 1.2; strike level 0.3; mallet noise length 0.02 + 12·0.08 = 0.98 s;
body attack 0.02 s; bloom amps `[0.35, 0.25]` (fundamental and an octave
below); beat attack 0.3 s, beat amps `[0.2, 0.2]`; an element ends 7 decay
constants after its attack (-61 dB); **a hard cap of 58 s on any element's
life, with a raised-cosine fade to true zero over its last `min(4 s, 25% of its
life)`**; recurrences restart every 256 frames on an absolute grid; **master
gain 0.1**; random streams 0 (root), 1 (existence), 2 (offset), 3 (degree),
4 (favoured element), 5 (mallet noise).

**Waves** (`NightDSP/Scenes/WavesScene.swift`, `Scenes/Proportion.swift`):
*(brief)* a wave is born every 6 s and exists when `unit < 0.85/(1+slowness)`;
its length is `(7 + 5·unit)·(1+slowness)` s; one shared noise stream; swell
lowpass 400 Hz, break bandpass 800...2500 Hz, wash highpass 1500 Hz; swell
rises over the first 45%, break peaks at 55%, wash fills the last 50%;
pixellation holds at `5512·(1 - 0.4·slowness)` Hz and quantises to 7 bits, then
a 4 kHz lowpass; streams 11 (existence), 12 (length), 13 (noise). *Invented:*
favoured-element stream 14; break rises from 30% and is gone by 85%; swell
falls with a raised cosine from 45% to 100%; wash attack 5%, decay time
constant 15%, closing fade over the last 10% of the wave's length; element
levels `[1.0, 0.6, 0.35]` (swell, break, wash) before proportion; each filtered
band scaled to RMS 0.25 so the normalised signal sits about 4σ inside ±1; the
break band's Q is its geometric centre (about 1414 Hz) over its 1700 Hz
bandwidth; mid-tread 127-level quantiser; the hold rate is read once per
256-frame absolute block; noise-gain impulse of 16384 frames; lookback 24 s
(derived: (7+5)·2); **master gain 0.13**, derived rather than guessed:
the analytic worst-case envelope (6.147 at gain 1) times the output lowpass's
L1 norm (about 1.104) times gain must stay at or under 0.9, giving 0.1326 and
a proven bound of 0.882 (-1.09 dBFS), with the bound's tightness itself tested.
The favoured/receded values (+6 dB / -12 dB) live in `Proportion.swift` and are
shared by both scenes.

**Distance** (`NightDSP/Warp/Distance.swift`): *(brief)* the depth is read
every 512 frames and glided with a one-pole smoother whose time constant is 2 s;
lowpass corner `8000·(400/8000)^d` Hz; direct gain `1 - 0.8d`; reverb send
`0.15 + 0.7d`; reverb decay `1.2 + 3.3d` s. *Invented:* the lowpass Q 0.7071;
the reverb is fed the post-filter signal and added to the filtered direct; the
reverb seed is `seed ^ 0xD157`; per-sample linear interpolation between block
values, which lags the smoother by one block.

**Reverb** (`NightDSP/Primitives/Reverb.swift`; a Schroeder reverb with no
ambition): comb delays `[29.7, 37.1, 41.1, 43.7]` ms and allpass delays
`[5.0, 1.7]` ms (in seconds, so they scale with the sample rate), each comb
jittered ±5% by the seed (stream `0x5265`); RT60-derived feedback; comb damping
`0.7·out + 0.3·previous`; comb mix 0.25; allpass gain 0.5; default decay 2 s
before Distance overrides it. These are the arbitrary values of a first
reverb, not a considered room.

**Fragmenter** (`NightDSP/Warp/Fragmenter.swift`): *(brief)* cells of 3 s; a
cell is present when `unit(stream 21) >= 0.7·fragmentation`, so fragmentation 1
drops 70% of cells; 0.4 s raised-cosine crossfade centred on each boundary.
*Invented:* the cell before the first is treated as cell 0.

**AM channel** (`NightDSP/Channel/AMChannel.swift`): *(brief)* settings read
every 512 frames and glided with the same 2 s one-pole as Distance; hiss
lowpassed at 6 kHz; crackle 40 grains a second, 3 to 8 ms each, level drawn
from crackle-6...crackle dB; fading noise on streams 31 (broadband) and 32
(selective); selective cut up to -9 dB, centre swept 600...2500 Hz; compressor
detector attack 50 ms, release 400 ms, threshold -24 dBFS, ratio `1 + 3·squash`;
band as a 2nd-order Butterworth highpass and a 4th-order lowpass (Qs 0.7071,
0.5412, 1.3066). *Invented:* hiss stream 33, grain streams 34 (offset), 35
(length), 36 (level), 37 (noise); the hiss level is the RMS of the lowpassed
hiss at injection, normalised through the 2nd-order Butterworth's equivalent
noise bandwidth (factor 1.1107); one grain per fixed 1/40 s slot at a jittered
offset, a full Hann envelope, noise inside the grain; the selective peaking
filter's Q 1.0 and its log-mapped centre (the same stream also sets its
depth); the fade is a raised-cosine interpolation between knots at integer
phase, with the phase integrated from `rate/sr` per frame; the compressor is a
hard-knee mean-square detector; **warmth is `tanh(drive·x)/drive` with
`drive = 1 + 2·squash`** (unity gain for quiet signals); a final clamp at ±1.
Corners glide in Hz, levels in dB.

**Test-only values** worth knowing about because they set what "passes" means
(all in `swift/Tests`): pixellation must change the energy above 2800 Hz by
more than 10%; a cold waves seek must land within -55 dB; the factory's seek
test requires -30 dB residual (measured about -149 dB, so the bar is very loose);
the distance test requires 20 dB less energy above 2 kHz at depth 1 (measured
37 dB); the channel's silent output must sit between -60 and -40 dB RMS
(measured -51 dB); crackle must stay at or under its level plus 1 dB end to
end (measured about 1.6 dB under); the corner-safety test uses a 0.95 tolerance.

### The rulings and why

These are the places the build went beyond or against the plan, with the
reasoning, because the reasoning is what is useful when the operator disagrees
with the result.

- **Warmth at unity small-signal gain.** The plan's `tanh(drive·x)/tanh(drive)`
  turned out to add 2.4 to 9.5 dB to quiet signals, which would have made
  `squash` a hidden loudness knob and quietly broken the spec's ratchet (the
  night's level only ever descends). The spec outranks the plan's formula.
  The cost: the channel is about 6 dB quieter than first built, and the ceiling
  for loud material is `1/drive` (a full-scale source reaches -9.5 dBFS at
  squash 1).
- **The crackle cap is tested end to end.** "Never pops" is a spec
  anti-goal, and the test the plan asked for could not fail against the defect
  it named (grains sit 10 dB under the hiss). A second test now feeds silence,
  silences the hiss and checks the output's peak against the crackle level.
- **The waves are peak-safe by bound, not by sampled seeds.** Sampling 20 seeds
  found a worst case within 2 dB of full scale; a bound derived from the shapes
  proved the true worst case was closer. Master gain went from 0.2 to 0.13.
- **Waves share one noise stream** (the plan's design). Overlapping waves are
  therefore the same noise under different envelopes, statistically equal to
  independent noise at the summed power but not independently distinct. The
  fix, a stream per wave, is deferred until someone listens and says
  overlapping waves sound like one wave twice.
- **The chimes' 58 s element cap (bells, superseded by Plan 7b; the cap itself
  carried over to the soft chimes as `min(7τ, 58 s)`).** The plan said the longest tail was 36 s; the
  bloom at full slowness decays over 24 s and is still at -21 dB at 60 s. The
  implementer capped life at 58 s with a 4 s fade so that seeks stay exact
  and nothing is cut. The slowest blooms lose their last whisper.
- **Bell chimes may peak near -2.6 dBFS before the channel at full proportion
  (superseded by Plan 7b: soft chimes are power-preserving and bounded at 0.8685).**
  The master guard owns peak safety, and a corner test checks the whole chain.
- **A discriminating pitch-drop test for the slow chimes.** The plan's test
  passed with the pitch drop removed (the density and decay changes alone moved
  the centroid). A test-visible `fundamental` function now pins 2^(-3/12).
- **A discriminating octave test for `ChannelSettings`**: the plan's fixture
  could not fail without the octave rule.
- **`channelOffIsBrighter` was replaced by `channelOffKeepsTheLowEnd`.** The
  plan's premise (a channel-free signal is brighter) was false, since the
  channel removes the low end and adds hiss and harmonics, which raises the
  centroid. The spec's intent is "narrow: no deep bass, no sparkle", and the top
  half of that is already guarded in the channel's own tests.
- **Work in place on `feat/am-night`, no worktree.** The tree was clean and the
  branch had been made for this.

### Known limitations and deferred items

**For the iPhone (real-time safety). None of these matter for the Mac tool, all
of them matter before anything runs on an audio thread:**

- **Chimes allocate a whole mallet per strike**: about 43,000 samples at voice
  creation, and about 1.2 million after a seek. It needs to be lazy or
  preallocated.
- **Waves keep N copies of three filters** (one set per live wave) and
  allocate at each wave's birth. A cold seek fast-forwards about ten million
  biquad steps. The three filters over the one shared noise stream could be
  global, which would also make the shared-noise question moot.
- **Per-sample `pow`, `log10`, `tanh` and hashing** in the AM channel (about
  two `pow`, one `log10`, two `tanh` and several hashes per sample) and in
  `Fragmenter.gain` (a warp lookup and a hash per sample). Grain parameters
  could be cached per slot, the fade knots per integer phase, the fragment gain
  per cell, `tanh(drive)` per block. Sixty seconds renders in a fraction of a
  second on this Mac, so this is a deferred cost and not a measured problem.
- **`Distance.cornerHz(at:)` replays the smoother from the start** (cost
  proportional to the seconds), which is fine for the cap logic it was built
  for but not something to call per sample.

**Level and loudness:**

- **The two scenes are not level-matched.** Plain waves peak about -15 dBFS
  and plain chimes about -6 dBFS before the channel (bells, superseded by Plan
  7b; the soft chimes also peak near -6 dBFS, median -6.1 over 600 s; the table's
  7a no-channel rows showed -14.9 and -7.6 over a 60 s sample). Whoever plans the night will
  need to balance them, or the planner will need a per-scene gain.
- **Squash is still coupled to loud-material level.** Raising squash
  lowers loud sources (down to -9.5 dBFS at squash 1 for a full-scale
  source). It never raises anything, so the ratchet's direction holds, but it
  is not a pure character control.
- **Plain waves are very bass-heavy before the channel**: a spectral centroid of
  339 Hz with seed 1 over 60 s (the `waves-nochannel.wav` row above). An
  earlier figure of about 114 Hz was an implementer's probe during the factory
  task (also waves, channel off; seeds and length not recorded, probably the
  10 s renders of `channelOffKeepsTheLowEnd`), so it is a different
  measurement of the same thing; centroids of a bass-dominated signal move a
  lot with the sample. The channel is doing a
  great deal of the work of making them audible as waves.

**For listening:**

- **Hiss and crackle fade with the signal** because they enter before the
  fade stage. Real AM noise rises as the signal fades. Probably wrong; nobody
  has heard it.
- **Crackle grains are quasi-periodic**: exactly one per 25 ms slot at a
  jittered offset, so exactly 40.0 per second, not a Poisson rain. Might be
  audible as a faint ticking pulse.
- **One stream drives both the selective fade's depth and its centre.**
  The deepest cuts always sit near 2500 Hz and shallow ones near 600 Hz.
  Decoupling them needs a third stream.
- **Waves share one noise stream** (see the rulings).
- **The pixellated waves have less energy above 2800 Hz than clean ones**
  (0.0167 against 0.0226 of the energy), because the sample-and-hold's droop
  outweighs the aliased images. "Pixellated" may not mean "gritty" the way
  the operator imagines.
- **Exactness of seeks, precisely, per component:**
  - *Chimes:* exact from a cold start (`seekIsExact`, `seekIsExactLateAndChunked`
    compare with `==`).
  - *Waves:* approximate cold, because the 4 kHz output lowpass is stateful
    and crosses waves (a cold seek measures about -63 dB relative,
    `coldSeekIsNearlyExact`). With the factory's 6 s lead-in it comes out
    bit-exact in every case tested (`seekWithLeadInIsExact`, `==`).
  - *Fragmenter:* exact (a pure function of the absolute frame).
  - *Distance:* approximate cold (filter, reverb tail and glide have state),
    settled by the lead-in. It has no seek test of its own; the factory's
    whole-chain test covers it.
  - *AM channel:* approximate cold (filters, compressor, glide), settled by the
    lead-in (`seekIsClose` measured -177 dB), and only for a *constant* fade
    rate: a varying rate before the seek point leaves the fade phase different.
  - *Whole chain through the factory:* about -149 dB residual against a longer
    render, for both scenes (`seekingMatchesALongerRender`).

**Test and tooling debts (minor):**

- Smaller ones left in place: a stray `print` in `distanceDarkensTheRoomToo`;
  `distanceZeroIsNearlyTransparent` is named as if it were transparent but
  allows +-2 dB; the master guard's slope tolerance is a loose 1e-2;
  `badInputWritesNothing` can't detect late validation (it never calls `run()`);
  `wavRoundTrip` doesn't check the RIFF and data sizes, bit depth, byte rate or
  block align; the processor variant of `seekLeadIn` is untested and has no
  bounds precondition; the reverb first-echo test window is tied to the current
  minimum delay; `NightPlanTests` has an unnecessary `@testable import`; the
  `elementGains` doc says "strike in cell" without checking that one is
  present; the chimes call `Envelope` per sample during the attack.

- The hash's golden value pins only `(0,0,0)`; there are no clamp tests for
  `ChannelSettings` levels, fade values, or `WarpDepth`'s setters.
- Several of the plan's tests cannot fail against the defect they name
  (`noClicksFromCrackle`, `bandIsNarrow`'s low-end check, `strikeAttackIsSoft`,
  `hourEightIsHealthy`, `everyCornerIsSafe` survives removing the master
  guard, `squashWarmsWithoutClipping` peaks at 0.33 against a bound of 1.0).
  Each has a stronger added test beside it; the weak ones are kept and not
  trusted.
- `silenceInHissOut`'s peak margin was thin (0.95 dB) and became 7.3 dB after
  the warmth change.
- No seek test with a time-varying warp curve; the peak bound for waves covers
  only the pixellated path (the `pixellate = false` path is test-only).
- `fragmentGainIsSmooth` materialises about 210 MB of Doubles;
  `NightFactory.audition` traps on non-finite seconds or sample rate from direct
  API callers (the CLI validates first); `writeIfListening` swallows write
  errors; `--at -3` reports "Missing value" rather than the validation message
  (ArgumentParser reads `-3` as an option); the seek residual bar of -30 dB
  could be tightened to about -90; `frame(_:_:)` is duplicated between the two
  scenes; one `print("SEEK ...")` is left in `NightFactoryTests`; the
  compressor detector switches its coefficient on instantaneous x², so it is
  peak-biased; the Hann table and FFT twiddles are rebuilt per call.

### The listening judgement is outstanding

**No agent has ears.** Everything above is measurement and structure: the
files are finite, bounded, deterministic, seekable, and the right shape on the
axes that can be measured. Nobody has played them. The implementers were told
not to describe how anything sounds and did not. Whether the chimes are *rich
and round*, whether the waves sound like waves rather than a bad radio, whether
the far version is a warm memory or just quiet, whether the channel reads as AM
radio or as a damaged file: all of that is the operator's call, and so is the
sleep science behind what the night should do. The eight files are in
`swift/listening/` (regenerate them with `swift/listening/render.sh`; vary one
with `swift run -c release nightctl audition <scene> ... --play`). Plan 7a is
done when the operator has listened and said what to change; the placeholders
above are the list of what they can ask to change.


## Plan 7b: soft mallets and low warmth

**Status (2026-11-02): built and tested; the new listening set is waiting for
the operator.** Plan 7a's first listening round told us the chimes were a
risk, and Plan 7b is the answer to it. The story (the operator's verdicts on
7a, the three throwaway rounds, the station-chime quote "like chimes they do at
train stations before an announcement", the felted-mallet reference "there's no
initial metallic ting when the note starts … but not staccato", and what was
measured from that reference) is in the spec, section **"What listening taught:
soft mallets, not bells (2026-11-02)"**, and is not repeated here. The short
version of the consequence: the bell recipe is gone, the chimes are now soft
bars, the warm low end the operator loves is its own scene, and three new
dials let them make a note longer, softer or wavering.

**The milestone is not done when the tests pass; it is done when they have
listened.** Nobody here has played any of this, and nothing below describes how
it sounds. All the numbers are measurements and invented values.

**What shipped** (branch `feat/soft-mallet-chimes`, plan
`docs/superpowers/plans/2026-11-02-am-night-7b-soft-mallets-and-low-warmth.md`):

- **Three tone dials** on `WarpDepth`: `ring`, `softness`, `vibrato`, each
  clamped to 0...1, with `nightctl` flags `--ring`, `--softness`, `--vibrato`
  (default 0; out-of-range input is rejected with a "must be" message before
  anything is written). They are frozen per note at its birth, like the other
  warp values; scenes without notes ignore them.
- **Chimes rebuilt as soft-mallet bars** (`ChimesScene`): a fundamental with a
  faint ×4 and a fainter ×10, each overtone dying faster, no mallet noise, a
  raised-cosine soft start. Same grid, density, pitch set and seekability as
  before; exact seeks still hold, now including into a long ring.
- **Power-preserving proportion** (`Proportion.powerPreservingGains`) for the
  chimes and the warmth: the favoured element still gets +6p dB and the others
  -12p dB, then the lot is rescaled so the note's power is unchanged. The
  waves do not use it (see "What 7b did not touch").
- **A new scene, `LowWarmthScene`** (`nightctl audition warmth`): slow low
  chords, each note a slightly detuned pair, lowpassed around 380 Hz, swelling
  in over seconds. Scene name `warmth`, `SceneKind.warmth`, one arm in
  `NightFactory`.
- **The listening set**: `swift/listening/render.sh` now renders ten files
  (the four waves, four soft chimes and two warmth). WAVs and
  `measurements.txt` are git-ignored; the script is the record.

**Test count: 104 tests, all passing** with `cd swift && swift test -c release`
(NightPlan 9, NightDSP 90 in 7 suites, NightCLI 5; parameterised tests count
once per function). Plan 7a ended at 80. No known-issue markers remain in the
suite, by ruling: a known issue is a test that cannot fail.

### The measurement table

Produced by `swift/listening/render.sh`: seed 1, 60 s, 44.1 kHz, levels after
the master guard. "sleepy" is `--ring 1 --softness 1`; "deep" is `--ring 1
--softness 1 --vibrato 1 --distance 0.6 --slowness 0.5`; "nochannel" is plain
with `--no-channel`. The waves rows are bit-for-bit the 7a numbers (the waves
were not touched), repeated so the table is the whole set.

| File | RMS (dB) | Peak (dBFS) | Centroid (Hz) |
|---|---|---|---|
| `chimes-soft-plain.wav` | -27.5 | -12.9 | 904 |
| `chimes-soft-sleepy.wav` | -26.5 | -15.2 | 638 |
| `chimes-soft-deep.wav` | -37.0 | -21.3 | 1040 |
| `chimes-soft-nochannel.wav` | -21.1 | -7.0 | 493 |
| `warmth-plain.wav` | -30.5 | -17.1 | 253 |
| `warmth-nochannel.wav` | -24.4 | -10.1 | 165 |
| `waves-plain.wav` | -36.8 | -20.4 | 977 |
| `waves-mid.wav` | -37.4 | -20.1 | 939 |
| `waves-far.wav` | -36.6 | -17.8 | 1033 |
| `waves-nochannel.wav` | -32.5 | -14.9 | 339 |

Measurements, not verdicts. Two things the table does show: the warmth peaks
about 3 dB lower than the chimes without the channel (-10.1 against -7.0 at
seed 1; the long-run figures are -10.5 against -6), which is a decision
recorded below, and its centroid is low (165 Hz without the channel). The
**`chimes-soft-deep` is not brighter.** Its centroid is 1040 Hz against plain's
904 with the channel, while its RMS is 10 dB lower, which reads as brighter. Rendered with `--no-channel` (seed 1, 60 s) the two are
plain 493 Hz (RMS -21.1, peak -7.0) and deep 463 Hz (RMS -34.7, peak -18.6): the
content is a little darker, as distance should make it (the RMS drop is 13.6 dB
without the channel against 9.5 dB with it). The brighter reading with the channel is consistent with
7a's noise-floor finding: the hiss and crackle stay put while the content falls
(-34.7 dB content against a -51 dB channel floor), so the floor's share of the spectrum grows.
That is the same effect the planner must handle (the channel's noise coming
down as content recedes). Likewise `chimes-soft-sleepy` is 1.0 dB *louder* in
RMS than plain after the channel (-26.5 against -27.5) although the ring dial
is +0.02 dB level-neutral: without the channel the two differ by -0.3 dB (-21.4
against -21.1), the dial's neutrality is a long-run figure for the bare scene,
and sleepy's peak is 1.9 dB lower (-8.9 against -7.0). The 1.3 dB swing is consistent with
the channel's compressor and saturation acting on a peakier plain signal more than
on the smoother sleepy one; that mechanism was not isolated.
The
channel again lifts the centroid on both new scenes (493 to 904 Hz on the
chimes, 165 to 253 Hz on the warmth), for the reason already given in the 7a
table: its band removes body and adds hiss.

### Every new placeholder, by name and value

**Every number below is invented or interpreted and none has been heard.**
*(brief)* marks a value from the plan or the spec; the rest were chosen by an
implementer or the controller. File paths are under `swift/Sources/`.

**The dials** (`NightDSP/Scenes/ChimesScene.swift`): *ring* is the fundamental's
decay time constant, 1.4 s at 0 to 4.2 s at 1, linear *(brief)*. 1.4 s is the
spike's "close to the reference" and 2.8 s was "sleepier"; **4.2 s is a
placeholder ceiling**. *Softness* is the raised-cosine attack, 0.035 s at 0 to
0.12 s at 1, linear *(brief)*; the spike measured 35 and 80 ms, **0.12 s is a
placeholder ceiling**. *Vibrato* is an amplitude pulse at 4.5 Hz, depth
`0.18 × vibrato` *(brief)*: the envelope is `1 - d·(0.5 - 0.5·cos θ)`, so it
dips from full level by up to `d`, never above it. Its phase at birth is drawn
per note (stream 6) so notes don't pulse in step. The level is multiplied by
`sqrt(1.4/τ)` (so a longer ring does not make the scene louder: measured +0.02
dB at ring 1) and by `1/(1 - d/2)` (so vibrato does not either: +0.02 dB). The
brief's rule is ±1 dB.

**The bar** (`ChimesScene`): partial ratios `[1, 4, 10]`, base amplitudes
`[1, -24 dB, -36 dB]` *(brief, the spec's sentence)*. The partial at ×k decays
with time constant `τ/sqrt(k)`, so the ×4 dies in half the fundamental's time
and the ×10 in about 0.32 of it (invented: the spec says only "dying faster").
A note ends after `min(7τ, 58 s)` (7 constants is -61 dB; 58 s keeps it inside
the 60 s lookback) and fades with a raised cosine to true zero over its last
`min(4 s, 25% of its life)`. These are the 7a element-cap rules carried over.
Partials at or above 0.45 of the sample rate are dropped. Root log-uniform
over 196...392 Hz, the two-octave pentatonic set, a 3-semitone drop at slowness
1, cell 2.2 s, strike present when `unit < 0.6/(1+2·slowness)`, 0...1.6 s into
its cell, lookback 60 s: all unchanged from 7a. Random streams: 0 root, 1
existence, 2 offset, 3 degree, 4 favoured partial, 6 vibrato phase; **stream 5
(the bells' mallet noise) is retired, not reused.**

**The felt-mallet rolloff** (invented by ruling, see below): each partial's
base amplitude is multiplied by `1/sqrt(1 + (f/2000)^4)` at its actual
frequency (a 4th-order magnitude, corner **2000 Hz**), *before* proportion's
power is redistributed. The levels this leaves, relative to the fundamental
(static, before the decay bias):

| Fundamental | ×4 | ×10 |
|---|---|---|
| 164.8 Hz (lowest note) | -24.05 dB | -37.65 dB |
| 196 Hz | -24.10 dB | -38.84 dB |
| 440 Hz (A4) | -26.03 dB | -49.87 dB |
| 1318.5 Hz (highest note) | -40.18 dB | -68.01 dB |

**Chimes master gain 0.32**, chosen so a plain passage peaks near -6 dBFS (the
median 600 s peak over 20 seeds is -6.1 dBFS, range -6.6 to -5.5; the first
60 s median is -6.7). The analytic peak bound at this gain is 0.8685, maximised
over ring {0, 0.5, 1}, softness 0, slowness 0, proportion 1, vibrato at its
crest and the fundamental over 164.8...1318.5 Hz, including birth offsets and
every note that can overlap. Blocks of 256 absolute frames.

**Low warmth** (`NightDSP/Scenes/LowWarmthScene.swift`): *(brief)* chords on a
12 s grid; each swells in over 3 s with a raised cosine and out over 3 s, so
consecutive chords overlap for 6 s (a chord sounds from `12i - 3` to
`12(j+1) + 3`); slowness lets a chord hold for more cells (a new chord is born
in a cell with probability `1/(1+slowness)`; cell 0 always); lowpass **380 Hz**,
a 4-pole Butterworth magnitude `1/sqrt(1 + (f/380)^8)`; a pair per note at
**±5 cents**, each voice drifting by up to **±4 cents** through
cosine-interpolated knots every **10 s**. *Invented:* the root is one of MIDI
29...36 (F1 to C2, about 43.7 to 65.4 Hz) per seed; the chord is one of the
diatonic triads I, vi, IV, V, always in root position, voiced root, fifth, then
the third an octave up (three notes); each voice is an additive band-limited
saw (amplitude `1/k` on harmonic k, times the lowpass), harmonics kept while
below 0.45 of the sample rate and skipped once under -60 dB (an amplitude of
1e-3 against an unfiltered fundamental of 1); every voice starts at phase 0 at
its chord's birth; harmonic weights are fixed at birth from the detuned
frequency (the drift moves the pitch, not the weighting); the drift's frequency
ratio is linearised (error under 0.001 cent). Streams: 40 root, 41 chord, 42
birth, 43 drift, 44 favoured note. Proportion's power is preserved over each
note's RMS, so a favoured low root is not louder than a favoured high third.
**Master gain 0.03**: the bound sums every partial at its crest across two
overlapping chords (14.86 for the worst chord, 29.72 for two), and 0.03 gives
0.8916 (-1.0 dBFS). That bound is conservative by about 3x (9.5 dB): the
measured 600 s peak is -10.5 dBFS and the RMS about -24 dBFS.

### What was removed

The bell recipe and its constants are gone from `ChimesScene`: the strike
(bandpassed noise, attack 0.02 s, decay 0.08 s, band centre 2x the fundamental
capped at 2500 Hz, Q 1.2, level 0.3, length 0.98 s), the body partials at
`[1, 2, 2.76, 4.07]` with decays `[6, 3, 2, 1.2]·(1+2s)` and amps `[1, 0.5,
0.35, 0.2]`, the bloom (attack 1.5 s, decay `12·(1+s)` s, amps `[0.35, 0.25]`),
the beating pair (±0.35 Hz, decay 8 s, attack 0.3 s, amps `[0.2, 0.2]`), the
bells' master gain 0.1 and mallet stream 5, and the slowness stretch on the
decays (slowness now thins and lowers the notes only; it no longer lengthens
them, because ring is the dial for that). **The chimes paragraph in "Every
placeholder, by component" under Plan 7a is therefore history, not a list of
what is in the code**; it is marked as such there. Nothing else in 7a's
placeholder list changed.

**The 7a chimes measurements no longer describe the current chimes.** The
chimes rows of the 7a table and the sentences built on them (the "far" chimes'
centroid, the fragmentation-1 centroid, "the channel takes about 5 dB off the
chimes' RMS", the chimes' proportion and distance level figures in "Before the
planner moves anything", the chimes peak figure and the chimes element-cap
ruling) were measured on bells that no longer exist. Where they are quoted
above they stand as a record of the first listening set, not as facts about the
code. The waves rows stand.

### The rulings and why

- **A felt-mallet rolloff on the partials (the departure to flag).** Making
  the ×4 favoured by proportion at +6 dB on the top note put 11.1% of the
  energy above 2 kHz (the test wanted under 1%), because that partial sits at
  5.3 kHz and power-preserving rescaling scales all three partials equally, so
  it cannot help. A ×4 at 5 kHz and -6 dB is exactly the thin, tinny alert the
  operator named, so the controller ruled that a felt mallet should not excite
  high partials, and applied the rolloff above to the base amplitudes before
  proportion. With it, the top note's ×4-favoured energy above 2 kHz is
  0.30%. **Cost: the ×10 overtone is about -44 dB in the mid-range and about -50 dB at
  A4, against the spec's "about -36 dB"** (it is -37.7 dB at the lowest note and
  -68 dB at the highest, see the table). The reference recording showed its
  strongest overtone at -20 to -27 dB, which the ×4 still meets at A4
  (-26 dB), so the bars are a touch purer than the approved spike in the upper
  range and proportion has less effect on high notes. **This is a deliberate
  departure from the spec's sentence, to be flagged for the operator's next
  listen: if they miss the glint, raise `malletCornerHz` (2000 Hz).**
- **Softness's rise threshold is 0.55, not 0.6.** A raised cosine's own 10 to
  90% rise is 0.590 of its length, so the plan's `rise >= 0.6·attack` could
  not pass; the test asks for 0.55 (measured 0.581, a thin margin). No cost.
- **No known-issue markers may stay in the suite.** Three had been recorded
  while a briefed threshold could not be met; after the rolloff and the 0.55
  threshold none remain.
- **The corrected, stricter peak bound and master gain 0.32.** The plan's
  formula for the chimes' bound was not conservative; the implementer's version
  includes birth offsets and maximises over the fundamental. No cost: it is
  stricter than briefed.
- **Warmth keeps the loose peak bound.** The briefed bound is about 3x looser
  than any real peak, so warmth peaks near -10.5 dBFS where the plain chimes
  peak near -6. Kept because the bound is truly conservative and balancing
  levels across scenes is the planner's job (already on 7a's list). **Cost:
  warmth is quieter than the chimes until the planner mixes them**; a tighter
  bound (one chord at its crest, the other at its RMS) would allow about 2x the
  gain.
- **Chord repeats stay (about 25%).** Each cell draws from all four triads, so
  about a quarter of chords repeat the one before. A repeat overlaps itself as
  a slow beating swell bounded by the peak bound, not a sudden change. Kept as
  briefed and **left as a listening item**; cost if wrong: an occasional
  static-sounding transition, fixed by a recursive no-repeat draw.
- **The warmth's handover bump (final review; a second listening item).**
  Every chord change sums two envelopes at 1, because the previous chord's
  swell-out starts as the next one's swell-in ends. Measured on seed 1 with 1 s
  RMS: steady about -24.5 dB; -22.3 to -21.2 dB at 24, 36, 48 and 60 s (+2 to
  3 dB); and -18.9 dB at 12 s (+5.6 dB, a repeated chord adding coherently).
  So the warmth breathes about 3 dB every 12 s, and up to about 6 dB on
  repeats. It is not sudden (the ramps are 3 s). Candidate fixes, only if the
  operator hears pumping: an equal-power handover (end each chord at `12*next`
  so the swell-out overlaps the next swell-in) and/or a no-repeat chord draw.
  Both are deferred until the operator has listened.
- **Work in place on the branch.** `feat/soft-mallet-chimes` was made for the
  plan and the tree was clean; no worktree. No cost.

### Known limitations and deferred items

- **The chimes' peak bound holds for constant dials only.** It evaluates
  every overlapping note at one ring value. The review found that a fast drop in
  ring can reach 1.30x the bound, which is 1.13 absolute, above full scale
  before the master guard. Mechanism: the newest note at ring 0 sits on older
  notes, each at the tau that maximises `sqrt(1.4/tau)*e^(-age/tau)`, which is
  ring 1 for every cell except the nearest. The worst-case sum is 2.378,
  against 1.823 for constant dials. In practice a 40-seed step test peaked at
  0.546, so it is a bound, not something likely to be heard, but it is the
  first case where the master guard would actively engage. Nothing varies the
  dials over time yet. The `peakBound()` comment now says "valid for constant
  dials only", and the planner must respect it.
- **Warmth is quieter than the chimes** (about -10.5 against -6 dBFS peak). A
  level decision for the planner, as above.
- **About 25% of warmth chords repeat** the previous chord. A listening item.
- **The waves still use non-power-preserving proportion.** The 7a finding (I1
  in "Before the planner moves anything": proportion 1 raises the waves by
  about +4 dB peak and +2.3 dB RMS) stands for them. 7b fixed it only for the
  chimes and the warmth.
- **The AM channel's settings were tuned against the old bells.** The `.early`
  preset (and the channel's level choices in 7a) were chosen with the bell
  chimes as the source and have not been re-listened to with soft chimes or the
  warmth. They await the operator's next listen; the numbers are unchanged.
- **The warmth's chord ignores warp today** (`chord(...warp:)` takes it and
  does nothing with it; no dial moves the pitch). Documented in code.
- **Test hygiene, deferred:** `partialsAreAPureBar` measures at 110 Hz, below
  the lowest playable note (164.8 Hz); move it to the lowest fundamental or add
  an A4 case that pins the rolloff. A note's life (`min(7τ, 58)`) and its fade
  are untested at scene level, and the vibrato phase source is untested.
  `softnessSetsTheAttack`'s margin is thin (0.581 against 0.55).
  `toneDialsClamp`'s setter checks one bound per field. `swellIsSmooth`
  evaluates every span per frame. `cutoffIsInHz` compares exactly, which would
  break if the 0.45·sr ceiling ever bound at 44.1 kHz.
- **For iOS:** each chime voice makes three small heap allocations per block,
  (a controller-noted item); the same class of work as the 7a list of real-time
  hazards, still to do before the app. The warmth's allocations were not
  audited.
- **Still true from 7a, and not touched:** no real-time engine, no planner, no
  time-varying warp in the tool, no later-night channel presets.

### What 7b did not touch

The waves, `WavesScene`, `Distance`, `Fragmenter`, the reverb and the channel
are byte-for-byte as they were (the waves renders match 7a's to the printed
digit). The channel's chain position, the single factory and `NightPlan`'s
Foundation-only rule are unchanged.

### The listening judgement is outstanding

Ten files are in `swift/listening/` (`render.sh` regenerates them). Things to
listen for, in the order they would show: whether the new chimes lose the
station-chime alert at the top of the range; whether the sleepy and deep
versions are what "longer, softer, wavering" means to the operator; whether the
×10 departure above costs them the glint; whether the warmth is the warm low end
they meant, and whether its repeated chords and its quiet level bother them;
and whether the channel still suits either. To vary one by ear:
`swift run -c release nightctl audition chimes --ring 1 --softness 1 --vibrato 0.5 --play`
(or `warmth`; all three dials are `0...1`).

## How the Python engine got here

Status as of the end of the `feat/arrangement` branch (Plan 4a of the
arrangement design, all 7 tasks complete), on top of `feat/finishing-touches`
(Plan 3g), `feat/legibility` (Plan 3f), and the `feat/presets` branch (Plan 3d
of the spec, all
6 tasks complete), on top of `feat/render-queue` (Plan 3c, all 9 tasks
complete), on top of `feat/mixer` (Plan 3b, all 7 tasks complete), on top of
`feat/elm-shell` (Plan 3a of the spec, all 6 tasks complete), on top of
`feat/interactive-server` (Plan 2b, all 8 tasks complete),
`feat/server-foundation` (Plan 2a, all 7 tasks complete), and `feat/core-hooks`
(Plan 1, all 10 tasks complete). Plan 1 gave the pipeline the hooks a local web
UI needs — session staging, cheap preview, structured progress, stable data
paths, a config schema — without building the UI itself. Plan 2a put an HTTP
server in front of that: a FastAPI app, a SQLite library store, and enough of a
songs API to import a file and draw its waveform. Plan 2b built the rest of the
API: preview, background jobs with live progress and cancellation, renders, and
presets. Plan 3a is the first real frontend — an Elm application replacing the
placeholder `index.html` — and it is scoped to *browsing and separating*, not
yet to mixing or rendering. Plan 3b adds the mixer: controls generated from the
config schema, a scrubber over the decay arc, and audio that plays while you
shape it. Plan 3c makes a running separation genuinely stoppable (previously
only a render could be cancelled mid-flight; Demucs's own call was a single
opaque block nothing could interrupt), and it gives the interface the three
things Plan 3b's own closing section named as still missing — a render
screen, a queue screen, and a warning before a job large enough to block
everything behind it. Plan 3d is the subject of this section: it gives
presets a screen — `server/api/presets.py`'s CRUD had been reachable only with
`curl` since Plan 2b — adds `PUT /api/presets/{id}` so one can be renamed or
saved over instead of only ever created fresh, and closes a gap this document
used to carry as open by adding `GET /api/config/default`, the route that lets
a freshly opened mixer start from the same curated per-stem values
`sleepmix render` does rather than from the schema's one identical setting for
every stem. Plan 3e (level-matching) was retired before implementation — see
its entry under "Known weaknesses" — so the branch on top of 3d is Plan 3f
(`feat/legibility`, 6 tasks), which writes no new feature at all: it makes the
mixer explain itself. Every section carries a description that comes from the
`config` dataclass's own docstring, and every control whose *name* states a
mechanism rather than an outcome carries a line of help underneath it. Both
were previously either absent or an `Attr.title` — a tooltip, which is nothing
on a touchscreen, nothing to a keyboard, and nothing to anyone not hovering the
exact element.

Plan 3g (`feat/finishing-touches`, 3 tasks) is the top of the branch and closes
the last two gaps this document carried as open and worth closing. **The sound
bed now reaches previews**: `render_window` mixes it in where `run_pipeline`
does, so turning on binaural beats or pink noise finally changes something you
can hear in the mixer — the one recorded preview-versus-render difference that
was about *character* rather than level, and therefore the one that touched the
judgement a preview exists to support. That forced `config.soundbed` into
`RenderSession._master_key` in the same commit, because the calibration window
began reading a field the memoized gain had been allowed to ignore. And **the
help text Plan 3f made visible is now findable by a screen reader**: every
control has an `id`, every label a real `for`, and every control with help an
`aria-describedby` pointing at it.

Plan 4a (`feat/arrangement`, 7 tasks) sits on top of all of that and is the
first change since Plan 1 to touch the shape of the mix itself rather than the
interface to it. **The gap between one repeat of the loop and the next is now a
setting**, it can grow across the mix, and it can be negative — which makes
repeats overlap and stack instead of handing over. Underneath that, placement
stopped being a constant: a pure planner (`sleepmix/arrangement.py`) decides
where every repeat lands and how decayed it is, the renderer and the preview
both read that plan, and 348 tests pass against a 299-test baseline at the
start of the branch. Its own section below is the record.

Plan 5, Phase 1 (`feat/night-stream`, 9 tasks plus this one) sits on top of
all of that and is a different kind of change from every plan before it: it
does not touch the finite-mix pipeline at all. `sleepmix/night/` is a new
package, reachable only from a new `sleepmix night` subcommand, producing a
night-long ambient stream instead of a rendered file. 482 tests pass against
the 356-test baseline at the start of that branch. Its own section, below, is
the record — and it opens with what the plan's own reference code got wrong,
because that is the part most worth not losing.

Plan 5, Phase 3 (`feat/night-ghost`, 8 tasks, complete) sits on top of Phase 1
and gives the night a second kind of material: real recordings, prepared
ahead of time, dissolving into drones built from their own spectrum. Phase 2 —
the microphone — was skipped rather than built. 663 tests pass against the
534-test baseline at the start of this branch. Its own section, first below,
is the record.

Read `docs/architecture.md` first for how the pieces fit together; this document
is about what's true right now, what was traded off to get here, and what's
explicitly not done yet.

## Plan 5, Phase 3: the ghost

`feat/night-ghost`, 8 tasks, complete. The design is
`docs/superpowers/specs/2026-08-18-night-ghost-design.md`, and it is the phase
Phase 1's own spec named as the eventual goal and deferred: *source-derived
early, synthesis late*. `docs/architecture.md`'s new section, "The ghost: a
prepared loop becomes its own double," has the mechanics; this section is
what a reader needs that is not mechanics.

### Phase 2 was skipped, not reordered

Phase 1's spec scheduled adaptive masking — the stream reading the room's own
noise floor through a microphone and quieting itself to match — as Phase 2,
and called it the most valuable steering input in the whole design, because it
was the only closed loop. It never got a task list.

The reasoning is worth keeping in full, because it was a design conclusion
about what the feature had become, not a scoping retreat under time pressure.
The operator's own choice — the room may make the stream quieter but never
louder — removes the danger a microphone is usually interesting for: a stream
that a microphone mistakes for room noise now produces *less* reduction, which
tops out at the arc's own ceiling, so being masked by your own masking is
impossible by construction. But the loop does not vanish; it inverts. A quiet
room lets the stream sink, a sunken stream reads quieter still, which lets it
sink further — the same feedback, aimed at silence instead of at noise,
arriving at 11 PM in a quiet house rather than at 4 AM in a noisy one. So the
risk shrank by more than the value did: a microphone varies what already
exists, and Phase 3's source material changes what the night is made of. The
operator chose the second.

**The empty-band finding is preserved here for whoever revisits this.** The
favoured escape from the feedback loop was spectral subtraction of the known
output, which needs a model of the acoustic path from speaker to microphone —
the only option in the discussion with any setup-specific work in it. There is
a cheaper one sitting unused: the arc lowpasses everything to
`brightness_hz`, sweeping 6000 Hz down to 500 Hz across the night, and after
Phase 1's noise-floor fix only **0.85% of block energy** sits above that
ceiling. That is a wide, known, guaranteed-quiet band the stream itself has
vacated, in which a microphone hears almost nothing but the room — and it gets
quieter, and so more room-only, as the night goes on. Measuring the room in
the band the stream is not using is setup-independent and cheaper than
subtraction, and it costs nothing extra to notice because the design already
guarantees the band's emptiness for an unrelated reason. Two things could
spoil it, and both are a short spike rather than a design question: laptop
microphones are often bandlimited and noisy above 8 kHz, and a low rumble has
little high-frequency energy up there to be detected by.

### The placeholders, named, none of them listened to

Every value below is a real number in a named constant, invented rather than
measured, in the same spirit as Phase 1's own list above. The person who can
fix any of them is the one who has slept through a night carrying them, which
as of this section is nobody.

**The top follow-up, and it is not a taste question: `MAX_SOURCE_RATIO` does
not control the quantity its own name and documentation describe.**
`palette.render_voice` peak-normalises each voice independently *before*
`Voice.gain` is applied, so the two halves of a pair reach the mix with
unrelated crest factors — a tiled recording is peaky, a drone is not, a noise
band is somewhere else again — and an equal-power gain pair therefore realises
whatever energy split those crest factors imply rather than the one asked for.
Measured across ten consecutive real pairs: an intended 0.85 realised as
anywhere from **0.60 to 0.91**. It is also the explanation for a number
already recorded below as a datum without anyone noticing it was a
discrepancy: the 22:30 excerpt reads 69/31 against an intended 85/15.

This is **documented and deliberately not fixed**, for two reasons that are
about sequencing rather than difficulty. The safety property the constant
exists for survives intact — the ghost is never absent, and at the top of the
observed spread it is still about −10 dB rather than gone — so nothing in the
spec is being violated, only a docstring's implied precision. And the fix
(normalising by RMS instead of by peak) would move every level on this branch
and invalidate the listening excerpts for the **fourth** time on this project,
before anyone has listened to the current set even once. Whoever picks this up
should expect to re-render the excerpts and to have the previous numbers stop
comparing. Until then, anyone tuning `MAX_SOURCE_RATIO` by ear is chasing a
target that moves with the material.

**The second follow-up is memory, and it is not the night's to fix.**
Rendering one voice costs a peak RSS of roughly **34x the buffer it produces**,
and the multiplier is stable across lengths — measured at 44.1 kHz through
`NightStream._rendered`: 240 s → 2.90 GB peak against a 0.081 GB buffer
(35.9x), 944 s → 10.29 GB against 0.312 GB (33.0x). That stability says it is
a fixed number of full-buffer temporaries inside `apply_decay` rather than
anything about voice length or about the night. The unbounded part of the
problem is gone — see `SEAM_APPROACH_S` below — but the honest post-fix
headline is **10.29 GB → about 7.0 GB (7.2 GB for a noise band)**, not the
6.69 GB once recorded here: that figure was measured for a 589.9 s voice,
which the fix wave's own wider sweep (400 seeds x five source counts)
superseded with a true post-fix worst case of 598.4 s, measuring 6.98 GB for
a drone and 7.19 GB for a noise band — `noiseband` is consistently more
expensive than `drone`, and the original measurement covered only the drone
path. The stated ceiling, `MAX_VOICE_TOTAL_S = 690 s`, bounds peak RSS at
roughly 8.0 GB (measured 7.8–8.0 GB at that length). Even a Phase 1 night
with no sources at all peaks near 2.9 GB for its 240 s worst case, which
predates this phase entirely. The remaining term is `apply_decay`'s
33–36x multiplier, already recorded above as an out-of-scope follow-up:
reducing it means changing `disintegration.py`, on the render path
`sleepmix render` shares, so it wants its own measurement pass rather than a
patch on the way out.

- **`LOOPS_PER_SOURCE = 3`** (`night/prepare.py`) — how many loops one song
  contributes. Enough for internal variety without one loop recurring often;
  a guess.
- **`LOOP_BARS`** (`night/prepare.py`) — **shipped this branch at 4, and
  corrected to 2 before the excerpts were re-rendered; see "`LOOP_BARS` was 4
  and defeated its own rationale" below.**
- **`STRETCH_SPEED = 0.6`** (`night/prepare.py`) — how much the loop is slowed
  before it enters the night. Chosen to pull gesture below the rate the ear
  tracks phrasing at; not measured against an ear.
- **`MAX_SOURCE_RATIO = 0.85`** (`night/plan.py`) — the birth ratio's ceiling,
  so the unprocessed loop is never heard entirely alone. The single most
  direct implementation of "clearly music, not identifiable," and a first
  draft.
- **`MIN_AUDIBLE_RATIO = 0.05`** (`night/plan.py`) — below this, a voice in
  the pair is not worth rendering at all. Where "not worth it" starts is a
  guess.
- **`STAGE_MIN_S` / `STAGE_MAX_S`** (`night/plan.py`) — 20 and 45 minutes,
  how long one source holds the stage before handing over. Long enough that
  its own several loops establish a place, short enough that a night visits
  more than one or two sources; neither bound has been checked against a
  real night.
- **`HANDOVER_COVER_S = 90.0`** (`night/plan.py`) — how far past a handover
  the covering voice must reach. Long enough that the incoming source has
  clearly arrived; a guess at what "clearly" needs.
- **`SEAM_APPROACH_S = 15.0`** (`night/plan.py`) — how close before a genuine
  handover the walk forces a birth, so the cover spans a bounded distance
  rather than whatever birth gap happened to cross the seam. It is a
  placeholder in its exact value only: the actual correctness condition is
  staying under the *maximum* birth gap (~980 s at the sparsest density),
  so the clamp still has room to fire — measured at 0.001 s, 1 s, 60 s, and
  200 s, all well above `_BIRTH_GAP_MIN_S`, still giving zero bare seams and
  zero ceiling breaches, while 1200 s (above the maximum birth gap) does
  breach. Staying under `_BIRTH_GAP_MIN_S` (20 s) is a nicety rather than a
  requirement: it means the step born before a seam reaches past it on its
  very next draw rather than creeping toward it over several. Fifteen
  seconds is the guess inside that nicety. Audibly, this is what makes
  births cluster slightly at handovers.
- **`MAX_VOICE_TOTAL_S = 690.0`** (`night/plan.py`) — not a taste value but a
  derived ceiling (`MAX_VOICE_S * OUTLIVE_MAX + HANDOVER_COVER_S`), listed
  here because it moves whenever any of those three do, and a test asserts
  it. It is deliberately looser than the true bound: the two mechanisms that
  lengthen a voice do not compose, so the real maximum is the larger of them
  (600 s), and the longest voice found anywhere in a 2000-night sweep
  (400 seeds x five source counts) is 598.4 s.
- **`LOOP_MIN_S = 4.0` / `LOOP_MAX_S = 12.0` and `_BAND_MARGIN = 0.05`**
  (`night/prepare.py`) — the band a finished loop must land in, now enforced
  by clamping the slice rather than hoped for from `LOOP_BARS` and a detected
  tempo. The band itself is the plan's own stated intent ("short enough to
  carry no phrase"); the margin is a guess large enough to absorb the
  stretchers' inexactness. Nobody has listened to either end of the band.
- **`OUTLIVE_CHANCE = 0.15`**, **`OUTLIVE_MIN`, `OUTLIVE_MAX = 1.5, 2.5`**
  (`night/plan.py`) — how often, away from a handover, a ghost survives past
  its source as a flourish rather than the rule, and by what multiple of its
  own would-be lifetime. All three are placeholders for what "occasional"
  means in numbers.
- **`MIN_PEAK_FRACTION = 0.02`** (`night/pitch.py`) — how loud a spectral peak
  must be, relative to the strongest one, to count as a pitch. See "`pitch_set`
  does not reject non-tonal material" below for why this is the *only*
  tonality gate left, and what it does not do.
- **The fold band, `FOLD_LOW_HZ = 55.0` / `FOLD_HIGH_HZ = 110.0`**
  (`night/pitch.py`) — the one octave every extracted pitch is folded into
  before it reaches a ghost. Low enough to sit under whatever else is
  sounding; not tuned against anything else that might be sounding.

**One placeholder from Phase 1 is not a new one, and is named here only to
correct a possible misreading.** `NOISE_BELOW_LEVEL_DB = -40.0`
(`night/plan.py`) governs the hiss floor of every voice `_decay_for` builds —
source voices and ghosts included, since Phase 3 adds no branch to that
function at all. It is Phase 1's placeholder, already recorded and reasoned
about above; Phase 3 simply inherits it unchanged for the two new kinds of
voice, rather than inventing a second one for the ghost's own floor.

### `pitch_set` does not reject non-tonal material, and two attempts failed

The spec asks for pitches "actually present" in a loop, and the first draft
of the extractor also tried, unasked, to refuse a pitch set for material with
no real tonality — a field recording, say, that happens to have a few strong
bins by chance. Neither of two attempts at that could tell noise from music.

**A peak-to-median-floor ratio, tuned against white noise, failed against
everything else tried.** Gated at 8.0, it rejected white Gaussian noise with a
claimed margin of "noise ≤ 4.6, real tones ≥ 10⁶" — and then read pink noise,
band-limited noise, and this repository's own cached separated stems,
including a `drums.wav` and a near-silent vocal-leakage stem at peak 0.0004,
as *all* confidently pitched: full six-pitch sets, 200 times out of 200 for
pink noise. The claimed margin collapsed to 389 on real material. That
constant had been fitted to the one test that motivated it, and nothing else.

**Spectral flatness — the standard, principled measure of tonality — failed
in the opposite direction.** It is the geometric mean of the in-band spectrum
over its arithmetic mean, bounded in `(0, 1]`, near 0 for a tone and near 1 for
noise, and it is not a fitted constant the way a peak ratio is. Measured
independently by two people using two different synthesis methods, it agreed
to the digit: narrowband noise reads as **more tonal than the least-tonal real
instrument tested, by five-plus orders of magnitude** (flatness near zero
against a real recording's 0.00965), because the geometric mean collapses
whenever a signal's energy sits in a narrow sub-range of the wide scan band
the formula is computed over — exactly the shape of the noise being tested
for.

**The requirement was deleted rather than fitted to a third constant.** The
spec never asked for noise rejection; a test written without checking it was
achievable did, and once two independently-verified approaches had failed for
two different, well-understood reasons, fitting a third number to pass that
one test would have repeated the exact mistake the first attempt made.
`MIN_PEAK_FRACTION` is left as the only gate, and it does only what its name
says: it compares peaks to each other, never to a floor, so it cannot and does
not claim to separate tone from noise.

**The forward pointer, recorded rather than acted on.** A **local** flatness —
computed in a narrow window around each candidate peak rather than across the
whole 40–4000 Hz scan band — would plausibly separate the two classes, because
within a narrow window a true sinusoid still concentrates into one bin while
narrowband noise stays flat there too. Neither attempt tried this; it is a
third approach, not a retry of either failed one.

**The consequence, stated plainly rather than left implicit:** a rain
recording, or any other genuinely non-tonal file, dropped into the sources
folder gets a ghost at arbitrary-but-harmless frequencies — deterministic,
always in-band, never degenerate — rather than the "no ghost" a listener might
reasonably expect from material with no real pitch in it. This is a known and
named limitation, not a bug nobody noticed.

### The deliberate difference from the spec: one pitch set per source

The spec's own wording is "the frequencies actually present in **each loop**"
— one pitch set per loop. What ships is one pooled pitch set per
`SourceProfile`, covering every loop `prepare_source` extracted from that
song, computed once from `sum_buffers` of all of them together. The reasoning
recorded at the point of the change: a `SourceProfile` already carries one
set as its whole interface to the planner, a ghost of *this song* is a more
useful object than a ghost of *this loop* — three loops from the same
recording sharing one instrument and one room have no reason to sound like
three different chords — and the handover preference (`pitch_distance`, which
picks the next source to hold the stage) already reasons at song level, not
loop level. Named here as a deliberate divergence rather than left to be
noticed by someone diffing the spec against the code.

### `LOOP_BARS` was 4 and defeated its own rationale

The stated purpose of the 4–12 second loop-length band is "short enough to
carry no phrase." `LOOP_BARS` shipped this branch's early tasks at 4, and four
bars of source material *is* a phrase — the two constants that set the
effective loop length interact directly:

```
bars × beats_per_bar × 60 / tempo ÷ STRETCH_SPEED
```

At four bars, a 120 BPM tempo and `STRETCH_SPEED = 0.6`, that comes to roughly
**13.2 seconds** — outside the stated 4–12 s band, and long enough to carry
exactly the kind of phrase the band exists to forbid. The only check actually
enforced at the time was a 1–40 second sanity bound loose enough to notice
nothing at all. `LOOP_BARS` is now **2**, landing at roughly 6.7 seconds:
inside the band, and genuinely too short to carry a phrase. Neither constant
can be changed alone without re-deriving where the pair lands — the formula
above is the whole of the relationship, and it is worth keeping visible
because nothing enforces it except a comment next to `LOOP_BARS` in
`night/prepare.py`.

### Wind is still a dead steering row, and it stayed dead deliberately

`night/palette.py`'s `_slow_drift` — the depth of the drones' amplitude
drift, the row the steering table gives to wind — still receives only
`(n, sr, rng)`, no `NightContext`, exactly as Phase 1 left it. It was offered
as the smaller of two pieces of work put up for this branch and passed over
in favour of the ghost, which is the larger and more interesting change. One
of the spec's six steering rows still does nothing, and this document said so
under Phase 1 and says so again here rather than letting the claim go stale
by omission.

### Ambient light was considered, and it needs a spike rather than a design

The same discussion that decided the microphone considered ambient light as a
steering input and set it aside for a different reason than wind's: it is not
smaller work, it is *unknown* work. A room going dark is the best available
proxy this system has for *you have actually gone to bed* — a fact nothing
else in the design can currently infer — which makes it more interesting than
any input on the existing steering table. It may also be unreadable at all on
Apple Silicon, which is not something a design document can resolve; only a
short technical spike can. Recorded here so the next person who reaches for
it starts with the spike rather than a spec.

### Defects in the plan's own reference code, and the pattern in them

The task briefs for this branch, like Phase 1's, shipped working verbatim code
for most tasks. Real defects were found in that code across all seven
implementation tasks — somewhere in the high teens to the mid-twenties by
count, depending on where the line is drawn between a defect in the reference
code, a controller ruling made mid-branch, and a test that simply could not
fail. That line is a judgement call, not something the execution ledger
settles on its own, so no single number is asserted here. The count was never
the useful part anyway; the pattern is, and it repeats the lesson Phase 1
already recorded once under its own false-safety-proof incident: a plan
document is prose with the authority of code and none of the checking.

**Some were tests asserting values that were impossible under constants
defined in the very same file.** Task 1's fold test expected a folded value of
exactly `110.0` from a band `pitch.py` itself defines as upper-*exclusive*,
`[FOLD_LOW_HZ, FOLD_HIGH_HZ)` — the expected value could never occur. Task 6's
resample test built a voice's `n_frames` from the module's `SR` constant
regardless of the sample rate it was actually rendering at, so its own
assertion (thirty seconds of audio at 44100 Hz) was arithmetic nonsense for a
voice built for the same duration at 22050 Hz. Both were caught the same
way: run the test, watch it fail against code that had not changed.

**Several more were tests that could not fail against the defect they existed
to catch.** Task 1's "three distinct tones" test used an exact octave pair as
its fixture, in a test whose entire subject was that octave-folding collapses
octaves into one pitch — a fixture chosen from precisely the family the test
was checking for. Task 5's ghost-pitch test asserted only `20.0 < pitch_hz <
130.0`, a window wide enough to contain both the fold band and the
seed-drawn root pitches, so it could not distinguish a ghost pitch from an
ordinary seeded one — the only thing it existed to check. Task 6's cache
test asserted a purity property that held whether or not any caching
mechanism existed at all; deleting the eviction logic outright left it
green.

**Two guards were flagged as decorative by the implementers who wrote them,
self-reported rather than found by a later reviewer.** Task 5's implementer
could not, after a 6000-trial sweep, construct a case where a stated
simplification actually mattered to the test guarding it. Task 6's
implementer tried dropping the cache key's sample-rate field and mutating a
cached buffer in place, could defeat neither attempt, and flagged the guard
as unverified rather than claiming it discriminating. Both were kept rather
than deleted or rewritten under time pressure, and both are recorded here by
name rather than folded quietly into a passing count.

### Three listening artefacts on this project have been unrepresentative

Every excerpt rendered from this branch's own reference material, until the
very last task, was of a `NightStream` nobody can actually run.
`NightStream(ctx, sr=44100)` — the excerpt script's own construction, taking
`SoundbedConfig`'s dataclass default — builds the bed **off**.
`cli.py:199`'s real `sleepmix night` builds `SoundbedConfig(enabled=True)`,
because Phase 1's own review found a night without the bed silent for much of
the small hours. The rule this leaves behind: **an excerpt script must
construct `NightStream` exactly as `cli.py` does**, or every measurement taken
from it describes a night nobody can hear.

**The excerpt measurements, taken from the corrected script, with a sampling
caveat that belongs beside them rather than after them.** Three three-minute
windows, one source (`nackmandela.mp3`), the same seed:

| Excerpt | RMS | Peak | Centroid | Voices |
|---|---|---|---|---|
| 22:30 | 0.1126 | 0.721 | 877 Hz | 8 — 4 source, 4 ghost, 69/31 energy split |
| 01:00 | 0.00131 | 0.0061 | 178 Hz | 0 — bed only |
| 04:00 | 0.00077 | 0.0035 | 100 Hz | 0 — bed only |

**Two of the three contain no voices at all**, and that is not a defect in
the excerpt or the design: each is a three-minute window landing entirely
inside one of the night's own birth gaps — roughly 450 s long at that hour,
where the arc's own density has already stretched the gap range to something
like 150–520 s — so a three-minute window falls between voices more often
than not. The files are accurate, and they demonstrate the *sparseness* the arc is
built to produce rather than the ghost mechanism this phase exists for. Only
22:30, with four source voices sounding against four ghosts at a 69/31 energy
split, shows the actual mechanism. The centroid falling **877 → 178 → 100 Hz**
across the three excerpts is the arc's brightness ceiling doing its stated
job, measured rather than merely claimed.

Whether seven-minute stretches of bed-only listening are the right shape for
a sleep tool is exactly the kind of question this document does not get to
answer. It is the operator's, and it now has numbers attached to it rather
than only an impression.

### The listening judgement is still outstanding

No agent has ears. Every measurement in this section — RMS, peak, spectral
centroid, voice count, energy split — is objective and none of it is a
verdict on how any of it sounds. Nobody has slept through a night this branch
produced. Every taste value named in "The placeholders" above, and the
question of whether the ghost mechanism itself reads as company or as
something stranger, is unvalidated until someone does.

## Plan 5, Phase 1: the night

`feat/night-stream`, 10 tasks, complete. The design is
`docs/superpowers/specs/2026-08-18-night-stream-design.md`: an indefinite,
self-quieting ambient stream that runs all night and evolves without becoming
energetic, in place of a finite rendered file. `docs/architecture.md`'s new
section, "The night: block independence is the purity property, renamed," has
the mechanics; this section is what a reader needs that is not mechanics.

**What shipped is synthesis-only, by choice, and the choice was made in the
spec rather than discovered as a shortcut.** Every voice in Phase 1 comes from
one of two generators in `night/palette.py` — additive drones and
bandpass-filtered pink noise — never from a separated stem of a real
recording. The operator's actual preference was the other order: recognisable
material near bedtime, dissolving toward pure synthesis by the small hours.
Starting synthesis-only was offered as a way to prove the concept without
building the expensive half of the pipeline (no Demucs, no loop detection, no
time-stretch) twice, and it was taken. **The spec names the risk of that order
explicitly, and it is worth restating rather than letting it go quiet: if the
synthesis-only version is good enough on its own, the source-derived phase
(Phase 3) may never feel necessary, and designing the handover to it
retroactively is harder than designing it in from the start.** The seam kept
open against that risk is `night/plan.py`'s `Voice` record, which names a
*source of material* — an index, a birth frame, a lifetime, a pitch, a texture
string, a decay config — rather than naming or holding a generator. In Phase 1
every `texture` is one of `TEXTURES = ("drone", "noiseband")`; in Phase 3 some
would be prepared loops from a real song instead, and the planner's actual job
— deciding what is born when, at what pitch, under what ceiling — does not
change. If a `Voice` field is ever added that only makes sense for synthesis,
that is the moment Phase 3 got harder, and the spec is explicit that it should
read as a design error rather than a convenience. Nothing in the shipped code
has done that yet.

### The whole-branch review, and the twelve things it found that ten task reviews did not

The branch was reviewed once more as a *whole* before being handed over, and
that review found more than the ten per-task reviews had between them. The
list is worth keeping in full, because the pattern in it is not "these ten
reviewers were careless" — it is that **every defect below lives in the space
between two modules that were each reviewed alone.**

The three critical ones, all of them the same shape:

- **`plan._decay_for` never set the decay noise floor**, so it stayed at
  `StemDecayConfig`'s absolute -42 dB while everything else about a voice
  descended with the arc. `apply_decay` adds that noise *last* — after the
  lowpass, after the gain, after `palette`'s fade — so a voice's birth
  stepped from exact digital silence to -40 dBFS broadband hiss in one
  sample; at hour six 37.4% of a block's energy sat above the arc's own
  brightness ceiling with the centroid at double it. `palette`'s no-attack
  test passed the whole time, because it tests `render_voice` in isolation
  and the two stages that put audio back at the ends of the buffer run
  after it. Fixed at both ends: the floor is pinned to `arc.level_db`, and
  `stream._rendered` now re-applies `palette.fade_envelope` over the whole
  padded buffer after decay and after the reverb trim.
- **Nothing rendered ahead of playback.** `NightPlayer.queue_depth` was
  stored and read by nothing; `run` rendered block *i*, handed it to a
  *blocking* `sd.OutputStream.write`, then rendered *i+1*. A block
  containing a voice birth costs 0.68-1.09 s against a device buffer of
  0.05-0.2 s, and voices are born every 20-70 s early in the night — an
  underrun once or twice a minute, on a device whose failure mode is a
  click. The spec and the plan both described a queue; nobody built it, and
  `fallback_block` — which exists precisely for "the block queue drains into
  a bed the player generates" — was therefore unreachable for its own
  reason. Now a daemon producer thread renders into a
  `queue.Queue(maxsize=queue_depth)` and the consumer substitutes
  `fallback_block` rather than waiting. The speech mix stays in the
  consumer, deliberately: moving it to the producer would make the live
  layer up to thirty seconds stale.
- **`through_a_wall` left 12 ms of digital silence at every block
  boundary** — see the section on the reverb pre-delay below, which is the
  one place on this branch where a *documented, argued* decision turned out
  to be wrong rather than merely absent.

And the rest, briefly:

- **Both distance treatments were per-block peak AGC.** Each ended in
  `data * (target / peak)`, so a 60 dB change in source level produced no
  change in output, a pause between two lines of dialogue was lifted to the
  same peak as the dialogue, and the gain stepped at every block boundary —
  a room pumping on a ten-second cycle. Replaced with a plain gain under a
  fixed ceiling (`speech._TREATMENT_CEILING`), fixed being the operative
  word: a reduction computed per block is a different reduction next block.
- **`squelch` closed the gate at both ends of every block.** Both `lfilter`
  passes ran from zero initial conditions, so `gate[:5]` and `gate[-5:]`
  were exactly 0 regardless of what was on the air — a ~100 ms duck at
  0.1 Hz all night, and a transmission straddling a seam chopped at both
  ends. Fixed with `lfilter_zi`, scaled by the *mean of the first smoothing
  window* rather than by the first sample: `raw` is a rectified-signal
  indicator that toggles at twice the audio frequency, so a single sample is
  a coin flip.
- **The playback loop blocked on the network and on whole-file decoding.**
  `RoomSource._advance` called `load_audio` — a whole-file read plus
  resample — from inside `read`, and `RadioSource.read` blocked until ten
  seconds of live stream had arrived. Both now fill from daemon threads:
  radio into a ring buffer, room by prefetching the next file while the
  current one plays, with the current buffer looped (crossfaded) rather than
  waited for if the prefetch has not landed.
- **Degradation granularity was the block, not the voice.** Any exception
  inside `stream._rendered` propagated out of `block`, so one bad voice cost
  ten seconds of music and got pink noise in exchange. The spec asks for
  "skip it, log it, continue"; the loop body is now wrapped per voice.
- **Both clipping tests were incapable of failing.** They asserted
  `max <= 1.0` against functions whose last statement is
  `np.clip(..., -1, 1)`. Measured pre-clip peaks: seed 3 → 0.751, seed 11 →
  1.053, seed 99 → **1.266, with 9 of 120 blocks clipping.** `NightStream`
  and `NightPlayer` grew `summed`/`summed_mix` so the tests have the number
  that arrives at the clip, and `palette._PEAK` came down from 0.35 to 0.20
  (worst pre-clip peak across seven seeds: 0.76).
- **The voice cache held 1.3 GB, not "a few tens of megabytes"** — see
  `docs/architecture.md`. Now bounded by bytes.
- **The steering sweep could not catch the defect it existed to catch.**
  Three of its four assertions were bounds `arc_at` clamps to before
  returning. Demonstrated: `cloud_cover = -5.0` doubled mid-night brightness
  and the sweep passed. Rewritten to assert the ordering that is actually
  load-bearing — every steered arc is no brighter than the same night
  unsteered, at every *t* — and `cloud_cover` is now clamped at its use site
  like its three siblings.
- **The sound bed was never switched on.** With it off, seed 3 rendered
  **26 of 30 consecutive blocks as exact digital silence** at 6.5 h in (seed
  11: 28/30; seed 1: 8/30), with voice-coverage gaps up to 694 s — so a
  shipped night was silent for much of the small hours, and "cloud and rain
  → the noise bed's level and character" was a dead steering row rather than
  an untested one. `sleepmix night` now passes `SoundbedConfig(enabled=True)`;
  the config's own default stays off, because every other caller has a mix
  underneath it and this one does not.

One thing the review suspected and measurement cleared: **the circular
convolution in `stream._soft_lowpass` is not the bed's seam artefact.** The
number this paragraph used to give for it, though, was wrong, and is corrected
here rather than quietly widened. It said the wrap contributes "at most -41 dB
relative to the block's peak"; that figure does not reproduce against the
module's own input. **Re-measured with the pink noise `_bed_window` actually
generates** — 44.1 kHz, seed 3, block 6, one whole `block + overlap` window,
against two independently constructed linear references (zero-padded
filtering, and an explicit zero-phase FIR convolved long) that agree to the
digit — the wrap reaches **-17.3 dB relative to the block's peak at a 500 Hz
cutoff and -16.2 dB at 3000 Hz**, worst case -9.8 dB across twenty seed/block
combinations. White noise, the same way, gives -9.7 dB and -12.4 dB. The old
figure was stated as a property of the filter when it was a property of one
measurement.

The conclusion is unchanged, because it never rested on the size of the number
— it rested on *where* the error is. A circular filter reads the opposite end
of its own window, so the error lives at the window's first and last samples:
above -60 dB only within 1.6 ms of each edge at 500 Hz and 0.3 ms at 3000 Hz,
with the interior matching the linear reference to -71.7 dB and -127.0 dB
against peaks of 0.669 and 0.778. Those first and last samples are exactly the
ones the overlap crossfade multiplies by approximately zero, so the fix for the
seam attenuates this as well. The one place it is not attenuated is the head of
block 0, which has no previous window to cross out of — one sample at the very
start of a night, before anything is asleep in it. The seam was real —
7.3x the largest within-block step, past the same 4x threshold the music's own
seam test uses — but it was **independent noise per block**, which is
inaudible while the noise is broadband and stops being inaudible the moment
the arc darkens it: lowpassing collapses the within-block motion and leaves
the seam standing. Fixed by generating each bed window a quarter-second past
the end of its own block and crossfading into the next, which keeps the bed a
pure function of the block index and so leaves block independence intact.

### Six bugs in the plan's own reference code, confirmed independently by implementer and reviewer

The plan document that drove this branch shipped working verbatim code for
most tasks. Six bugs were found in it during implementation, across four
tasks (6, 7, 8 and 9), by implementers and confirmed independently by
reviewers, and the pattern is worth keeping past the fixes themselves:

- **`_lowpass_fft` and `_bandpass_fft` (`night/speech.py`) both called
  `np.fft.rfft(x, axis=0)` on a stereo buffer but `np.fft.irfft(..., n=n)`
  with no `axis` argument** — defaulting to the last axis, which for a
  `(frames, 2)` array is the two-wide channel axis rather than the frames
  axis. The failing evidence in Task 7's own review was as blunt as a bug gets
  to be: `out.n_channels == 44100`. `_bandpass_fft` carried the identical
  defect one task later, confirmed independently — the second instance of the
  same bug class in the same file, from the same plan document.
- **`RoomSource` hung forever on a media file that decoded successfully but
  yielded zero frames** — a plausible corrupt-download case. `_advance`
  accepted a zero-frame buffer as "loaded," the read loop's cursor was
  already past the end of it, and nothing ever advanced again: an infinite
  loop reached through the exact skip-don't-raise path that exists to keep a
  bad file from costing more than itself. Fixed by treating a zero-frame
  decode the same as a failed one.
- **`through_a_wall` reached `np.fft.rfft` with `n=0`** on a zero-length input
  buffer, which raises rather than returning something empty. Fixed by
  returning the empty buffer directly before the transform is attempted —
  under the never-raises rule this layer is built on, a report of the fix
  once described it as "raising `ValueError`," which was simply wrong; the
  shipped code does not raise.
- **`_bed` (`night/stream.py`) ignored `SoundbedConfig.enabled`**, gating only
  on `noise_type`, so the default `NightStream` — and every test in the file
  — mixed in pink noise that the config's own `enabled=False` default said
  should not be there. Every other caller in the codebase (`pipeline.py`,
  `preview.py`) gates on `.enabled`; this was the one that didn't.
- **The CLI's `--seconds` handling treated `--seconds 0` as "run forever"**:
  `if seconds else None` reads `0` as falsy and silently discards it. Fixed to
  `if seconds is not None else None`.
- **The band-limit shoulder exponent specified for the radio treatment,
  `2.0`, left 10.3–11.1% of spectral power above 4 kHz** against the design's
  own stated target of under 2% — failing by roughly five times, confirmed
  across six seeds. `4.0` passed thin, at about 1.8%; the shipped value,
  `_AIR_SHOULDER_OCTAVE = 5.0`, sits at about 0.8%. The reviewer's own framing
  matters here: "not tuning to an over-tight assertion" — the number in the
  plan was wrong, not the requirement.

**The pattern, not the individual fixes, is the lesson.** Two of the six are
the identical FFT axis mistake, discovered twice in one file because nobody
went looking for the second instance until it was tripped over independently.
None of the six was caught by writing the code carefully the first time; all
six were caught by an implementer or reviewer actually running the numbers —
a failing assertion, a hang reproduced, a percentage measured — rather than by
reading the plan's code and trusting that a design document's own worked
example must be correct. That is the same lesson this document already
records once, at length, under Plan 4a's false safety proof: a plan document
is prose with the authority of code and none of the checking.

### The reverb pre-delay is trimmed in both callers — the argument that it should not be was wrong

`effects.apply_reverb`'s pedalboard backend shifts the *whole* buffer it is
given — dry signal included — forward by its pre-delay, and
`effects.reverb_dry_offset` exists to report exactly how far. Two places in
`night/` call `apply_reverb` on a buffer they then need to reason about
sample-accurately, and **both trim.**

`night/stream.py`'s `_rendered` trims it. A voice is cached once and then
sliced by `NightStream.block` using `voice.birth_frame` as the frame that
buffer's index 0 corresponds to — `offset = max(voice.birth_frame - start,
0)` and `take_from = max(start - voice.birth_frame, 0)` both assume that
identity directly. Left uncorrected, every voice's cached buffer would open
with roughly 40 ms of pre-delay silence the slicing arithmetic knows nothing
about, so frame 0 would quietly stop being the voice's actual birth and every
block that sliced into it would be off by that amount. The fix is one call to
`reverb_dry_offset` before the wet buffer is cached (Ruling 17 above).

`night/speech.py`'s `through_a_wall` now trims it too, and this section used
to argue at length that it should not. **That argument was wrong, and the
sentence it turned on was factually false.** It read: "nothing downstream
indexes into its output expecting a particular sample to be a particular
moment." `player.py`'s `_speech` calls `through_a_wall` once per block and
the player concatenates the results, which *is* exactly such an
expectation — the last sample of one treated block is expected to be the
sample immediately before the first sample of the next. Being continuous
background rather than an onset-critical signal made no difference to that,
and the phrase "a 40 ms shift in a wall-muffled murmur has nothing to be
misaligned against" was answering a question nobody had asked: the problem
was never alignment against another layer, it was alignment against the
block before it.

What the omission actually produced, measured at 12 ms of pre-delay: every
treated block opened with 12 ms of **exact digital zeros**, so the seam step
into that silence was 4.2x the largest transition anywhere inside the block,
and the whole pattern repeated at 0.1 Hz for the length of the night. It also
silently discarded 12 ms of source audio per block, because the buffer was
truncated back to length from the *front* rather than trimmed. Both effects
are precisely the class of thing — a periodic click, a periodic gap — that
this program's entire design is arranged around avoiding.

Two general lessons are worth keeping out of this, because neither is about
reverb. The first: a claim of the form "nothing downstream depends on X" is a
claim about every caller, and it was made here without checking the one
caller that existed. The second: the omission was *reasoned about* and given
a section defending it, which made it look considered rather than missed —
a wrong explanation is harder to find than no explanation at all.

### Three guards on this branch looked like protection and were not

- **The rule that no shipped pipeline module may import `sleepmix.night` was
  asserted only in a docstring, with nothing checking it**, until a reviewer
  flagged the gap and a test was written for it
  (`tests/test_night_sky.py::test_no_shipped_module_imports_the_night_package`).
  A convention nothing checks is a convention that decays silently.
- **Two import guards used a plain substring search on source text**, and
  both were too weak in the same way: `"sleepmix.audio" not in source` misses
  `from sleepmix import audio`, and `"sleepmix.night" not in source` misses
  `import sleepmix.night` spelled with a different statement shape. The first
  fix replaced the substring search with an AST walk and was **still**
  bypassable, because parsing alone buys nothing if the comparison afterward
  is still an exact dotted string: a relative import (`from ..audio import
  X`) and an absolute one (`from sleepmix.audio import X`) name the same
  module and produced different answers. A re-review executed the guard
  against every spelling it could construct and found **seven slip through**
  across the two guards: `from sleepmix import audio`, `from ..audio import
  X`, `from .palette import X`, `from . import palette`, and
  `import sleepmix.audio as a` on the plan guard; `import sleepmix.night` and
  `from . import night` on the layering guard. The working version
  (`tests/import_guard.py`) resolves every import to a fully-qualified dotted
  module name — accounting for the importing file's own package when
  resolving a relative import — and matches by dotted-prefix rather than
  string equality, so `from ..audio import X` inside `night/plan.py` and
  `from sleepmix.audio import X` are recognised as naming the same module.
  Verified by building a harness outside the repo and running the real guard
  against all sixteen spellings its author could think of plus three
  deliberately legitimate imports: sixteen caught, three correctly left
  alone.
- **`NightStream`'s own class docstring claimed cache-eviction purity was
  tested "by rendering the same block from two different instances,"** which
  is a real test but cannot exercise eviction at all — two separate instances
  never share a cache to evict from. Nothing in the suite constructed enough
  distinct voices against the 24-entry cache to force an eviction and then
  re-request an evicted one. The property held (verified by reading the
  code), but nothing would have caught a regression. A test was added that
  forces 25 distinct voices through a single instance's cache and confirms
  block 0's voice is provably absent from `_cache` before it is re-requested
  and re-rendered identically.

None of the three was found by looking for guards to distrust; each was found
because a reviewer tried to defeat the specific one in front of them. The
generalisable point, stated plainly because it is worth stating plainly: **a
guard nobody has tried to defeat is decorative.**

A fourth of the same shape surfaced when the branch was handed over: **both
cache tests asserted `len(_cache) <= 24`, a number that stopped corresponding
to anything the moment the cache moved from an entry ceiling to a byte
ceiling** — and which a 256 MB cache satisfies trivially at the test suite's
22.05 kHz. Worse, *nothing asserted the byte bound at all*: deleting
`self._cache_bytes -= evicted.data.nbytes` from `_rendered` would let the
running total climb forever, collapse the cache to a single entry, and thrash
every voice on every block, and the whole suite would still have gone green.
The assertions now check the bound the code is actually written against
(`_cache_bytes <= _CACHE_BYTES`), that the running total equals the bytes
really held (`sum(buf.data.nbytes ...)`, which is the assertion that fails if
the subtraction is ever lost), and that more than one entry survives — so a
thrashing cache is a failure rather than a silent slowdown. The mutation was
run to confirm it: with the subtraction deleted, both tests fail with
`assert 1746182320 <= 268435456`.

### The queue's own degradation path arrived with a loop in it

The render-ahead queue was added late on this branch, and it changed what the
fallback bed *is*. Before the queue, `NightPlayer.fallback_block` was reached
only when a render raised — an exception path, rare by construction. After it,
the queue draining is the ordinary way a slow renderer degrades, and the spec
names it as such ("the block queue drains into a bed the *player*
generates"). A path that went from exception-only to routine arrived carrying
two defects that nobody would have noticed while it was rare.

**Every fallback block in a run of them was byte-identical.** `run`'s
`next_music_index` advanced only when a real block arrived from the queue; on
the `queue.Empty` path it was used and not incremented. `fallback_block` is a
pure function of `(seed, "night:fallback", index)`, so a thirty-second stall
played one ten-second noise loop three times. Measured with the renderer
slowed to 1 s per block, before the fix:

```
peaks: [0.2009, 0.0121, 0.0121, 0.0121, 0.2022, 0.0119, 0.0119, 0.0119]
  block 2 identical to block 1, block 3 identical to block 1
```

Repetition and pattern are exactly what this design argues wake people, and
this design goes to some length elsewhere — per-block noise keys, a root that
descends by one semitone across eight hours — to avoid producing either.

**And the return to music stepped.** Music and the player's own bed differ by
more than a factor of ten in level and know nothing about each other, so
butting them together put a jump at the seam **7.58x** the largest motion
anywhere inside a block, against the 4x threshold that
`test_consecutive_blocks_join_without_a_step` and
`test_the_bed_joins_across_a_block_seam_without_a_step` both apply elsewhere
on this branch. The same metric, the same threshold, at the one boundary
neither test covered.

Both are fixed. The block counter advances on the empty path as well as the
full one, and never backwards — `max(next_music_index, index + 1)`, because a
renderer far enough behind hands over a block whose index the fallbacks have
already passed, and letting the counter rewind to it made the next fallback
repeat one from thirty seconds earlier. And a change of kind, in either
direction, is crossed over 75 ms rather than stepped
(`NightPlayer._cross_into`).

**The crossfade's outgoing material is the previous block's tail, reversed,**
which is the part worth explaining. By the time a kind change is detected the
previous block is already at the device — nothing can be faded out of it after
the fact — and there is no continuation of it to fade with either: if the
renderer had one, this would not be a fallback. Reversing the tail gives a
signal that *begins* on the exact sample the device last played and carries on
with the same spectrum and the same texture, so the step at the seam is zero
by construction rather than small by measurement. Time-reversed noise is
noise, and time-reversed drone is drone. Measured after the fix, the same run:

```
peaks: [0.2009, 0.1144, 0.0119, 0.0118, 0.2022, 0.1082, 0.0115, 0.0115]
  no two blocks identical
  seam ratios 0.00, 0.02, 0.49, 0.00, 0.00, 0.04, 0.35   (threshold 4.0)
```

None of this reaches the renderer: block independence is a property of
`NightStream`, and the crossfade happens downstream of it on the buffer about
to be handed to the device. One consequence for anyone reading a delivered
block: a bed that *opens* a stall now carries the music's level in its first
75 ms, so a whole-block peak no longer identifies which kind it is — the
tests judge that on the back half of the block instead.

### A diagnosis that measurement overturned

The three listening excerpts rendered for this branch (`night-2230.wav`,
`night-0100.wav`, `night-0400.wav`, at the repo root, gitignored by the blanket
`*.wav` rule) show spectral centroid **rising** across the night rather than
falling: roughly 7557 Hz at 22:30, climbing to roughly 9578 Hz by 04:00, while
loudness (RMS and peak) both fall as intended.

**The first explanation offered for this was wrong, and the correction matters
more than the original diagnosis did.** The first hypothesis was that the
fixed-spectrum pink-noise bed was dominating the mix once the voices had
darkened enough — plausible, and it came with a fix (darken the bed alongside
the arc, in `_soft_lowpass`). But that fix was built on top of an unrelated
defect: the bed was audible at all only because `_bed` was ignoring
`SoundbedConfig.enabled` (see above), so the numbers the hypothesis was
argued from were measuring a bug rather than the design. Once the enabled-flag
bug was fixed and the bed correctly silent by default, the same three files
were re-rendered and re-measured — and the centroid moved by under 1%. The
bed was never what lifted it.

**The real mechanism is `disintegration.apply_decay`'s rising noise floor.**
It adds broadband hiss at an *absolute* level, independent of how quiet the
voice's own tonal content has become, while the voice's own amplitude is
simultaneously pulled down toward the arc's falling `level_db` ceiling. The
two together mean hiss becomes proportionally more of the signal exactly as
the tonal content is darkening — which is the tape gesture working precisely
as specified (surfacing hiss as the material erodes), not a defect in it.

**Whether a night that grows *hissier* as it grows *quieter* is the right
shape for a sleep tool is an open question, and it is the operator's, not an
engineering one this document can close.** It is the single most important
thing recorded in this section. It now has a number attached to it — a rise
from about 7557 Hz to about 9578 Hz over the course of a modelled night —
rather than only the impression a listener might form. Whether that number
describes something worth changing can only be answered by someone who has
actually fallen asleep to it.

**Postscript: the mechanism was right, the level was a bug, and the numbers
above are now historical.** The hiss really was `apply_decay`'s noise floor;
what the diagnosis did not notice is that `plan._decay_for` never set it, so
it sat at `StemDecayConfig`'s `-42 dB` default — an *absolute* level with no
relationship to the arc at all. A voice born at hour six carried exactly the
same hiss as one born at hour zero, under a level ceiling 18 dB lower and a
brightness ceiling twelve times lower. That is not the tape gesture working
as specified; it is the tape gesture escaping the constraint every other
quantity in the night is under. The floor is now pinned to `arc.level_db`
(`plan.NOISE_BELOW_LEVEL_DB`, -40 dB under it), and the same three excerpts
re-measure at **873.7 Hz / 1302.8 Hz / 1303.5 Hz** — an order of magnitude
down, and flat rather than climbing after 01:00. A residual rise from 22:30
to 01:00 remains and is carried by the voices, not the bed (bed centroids
353 / 201 / 100 Hz across the same three hours). Whether *that* is right is
still nobody-has-listened territory, and -40 dB is still a taste value.

### The listening judgement is still outstanding

No agent has ears, and this branch does not pretend otherwise. Every one of
the three listening tasks in the plan for this branch produced *objective*
measurements only — RMS, peak, spectral centroid, voice count, per file — and
was explicitly instructed not to render a verdict on how any of it sounds,
because doing so would convert an honest open question into a false
completion. Nobody has slept through a night this branch produced. Every taste
value below, and everything the previous section raises about the rising
centroid, is unvalidated until someone does.

The three excerpts were re-rendered after the whole-branch fix wave, from the
same seed, the same modelled night and the same three hours, now with the
sound bed on as `sleepmix night` ships it. They are at the repo root and
gitignored:

| File | RMS | RMS dBFS | Peak | Peak dBFS | Spectral centroid | Voices | Digital silence |
|---|---|---|---|---|---|---|---|
| `night-2230.wav` | 0.08029 | -21.9 dB | 0.48566 | -6.3 dB | 873.7 Hz | 3 | 0.00% |
| `night-0100.wav` | 0.01241 | -38.1 dB | 0.05967 | -24.5 dB | 1302.8 Hz | 1 | 0.00% |
| `night-0400.wav` | 0.00643 | -43.8 dB | 0.04321 | -27.3 dB | 1303.5 Hz | 1 | 0.00% |

Against the previous render: RMS down 4.7-6.9 dB (`palette._PEAK` fell from
0.35 to 0.20), peak down 4.6-6.9 dB, and spectral centroid down by roughly an
order of magnitude and no longer climbing after 01:00. These are measurements
and nothing else. **Nobody has heard them.**

### The placeholders, and why they are placeholders rather than bugs

Every value below is a named constant with a real number in it — none is a
`TODO` or an unwritten step — and every one is invented rather than measured.
They are recorded here, as the spec that introduced them required, so a
future reader does not mistake a first draft for a considered value. The
person who can actually fix any of them is the one who has slept through a
night produced with them, which as of this section is nobody.

- **`MIN_NIGHT_S` / `MAX_NIGHT_S`** (`night/context.py`) — 6 and 10 hours,
  clamping the sunrise-derived night length. Invented so that starting at
  3 AM in June does not compress the whole descent into ninety minutes and an
  arctic winter does not stretch it into something that never audibly moves;
  neither bound has been checked against an actual night.
- **`NEUTRAL_WEATHER`** (`night/context.py`) — the `Weather` used whenever the
  forecast call fails, is slow, or returns something the module does not
  recognise: 50% cloud, no precipitation, 3 m/s wind, sea-level pressure, flat
  trend. Meant to read as an unremarkable night; "unremarkable" is a guess.
- **`_INTERVALS_CENTS`** and **`ROOT_DESCENT_SEMITONES`** (`night/plan.py`) —
  the consonant interval set a voice may sit at above the night's one root
  (unison through a fifth above the octave, no thirds), and the rate the root
  itself falls across a whole night (one semitone). The spec calls these "the
  most taste-dependent numbers in the design," and both are first drafts.
- **The four arc endpoints** (`night/clock.py`) — `_DENSITY_START`/`_END`
  (1.0 → 0.05), `_BRIGHTNESS_START_HZ`/`_END_HZ` (6000 → 500), `_LEVEL_START_DB`/`_END_DB`
  (0 → −18), `_INTELLIGIBILITY_START`/`_END` (0.80 → 0.03). Every quantity the
  night arc governs, at both ends of its descent, invented rather than
  measured.
- **`_AIR_SHOULDER_OCTAVE = 5.0`** (`night/speech.py`) — corrected once
  already during this branch's own review (from 2.0, which failed its own
  band-limit target by roughly 5×; see above), and still a first-draft number
  rather than a measured one. See the open design question about it below.
- **`NOISE_BELOW_LEVEL_DB = -40.0`** (`night/plan.py`) — how far under the
  night's level ceiling a voice's tape hiss sits, added by the whole-branch
  fix wave to stop the floor being an absolute number the arc could not
  reach. -40 dB was chosen so a fresh voice's hiss sits well under its own
  tone. **Nobody has listened to it**, and the question it decides — how much
  tape a night should have in it — is exactly the sort the operator's ears
  own. It is the most consequential of the values in this list, because it
  moved the measured spectral centroid of a three-minute excerpt by an order
  of magnitude.
- **`_PEAK = 0.20`** (`night/palette.py`) — how loud one voice is before the
  arc scales it. Unlike its neighbours here this one *is* measured, against a
  headroom requirement (worst pre-clip block peak across seven seeds: 0.76),
  but the requirement only bounds it from above. Nothing says a night should
  not be quieter still.
- **`_TREATMENT_CEILING = 0.5`**, **`_ROOM_XFADE_S = 0.08`**,
  **`_ROOM_PREFETCH_LEAD_S = 120.0`** and **`_RADIO_BUFFER_S = 20.0`**
  (`night/speech.py`); **`_BED_OVERLAP_S = 0.25`** (`night/stream.py`);
  **`_QUEUE_WAIT_S = 0.25`** and **`_PRIME_WAIT_S = 5.0`**
  (`night/player.py`). All from the fix wave, all invented. None is a taste
  value in the way the arc's endpoints are — they are engineering slack, and
  the failure mode of each is visible in a measurement rather than only in a
  listener's judgement — but none has been tuned against a real device, a
  real network or a real forty-minute media file either.

**One more environment variable exists and is not part of the documented
surface.** `cli.py`'s `night` command also reads `SLEEPMIX_SEED`, defaulting
to a random 31-bit value when unset — useful for reproducing a specific
night exactly, since the spec's only stated reproducibility guarantee is "the
seed plus the date reproduces a night." It is not named in the command's own
`--help` text (`SLEEPMIX_LAT`, `SLEEPMIX_LON` and `SLEEPMIX_RADIO_URL` are the
three asserted there, in `tests/test_cli.py::test_night_help_exits_cleanly_and_documents_the_env_vars`)
and nothing in the test suite exercises it. It works; it is simply
undocumented, which is worth recording precisely because "the only
configuration there is, on purpose" is the claim the README makes about the
other three.

### Deviations from the spec, each with its reason

- **`RadioSource` reads a live HTTP/Icecast stream (`night/speech.py`'s
  `_open_stream`, via `soundfile.SoundFile` over a streamed `requests` GET),
  not a KiwiSDR websocket.** The design spec named KiwiSDR — roughly 800
  public shortwave receivers, tunable over a websocket via `kiwiclient` — as
  the deliberate choice over Broadcastify or LiveATC, for real ionospheric
  static and receiver etiquette a websocket protocol would need to respect.
  That protocol could not be specified correctly without first reading
  `kiwiclient`'s own implementation, and approximate protocol code — code that
  looks like it speaks a wire protocol but was never checked against the real
  one — is worse than no code at all, because it fails in ways nobody can
  distinguish from success until a real receiver is on the other end. An
  ordinary HTTP audio stream needed no such research and stands behind the
  same `SpeechSource` interface a `KiwiSource` would use; building that is the
  named follow-up, not a redesign.
- **Binaural beats are absent from the night bed.** `night/stream.py`'s `_bed`
  generates only noise, never the periodic binaural tone
  `sleepmix/soundbed.py` already knows how to build for a finite render. A
  tone generated fresh per ten-second block restarts its own phase at every
  block seam, which clicks — audibly, at the exact boundary the whole design
  is built to keep silent. The fix needs absolute elapsed time carried into
  the tone generator so a block's tone picks up where the previous block's
  left off, which nothing in the current per-block generation model supplies.
  Deferred rather than shipped broken.
- **One of the six steering rows does nothing, as of this commit — wind.**
  The spec's steering table gives it "depth of the drones' slow amplitude
  drift," but drift lives entirely inside `night/palette.py`'s `_slow_drift`,
  which receives only `(n, sr, rng)` and no `NightContext` at all. Threading a
  context into the palette to reach it would put steering logic in a second
  place at the same level, against the rule stated at the top of
  `night/clock.py` and enforced nowhere but by that rule being followed. It is
  dead as the branch is handed over, and no promise is made here about when it
  will not be.

  **Moon phase was the second dead row and is now implemented.** For most of
  this branch's life `NightContext.moon_phase` was computed in `sky.py`,
  carried into the context, and read by nobody: `clock.py`'s
  `_brightness_multiplier` reads cloud, rain, pressure trend and season and
  never touched it, and `plan.py` drew a voice's interval from the fixed
  `_INTERVALS_CENTS` tuple with a uniform `rng.choice`. The spec's own row for
  it is "width of the interval set," and the operator selected moon phase by
  name when asked which inputs the stream should read, so it was undelivered
  scope rather than an optional extra. `plan.interval_set(moon_phase)` now
  supplies it: openness is `1 - 2 * |phase - 0.5|`, and it selects how many of
  `_INTERVALS_CENTS` are reachable, from four at new moon (unison, second,
  fourth, fifth) to all six at full (adding the octave and the fifth above
  it). It lives in `plan.py` rather than `clock.py` because an interval set is
  not one of the arc's four descending ceilings — see `docs/architecture.md`
  — and emphatically not in `palette.py`, which still receives no context. The
  draw stays a fixed-width slot into the whole tuple, folded into the
  reachable set, so the moon cannot move a single birth time
  (`test_no_moon_moves_a_single_birth`); at full moon the plan is bit-identical
  to what it was before the moon reached it.

  **The history of this paragraph is worth keeping.** An earlier version of it
  stated the opposite of the truth about a feature the operator asked for by
  name, and a version after that said moon phase was "scheduled for the
  branch's final fix wave" when it was not in that wave's brief and did not
  land. This document exists specifically to prevent false confidence about
  what is implemented, so both the wrong claim and the quiet promise are
  recorded here rather than deleted along with the gap they described.
- **The spec's own memory figure for the voice cache is wrong and is left
  standing.** `docs/superpowers/specs/2026-08-18-night-stream-design.md` says
  "Voices are minutes long and there are three or four at a time, so the cache
  is a few tens of megabytes." A *voice* is a few tens of megabytes (52.7 MB
  average, 86.6 MB peak, at 44.1 kHz); the 24-entry cache built on that
  sentence was 1.27 GB. The spec is the binding design document and is not
  edited retroactively, so the correction lives here and in
  `docs/architecture.md`, and the code is bounded by bytes rather than by
  entries. A reader who reaches the spec's sentence first should treat this
  paragraph as its erratum.
- **The stream did not stop; it held. It stops now.** The design spec's
  "Control surface" section states the intended behaviour plainly: "Phase 1
  descends toward near-silence over an assumed night and stops." What shipped
  did not do that — with no `max_blocks` (the case `sleepmix night` actually
  ran, since `--seconds` is explicitly for trying it out) `NightPlayer.run()`
  looped indefinitely, and `night/clock.py`'s `arc_at` clamps time outside the
  night to the arc's own quietest values rather than raising or signalling an
  end
  (`tests/test_night_stream.py::test_a_block_past_the_end_of_the_night_still_renders`,
  whose own docstring says so: "the arc clamps rather than ending, so the
  stream never runs out"). A night descended to near-silence and then held
  there — the audible target the spec wanted — but nothing ended the process;
  `cli.py` printed "Ctrl-C to stop" because Ctrl-C was, in fact, the only way,
  and `sleepmix night` would still have been playing at noon. That was a third
  behaviour nobody chose: not the spec's ending, and not an honest
  "indefinite" either.

  **Closed.** `cli.py` now derives `max_blocks` from the night's own length —
  `ceil(ctx.night_length_s / BLOCK_S)` — whenever `--seconds` is absent, and
  `--seconds` still overrides it
  (`tests/test_cli.py::test_a_night_with_no_seconds_is_bounded_by_the_nights_own_length`,
  `::test_seconds_still_overrides_the_nights_own_length`). Nothing about the
  sound changed: the arc still clamps at its quietest past the end, so the
  rounding-up that keeps the last of the descent from being clipped costs at
  most one block of already-clamped audio. What changed is that the process
  ends. `run()` itself still accepts `max_blocks=None` and still loops
  forever on it — that is what
  `test_run_gives_up_after_consecutive_sink_failures_rather_than_looping_forever`
  needs in order to prove anything, and the player is not the layer that knows
  how long a night is.

### `RadioSource` never reconnects, and that is deliberate

Every failure a live HTTP stream can produce — a refused connection, a DNS
failure, a stream that stops mid-night, a decoder that gives up — lands in the
same place: `RadioSource._fill_loop` returns, the ring drains, and the source
goes permanently quiet for the rest of that night. Nothing retries and nothing
rotates to a backup feed.

There is no dead *flag*, and that is deliberate rather than an oversight. A
`_dead` attribute was set on all four of those paths and read by none of them
— written four times, consulted zero. The only place it could have been
consulted is a short-circuit at the top of `read`, and that would discard the
audio that had already arrived before the connection dropped, which
`test_a_radio_source_that_dies_mid_night_goes_silent_once_it_drains` exists
specifically to assert still plays out. So it was removed rather than wired
up: deadness is a state `read` already answers correctly by finding nothing
available and writing zeros. The class's own docstring states the reasoning directly: "a retry loop
inside the playback path is a stall inside the playback path, and there is no
version of 'the network came back' that is worth a gap in the audio at 3 AM."
A dropped feed is permanent for that night, by choice, not by an unhandled
case. If this proves too blunt in practice, the fix that was considered and
rejected for Phase 1 is a reconnect running on a background thread that swaps
a freshly-opened source in when it succeeds — never a retry attempted from
inside the read path where it currently fails, which is exactly the stall the
design was built to avoid.

### What Phase 1 leaves for a later task, on purpose

- **The bed-enabled path is unreachable in Phase 1, and its darkening is
  untested.** `SoundbedConfig()` defaults to `enabled=False`, `sleepmix night`
  takes no options, and nothing in this plan turns the bed on. The
  arc-darkening fix described above (`_soft_lowpass` in `_bed`) was verified
  by reading rather than by an automated test — finite output, correct shape
  and dtype, centroid rising monotonically with cutoff across a swept range —
  and the decision to leave it untested was made explicitly on the grounds
  that unreachable code does not carry the same cost as reachable code left
  untested, after three earlier findings on this same branch had gone the
  other way. Whoever first enables the bed inherits this gap.
- **A block-seam artefact in the same, currently unreachable, path.**
  `_soft_lowpass` runs a whole-block FFT roll-off over noise that was already
  generated independently per block, so a circular-convolution edge effect is
  possible at block boundaries, stacked on top of the pre-existing per-block
  noise discontinuity the bed already has. Both belong to the same future
  "turn the bed on" task.
- **An open design question about `_AIR_SHOULDER_OCTAVE = 5.0`.** At that
  value the radio treatment's band-limit shoulder falls at roughly
  30 dB/octave, against the room treatment's wall filter (`_lowpass_fft`'s
  fixed `-1.6` exponent) at roughly 9.6 dB/octave — a steep shoulder, and the
  piecewise corner it creates has a slope discontinuity that sharpens as the
  exponent grows. There is no IIR-style resonance here — no poles, nothing
  that can ring in the classical sense — but a kink in an FFT-domain window
  is exactly the mechanism by which mild time-domain pre- and post-ringing
  gets into a signal, and nothing in the test suite asserts its absence. A
  raised-cosine transition in place of the current hard piecewise corner is
  the fix, if listening ever finds the ringing audible.

### The `cli.py` layering exemption, and why it is scope-conditional rather than blanket

The rule that no shipped pipeline module may import `sleepmix.night` has one
exception, in `cli.py`, because `cli.py` is where the `sleepmix night`
subcommand necessarily wires the package in. The exemption is narrower than
"this file is exempt": `tests/test_night_sky.py`'s guard checks every import
in `cli.py` too, but only at module scope — an import inside the `night()`
function body is allowed, an import at the top of the file is not. That
distinction is the whole content of the rule, not a simplification of it.
Every one of `cli.py`'s `sleepmix.night` imports already lives inside the
`night()` function, following the same graceful-degradation pattern the rest
of the CLI uses for `uvicorn`, Demucs, and every other optional dependency —
which means it only runs when the subcommand is actually invoked, so
`import sleepmix` and `sleepmix render` both survive `sleepmix/night/` being
deleted entirely, and only `sleepmix night` itself would break. A blanket
file-level exemption would also have silently permitted a *module-scope*
`import sleepmix.night` in the same file, which genuinely would break that
removability guarantee — the first implementation shipped the blanket form,
correctly flagged as an acceptable fallback if the narrower one proved
awkward, and it was tightened to the scope-conditional version in the same
fix round rather than left as the easier answer, because the AST walk already
had everything it needed to make the distinction.

## Plan 4a: placement becomes a plan

`feat/arrangement`, 7 tasks, complete. This is the first third of a three-part
design (`docs/superpowers/specs/2026-08-08-arrangement-design.md`): 4b gives one
song several segments dissolving on their own clocks, 4c blends several source
files into one mix. 4a is the smallest of the three and was deliberately built
first, for a reason the spec states up front — it is also the piece most likely
to lock in a placement model the other two cannot live inside, so the whole arc
was specified in one document before the smallest part of it was built.

What shipped: `ArrangementConfig` with three fields; `sleepmix/arrangement.py`,
a pure planner with no audio anywhere in it; `disintegration.render_arrangement`
rendering a plan and applying the seam rule; `pipeline` and `preview` both
reading the same plan; `preview.master_gain` finding the window it measures
instead of assuming it; and the regression that made the whole thing safe to
land — at default gaps the planner places repeats at exactly the frames the
previous renderer did. **No frontend work whatsoever**: the mixer generates the
new section from `/api/schema`, which is what the schema-driven design in
`ui/README.md` exists to buy. `docs/architecture.md`'s new section, "The
arrangement seam", has the mechanics and the arguments; this section is what a
reader needs that is not mechanics.

### `ArrangementConfig` ships three fields, and four more are deliberately withheld until Plan 4b

The design spec's config block has seven fields. Three of them shipped —
`gap_start_s`, `gap_end_s`, `gap_curve`. The other four — **`segments`,
`segment_overlap`, `lifetime_jitter`, `order`** — are Plan 4b's, and they are
deliberately *not* present in the dataclass, not even as unused defaults.
**This is the placeholder record, written here so it is not lost**, and the
reason it is a real decision rather than tidiness is a specific property of
this codebase:

**every field on a dataclass registered in `config._SECTION_TYPES` automatically
becomes a control in the mixer.** That is the whole point of the schema-driven
frontend — `config_schema()` walks the fields, `Page.Mixer` turns each one into
a slider, a select or a typed box by one rule, and nothing in Elm names a
config parameter. Add a field to `sleepmix/config.py` and it appears on screen,
editable and round-tripping, with no frontend change at all. So a field added
early "ready for 4b" is not inert and is not harmless: it is four controls in
front of the operator that do nothing, and — worse — that *look* like they
work. The schema would carry their labels, bounds and help text, `Config.set`
would clamp and round-trip them, a preview would come back at 200, and the only
thing that would not happen is the sound changing. There is exactly one other
way to withhold a control — have `Page.Mixer` name the field and refuse it, as
it does for `separation_model` — and that means a frontend change and four more
names written into Elm, against a frontend whose whole rule is that it names no
config parameter it does not have to, for four fields that become real in the
very next plan. Not having the
field is cheaper and says the same thing. The cost of
adding them in 4b instead is one dataclass edit; the cost of adding them now is
a lie on screen for however long 4b takes.

The same policy runs one level down: `plan_arrangement` raises
`NotImplementedError` naming Plan 4b when handed anything other than exactly
one `SegmentInfo`, rather than quietly planning the first one. `MIN_STRIDE_FRACTION` (a tenth of a
segment) is a floor on the stride for the same family of reasons — below it an
overlap stops being an overlap and starts being a comb filter, and one config
could turn a twenty-minute target into millions of placements.

### `plan_iterations` has no production caller left, and it must not be deleted

`disintegration.plan_iterations` is now reachable in production from nothing.
`run_pipeline` goes through `plan_arrangement` and `render_arrangement`;
`preview.preview_iteration_index`, which used to call it, reads the plan
instead. Its one remaining caller is `build_disintegrating_stream`, which is
itself now only called from the test suite.

**It is retained on purpose, as the regression oracle.**
`tests/test_arrangement.py::test_defaults_reproduce_todays_positions` asserts
that at default gaps the planner produces exactly the frames and exactly the
count `plan_iterations` does — parametrised over six targets rather than one,
because mutating the stopping rule's `>=` to `>` only diverges when the target
lands exactly on `L + k * stride`, which an arbitrary round-seconds duration
essentially never does by chance. That test is the thing that made it safe to
replace the one line this whole plan lives at. An oracle deleted as dead code
takes its regression with it, and the regression is not re-derivable from the
new code, because the new code is what it exists to check.

One small inaccuracy is left standing rather than fixed, because Task 7 changed
no code: `plan_iterations`' own docstring still says it is "shared by the batch
stream builder and the preview path". The preview half has not been true since
Task 5.

### A false safety proof shipped in the plan document, and it would have discarded a voice

This is the incident this branch is most worth remembering for, and it
originated in the plan text rather than in the implementation.

Task 3's `render_arrangement` docstring, as written in
`docs/superpowers/plans/2026-08-08-arrangement-placement.md`, argued that the
crossfade branch may *assign* into the overlap region rather than adding to it,
"which is only safe because no third repeat can reach it: the crossfade branch
runs when the overlap is at most `xfade`, `xfade` is clamped to half a segment,
so the stride is at least half a segment and the repeat two back has already
ended."

**Every step of that is true about the wrong stride.** The branch condition
constrains only the stride *into this placement* — the one from `i-1` to `i`.
It says nothing at all about the stride from `i-2` to `i-1`, which is floored
at `MIN_STRIDE_FRACTION`, a tenth of a segment. Those two can therefore sum to
0.6 of a segment while a third repeat is still sounding: a heavy stack
immediately followed by a seam, which is exactly what a gap arc crossing from
negative to positive produces, from ordinary settings, at the **default**
`output.cycle_crossfade_ms` of 800 ms. The assigning version ducked that third
voice to silence through the overlap and snapped it back afterwards — up to
**~0.92 s of a third voice discarded** in the worst case observed. No test saw
it, because every test in that file used two placements, or three with no
overlap at all.

The shipped code does not assign. It blends against the *previous placement's
own chunk* and adds the difference in — so whatever else already sits in that
region survives untouched, however many earlier voices put it there. That is
**additive-safe by construction**, which is a strictly stronger property than
the one the proof was reaching for, because it does not depend on any bound on
how far back an overlap can reach.
`tests/test_disintegration.py::test_a_seam_after_a_stack_keeps_the_stacked_voice`
pins the case the argument would have silently dropped.

**The plan document has been corrected in place**, not annotated with a note
beside the original, because Plan 4b will be written against that document and
would otherwise inherit the proof intact. The generalisable lesson is not
"check the crossfade branch": it is that a *reachability* argument — nothing
else can be here, therefore overwriting is safe — is worth exactly as much as
the bound it rests on, and this one rested on a bound that constrained a
different quantity than the one the conclusion needed. Where a cheap
construction is safe unconditionally, prefer it over a proof that it is safe
conditionally.

A second defect of the same family was found in the same task's review and is
worth recording beside it, because the shape repeats: `plan_arrangement`
appended a position to the list and only *then* checked whether it was still
short of the target. At zero gaps the two orderings are indistinguishable —
every stride is at most a segment length, so a position computed from an
in-range one is still in range — which is why the tests, all of which ran at
default gaps, never saw it. Once the gap arc goes positive a single stride can
leap clean past what is left of the target, and `render_arrangement` then wrote
past the end of a buffer sized from `target_frames`, surfacing as a bare numpy
broadcast error naming nothing. A sweep found 320 of 972 legal configs
affected. The fix lays a position down only while it is still in range, and
`MalformedArrangement` was added as a named guard for any `Arrangement` that
arrives from somewhere other than the planner; the re-review swept 13,608
configs with real rendering and found none failing.

### The density ratio is an estimate, and this is its measured error

`preview.master_gain` now measures the window carrying the most concurrent
amplitude rather than assuming it is the first one, and scales that window's
measured peak by a **density ratio** — how much more amplitude is sounding at
that frame than in the single window it actually rendered. The ratio is
computed by combining per-placement amplitude proxies by **root-sum-square**:
the standard estimate for how *independent* sources add, which is close to what
stacked repeats are (the same loop at different decay stages, offset by a full
stride) and not identical to it. This is an estimate, so its error is recorded
as a quantity rather than as a caveat.

Ground truth for all of the figures below is the actual peak of 40 real
`render_arrangement` streams — 8 content types × 5 stacking depths — not a
model of one.

- **Root-sum-square, broadband and percussive content:** worst case **±7.7 dB**,
  signed mean **+2.2 dB**. The sign matters: over-predicting the concurrent
  amplitude makes the ratio too large, the gain too small, and the preview a
  little *quiet* — which reads as more decayed than the render is.
- **Root-sum-square, tonal content:** it *under*-predicts, by up to **≈10 dB**
  at ten concurrent placements. That direction is the dangerous one. Too small
  a ratio makes `gain = target / (peak × ratio)` too *large*, so the preview
  plays **louder** than the render — the same direction as the ~4 dB-hot defect
  `master_gain` exists to correct in the first place, at more than twice the
  size.
- **Plain summation**, which was implemented first and measured wrong: worst
  case **+17.7 dB**. It assumes the concurrent repeats are coherent — in phase,
  adding sample for sample — and mostly they are not.
- **An exponent sweep** against the same ground truth puts the empirical
  optimum at **p ≈ 1.75**, about 0.9 dB better worst-case than root-sum-square's
  p = 2. `p = 2` ships anyway. Trading a principled, standard estimator for a
  tuned constant fitted to 40 measurements buys about a decibel and costs the
  ability to say why the formula is that formula.

**The stride-locking finding is the most useful thing learned here, and nobody
is going to re-derive it.** Two reviews disputed whether summation or
root-sum-square was right, one arguing from broadband measurements and one from
a tonal counter-case, and both were describing the same effect from different
sides. **Whether stacked repeats add coherently is a property of the *stride*,
not of the content.** A 220 Hz tone whose gap makes the stride an exact whole
number of periods gives a plain-sum error within **0.07 dB** — summation is
essentially exact there. The same tone at **233 Hz**, nothing else changed, and
the plain sum is **+10.3 dB** out, no better than its broadband case. Coherent
copies can also *cancel* rather than add: one configuration whose stride landed
on a half period measured a true peak ratio of **1.92** against a plain-sum
prediction of **3.92**. So "summation wins for tonal material" was never a
content rule — it is "summation wins when the stride locks to the period",
which is a knife-edge in a continuous parameter rather than a class of audio.
There is no cheap classifier that could pick the better formula per case, which
is why one estimator is used everywhere.

The looseness is tolerated rather than closed, and the reason is what the factor
is *for*: a real render is peak-normalized from its own genuine audio by
`normalize_peak`, which reads the true peak wherever it falls and cannot be
fooled by this estimate. The density ratio only has to put a preview window in
the neighbourhood of the render's level for a tuning judgement to stay
meaningful. It does not, and from one rendered window cannot, protect a render
from clipping.

### Open question for the operator: a repeat with nothing after it stops dead

**This is a design question the spec never decided, not a defect, and it is
recorded here rather than answered unilaterally.**

With gaps in play, a repeat that has nothing following it now simply ends at
whatever amplitude it had reached — a hard step to zero, which will click. It
is most audible on a heavily stacked configuration, where a stacked voice ends
in the middle of everything else rather than at the end of the mix.

This could not happen before Plan 4a: every repeat crossfaded into the next one,
so the amplitude was always handed over rather than dropped. The arrangement
design spec specifies the seam rule for repeats that *do* have a neighbour —
crossfade, sum, or silence — and says nothing about the case where nothing
follows. The options are roughly: fade every placement out over the crossfade
width when nothing overlaps its tail; fade only in the additive branch; or leave
it, on the grounds that at the default zero gap every repeat still has a
successor and the click only appears in configurations the operator reached for
deliberately. Each has an audible consequence, and choosing between them is a
taste decision about what stacking should sound like, which is the operator's.

### Three smaller things found and deliberately left

None of these is audible today and each will be reached by Plan 4b, so they are
written down rather than fixed.

- **`gap_end_s` is never quite fully applied.** The gap is shaped by
  `elapsed = pos / target_frames`, and the layout loop stops before `pos`
  reaches the target — the last repeat begins a segment-length short of it — so
  `elapsed` tops out a little below 1.0 and the final gap lands a little short
  of `gap_end_s`. The shortfall is roughly one segment's worth of the mix —
  with a ~17 s loop in a twenty-minute mix, a couple of percent of the way up
  the curve: inaudible, and the `min(..., 1.0)` clamp in the
  code is dead as a result. It is the same shape as the decay-progress defect
  the two-pass layout exists to avoid, at a scale that does not matter, and
  fixing it means normalising `elapsed` over the last *placed* position, which
  is not knowable in pass one.
- **`render_arrangement` reads the loop's length, not the placement's.** It
  renders `loop.n_frames` per placement and ignores `Placement.n_frames`
  entirely. Today those are always equal — one segment, one length — so the
  plan's self-description and the renderer disagree only in principle. Plan 4b,
  where different segments have different lengths, hits it immediately.
- **A hand-built `Arrangement` is only partly checked.** `MalformedArrangement`
  catches a placement that does not fit the buffer, but nothing checks that the
  placements are sorted or that an overlap does not exceed a segment length; an
  unsorted plan still fails somewhere inside numpy rather than by name.
  `plan_arrangement` cannot produce either, so this only matters to a future
  planner or a test.

### What Plan 4a deliberately does not do

- **One segment, one source.** `find_loops`, per-segment lifetimes,
  `RenderSession` rekeyed to `(segment_index, stem)`, and the
  segments-found-versus-requested report are all Plan 4b; `ArrangementSession`,
  multi-source `run_pipeline`, the N-separations job model and the source cap
  are Plan 4c.
- **No arrangement preview.** `render_arrangement_window` — auditioning a real
  window of the arrangement at a chosen moment, overlaps included — belongs to
  4b, because it is not useful with one segment and it is essential the moment
  there is more than one thing sounding. Today's seamless single-iteration
  preview is unchanged, and remains the right tool for tuning a stem's decay by
  ear.
- **No visual arrangement editor, and no explicit placement list.** Both were
  ruled out in the design: the arrangement is parametric and seeded, so the same
  config plus the same seed produces the same mix and a preset stays a handful
  of numbers. A config naming every repeat would run to roughly two hundred
  entries for a twenty-minute mix, and a hybrid (generate, then patch individual
  repeats) is worse than either, because an override indexes into a generated
  list and changing any upstream parameter silently re-points every override at
  a different repeat.

## Plan 3d: presets, and the server's own defaults

Two gaps closed together, because the same mechanism closes both: a preset is
a named config snapshot, and the server's own defaults are values with
nowhere to live *as* a config until the mixer already knows how to accept
one.

**The mixer used to start every stem identical, which was a real audible
difference from what `sleepmix render` produces by default — closed by this
plan's `GET /api/config/default`.** A fresh mixer built `Config.fromSchema`
from `/api/schema` alone, and the schema has no way to describe a list, so it
could describe every stem's bounds but not that the shipped default has
`drums` off, `bass`'s decay off, `vocals` dissolving on an `exp` curve to
2200 Hz, and `other` to 2400 Hz — the curated shape `MixConfig`'s own
dataclass defaults carry. This document used to record that divergence in
detail, stem by stem, as an open gap under Plan 3b, with a note that closing
it properly needed the server to publish its own default config rather than
a copy of that list written out in Elm. `GET /api/config/default`
(`dataclasses.asdict(MixConfig())`, see `docs/architecture.md`'s new section
on it) is exactly that: a mixer now opens with the same starting point a
render does, and `Config.overlay` — the same function that lays a preset
over a config — is what turns those published values into one, so applying a
preset and loading the server's own defaults are one code path rather than
two that could drift apart.

**Presets can now be renamed or saved over, and a preset saved under its own
existing name is not treated as though it collided with itself.**
`PUT /api/presets/{id}` (`server/api/presets.py`) validates exactly as
`POST` does — a config that could never render is refused with a 400 before
it is stored, not discovered later at render time with the connection to the
bad value already lost — and checks the name collision explicitly rather than
catching the database's own `UNIQUE` violation, because the unique index
cannot tell "this name is taken by someone else" from "this name is taken by
the row being updated," and the second is the ordinary case of saving a
preset over itself. See `docs/architecture.md`'s new section for what a
preset deliberately still does not carry (the song's own loop region,
`separation_model`) and why.

**The mixer's preset bar (`ui/src/Page/Mixer.elm`)** is a row above the
controls, not a screen: choose a preset from a select, Apply it against the
song currently open, type a name and Save as a new one, Save over the
selected preset, or Delete it. Applying a preset means *make it look like
this*, not merge it in — a field the preset doesn't mention goes back to its
schema default, not to whatever the operator had it at a moment ago — except
the song's current loop region, which is carried across explicitly because a
preset never carries loop seconds belonging to a different piece of audio
(`Page.Mixer.applyPreset`, `docs/architecture.md`).

**`songs.last_preset_id` remembers which preset was last applied to a song,
as a hint and nothing more — deliberately never applied automatically.**
Reopening a song's mixer always starts from the server's own defaults; any
preset that had been applied to it has to be chosen again, from a line
reading "last used here" beside an Apply button. Auto-applying it was
considered and rejected: a preset is a shared, editable recipe, and a mixer
that silently re-applied one on open would mean that editing a preset later
silently changes the sound of every song ever pointed at it — including one
tuned and considered finished weeks earlier. `PUT
/api/songs/{id}/last-preset` records the id and nothing more; nothing reads
it except that one line of UI.

That id is deliberately not a foreign key, and deleting a preset a song
points at is an ordinary, unremarkable thing to do — verified directly this
task: deleting a preset a song's `last_preset_id` still names leaves the
song row holding the now-dangling id, `GET`s it back with no error, and the
mixer's own lookup against the (now shorter) presets list simply stops
finding it, so the "last used here" line quietly stops appearing. No
migration, no constraint, and no 500 anywhere in that path.

**What the final whole-branch review changed.** (1) `Mixer.applyPreset` built
its base from `Config.fromSchema` alone rather than sharing `Mixer.init`'s
base (schema defaults overlaid with the published ones) — the two agreed on
every scalar leaf, because a schema default already equals the dataclass
default, and diverged in exactly the one place `MixConfig` curates a list the
schema cannot describe: the stems. A preset silent about a stem, or applied to
a song whose stems didn't match the ones the preset was saved from, fell all
the way back to the schema's uniform values — drums enabled, vocals on the
wrong curve — with `defaultsNote` staying silent, because the defaults *had*
arrived. Fixed by pulling the shared base into `Mixer.baseConfig`, used by
both `init` and `applyPreset` now, with `Main`'s one production call site
threading `publishedDefaults model.defaults` through. (2) `GotDefaultConfig`'s
error branch unconditionally overwrote `model.defaults` with
`DefaultsUnavailable`, which used to be harmless because the fetch only ever
happened once per session; now that `OpenMixer` re-issues it on every open, a
transient failure arriving after an earlier fetch had already succeeded could
discard a `DefaultsReady` value that worked, regressing every later mixer in
the session to the schema's bare defaults for no reason a fetch failure this
time actually caused. Only `DefaultsLoading`/`DefaultsUnavailable` now move to
`DefaultsUnavailable` on error; `DefaultsReady` stays exactly as it was. (3)
That same overwrite was the only way `defaultsProblem`'s "could not be
fetched" sentence could render under a mixer that had, in fact, opened with
the real defaults — (2)'s fix closes this too, confirmed by reverting just
that guard and watching the contradiction reappear, not assumed. (4)
`applyBlock`'s "Choose a preset to apply" used to show beside a fully live
`lastUsedLine` Apply button whenever the preview was playable and nothing was
picked from the dropdown — that Apply needs no selection at all — reading as
if neither button worked; it now names the "Last used here" line as the live
alternative when one exists for the song. (5) Five stale documentation claims
about presets and the server's defaults, mostly found while tracing (1)
through the docs that describe it, are corrected in `README.md`,
`ui/README.md` and `docs/architecture.md`: an undercount of `setLastPreset`'s
call sites, an "always" a failed fetch actually falsifies, `other`'s decay
curve misattributed as `exp` when it is `linear`, a docstring pointer that
says nothing about what it's cited for, and a preset-save network-error
branch that does not exist in the suite.

**Five small things this plan's own reviews found and left, none of them
blocking:**

- **A check-then-act race survives in `_migrate_last_preset_id`** (added to
  `Store.__init__` to add `songs.last_preset_id` to a database that predates
  it). Two processes opening the same pre-migration database in the same
  instant could both see the column missing and both try to add it; the
  loser raises `sqlite3.OperationalError: duplicate column name` at startup.
  `Store` is a per-app singleton and this is a single-user desktop tool, so
  the failure mode is the loser crashing once and self-healing on the very
  next retry (the column exists by then) rather than any lasting
  inconsistency — ruled not worth a lock for.
- **`test_update_preset_keeping_its_own_name_is_not_a_collision` does not
  prove what its own docstring claims.** It was written to show that the
  explicit `AND id != preset_id` pre-check (`Store.update_preset`) is what
  lets a preset be saved over itself under its own name; a version that
  instead saved first and caught the database's `IntegrityError` passes the
  same test, because SQLite's `UNIQUE` constraint never fires on a
  self-rename regardless of which style wrote the check. The test does have
  real value, verified by mutation — it does catch forgetting the `AND id !=
  preset_id` clause itself — the docstring's claim about *why* is simply
  broader than what the test can tell apart.
- **`ui/tests/ApiTest.elm`'s pre-existing unknown-status test omits
  `last_preset_id` from its fixture entirely and still passes** — only
  because the decode fails earlier, on the deliberately-bad
  `separation_status` the test exists to exercise. Harmless, and untouched by
  this plan, but nobody should read the omission as evidence the field is
  optional; `Api.Song`'s decoder requires it.
- **No `RequestTest.elm` exists**, so this plan's new `Request` functions —
  their paths, verbs, and JSON encoding — are exercised only by reading, the
  same as every other function in that module. Pre-existing convention, not a
  gap this plan introduced.
- **Nothing in either suite exercises `Config.overlay` against the *real*
  schema or the *real* published defaults, and the final review's Fix (1)
  above is exactly what living in that gap costs.** `ui/tests/Fixtures.elm`'s
  schema is a trimmed hand-copy of one live `GET /api/schema` response, with
  no `reverb` section and no `search_end`; the Python side's own test of
  `GET /api/config/default` stops at `MixConfig.from_dict(body) ==
  MixConfig()` and never reaches Elm at all. So the branch's headline claim —
  that a mixer opens on the same values `sleepmix render` would use — held,
  through six per-task reviews and two earlier whole-branch fix-wave attempts
  that also missed it, only because `Fixtures.elm`'s schema and the server's
  real one happen to agree with each other, not because either is ever
  checked against the other's ground truth. `MixerTest.elm`'s `onDefaults`
  fixture (three tests use it) is the closest either suite comes, and it is
  still a hand-written `Decode.Value` standing in for the real route.
  Closing this needs one fixture generated on one side — a real
  `GET /api/schema` and a real `GET /api/config/default` response, captured
  once against a running server — and consumed unmodified by the other side,
  the same shape `_ui_body` (Plan 3b, above) still lacks for `Config.encode`.
  Not attempted here.

**What this plan does not cover, named up front rather than discovered
later:** a presets screen (list, browse, delete from outside the mixer),
preset import or export or sharing between installations, and migrating
`last_preset_id` to an enforced foreign key. Segment selection and
arrangement, a path allow-list for `import_song`, streaming peak
computation, and authentication are carried forward unchanged from earlier
plans — see "Known weaknesses, deferred deliberately" below.

## Plan 3c: jobs you can watch and stop

The incident this plan exists to fix: a seventy-minute file, imported by
accident, that the operator wanted to test a smaller one instead of — and had
to kill the server by hand to get at, because nothing running could be
stopped and nothing on screen showed what was queued behind it. It turned out
to be suspended (`Ctrl-Z`) rather than dead, and was found still holding
6.2 GB resident. Plan 3c closes every part of that: separation can now be
cancelled mid-run, a queue screen shows what the one worker is doing and
what's waiting, and both the mixer's Render button and the song screen's
Separate button say so before a long source file is submitted.

**Separation is killable now, and the mechanism is a subprocess.**
`demucs.apply_model` is one opaque call that never looks at a cancel token, so
making it interruptible meant moving it out of the request-serving process
entirely: `separation_process.run_separation` runs `python -m
sleepmix.separation_worker` as a child, reads its phase progress off stdout,
and kills it (`SIGTERM`, escalating to `SIGKILL`) the moment a cancel token
fires. See `docs/architecture.md`'s new section on this for the phase
protocol and — the part that mattered most in review — how the three ways a
child process can end (cancelled, crashed, "demucs isn't installed") are kept
from being read as each other. This task's own verification confirmed it
against a real 246.6 s track and a real Demucs run: cancelling partway through
(at `fraction=0.15`, mid-"Separating stems") left the song back at `pending`
with no reason recorded, no worker process still running, and **nothing at
all** in the cache directory — not a partial stem, not a staging directory.

**The stem cache write became atomic as a consequence, not a separate
goal.** A subprocess that can be killed can be killed mid-write, and the old
two-step cache write (marker, then stems, straight into the final directory)
had no atomic "finished" to interrupt. `separation._write_cache` now builds
everything in a sibling staging directory and renames it into place in one
step, so a kill lands either before the rename (nothing changes) or after it
(the new cache is already complete) — never in between. See
`docs/architecture.md` for the full reasoning, including why the old ordering
was right for the write that used to exist and stopped being relevant once
that write did.

**The render screen (`Page.Renders`)** shows every render — queued, running,
done, cancelled, failed — with a config summary (duration, which stems,
where the decay ends up) read from whatever was actually `POST`ed rather than
inventing a value for fields the server defaulted silently. It plays a
finished render through a plain `<audio controls>` element rather than the
Web Audio port the mixer uses, deliberately: the port decodes a whole buffer
into memory to loop it on a musical seam, which is the wrong trade for half an
hour of audio a browser will happily stream instead. A render still running
gets a Cancel button and a progress bar fed by the same job machinery
separation uses; a finished one gets a download link and a Delete button, and
deleting removes both the database row and the file on disk, verified this
task by watching both actually disappear.

**The one bug this screen shipped with and caught in its own review is worth
keeping the story of.** The first version paired a render with its progress
job by *song and timestamp*, a heuristic standing in for a real key — and a
render row stranded at `"running"` by a server restart (rows are in SQLite,
jobs are only ever in memory) would silently adopt the *next* render's job the
next time that song was rendered. Clicking Cancel on the dead row would then
kill the live render underneath it, and `_abandon` would delete its partial
file — the wrong render, stopped, invisibly. The fix was a real key:
`Job.render_id`, three server lines, flowing through `GET /api/jobs`, the SSE
stream and the render POST response, with the heuristic deleted outright
rather than kept as a fallback — a fallback that silently mispairs is the bug,
not a safety net for it.

**The queue screen (`Page.Queue`)** answers "what is the one worker doing, and
what's stacked up behind it" — running first, then queued, then what recently
finished, oldest first within each group because that is the order the worker
will actually take them in. It is live-only and says so: `JobManager` keeps
jobs in memory, so a restart empties this screen, and an empty screen is then
the truth rather than a failure to load. It polls `GET /api/jobs` every four
seconds rather than streaming, because ten rows streaming one worker's
progress each would be ten connections answering the same question `Page.Queue`
already asks once. Every non-terminal row has a Cancel button, including a job
still *queued* — which, on this project's one worker, might mean waiting
behind a separation that runs for many minutes, and used to mean nothing
visibly happened when you clicked it (below). Cancelling a queued render
settles its row immediately rather than leaving it to a work function that
will now never run (see the note on `JobManager.cancel` below); the same
route settles a render cancelled while queued even if nothing else ever
touches its row again, which is what makes it deletable afterwards instead of
stuck forever at a status `DELETE` refuses.

**A cancel on a queued job used to be completely silent, in exactly the
scenario this plan exists for.** `JobManager.cancel` only set the token;
the status only flipped once the pool actually reached that job, which on one
worker means after whatever is running ahead of it finishes. Seventy-minute
separation running, a render queued behind it, operator clicks Cancel: the
response said `cancelled: true`, and the row went on reading "waiting" for
seventy minutes, because nothing was wrong with the cancel — it had just not
had a chance to matter yet. The fix flips a **queued** job's status to
`cancelled` synchronously, inside the same lock, the moment `cancel()` is
called, since `_run`'s own guard means that job will never do any real work
regardless. A **running** job is left for its own work function to settle,
because settling it from the request thread as well would race the worker —
the case that would hurt is a render finishing a moment after the token was
set, where the request thread's write could land "cancelled" over a row the
pipeline had just, correctly, marked "done".

**`Warn` is one module, not a sentence written twice.** The mixer's Render
button and the song screen's Separate button both put work on the same
single worker, and a warning written once in each place is a warning that can
drift into disagreeing about the same queue. `Warn.forSource` names a
duration (rounded to the nearest minute, with "roughly" doing the work of not
claiming a precision that isn't there) once source audio passes fifteen
minutes — a judgement call, not a measurement: roughly three times an ordinary
album track, and nowhere near either side of the incident it exists to catch.
It warns; it does not block, because a long file is a legitimate thing to
render and the threshold exists to catch the accident, not to have an opinion
about long songs.

**`Warn.forSource` keys on the source file's length, and that is a real gap a
render's own timing now makes concrete.** A render's wall-clock cost is
dominated by `output.duration_min`, not by how long the source track is — this
task's own measurement found a 246.6 s source with its stems already cached
rendering to the default 20-minute (1200 s) mix in roughly 11–14 s (measured
twice, 11.0 s and 13.6 s; see `docs/architecture.md`),
because the cost that scales with output length (`build_disintegrating_stream`
iterating roughly seventy times for that loop) is cheap per iteration, while
the cost that would actually make a render slow — separation, which does scale
with source length — has usually already been paid by the time the mixer's
Render button is reachable at all. Read backwards, that means the warning is
watching the wrong number for what it is nominally about: a four-minute source
rendered to a **sixty-minute** mix (`output.duration_min = 60`, a config change
away, not a different file) would iterate roughly three times as many loops as
the measurement above and block the one worker for a correspondingly longer
stretch, and nothing would warn, because the source is nowhere near fifteen
minutes. The warning was written before anyone had a render-timing number to
design a better one from; it now exists, and extending `Warn.forSource` (or
splitting it) to also look at the configured output length is the natural next
move, not attempted here because this task writes no application code.

**Known gaps, carried forward rather than fixed:**

- **A sub-millisecond TOCTOU race survives in the duplicate-separation
  guard.** `separate_song` checks `jobs.list()` for an in-flight separation on
  the same song before submitting a new one, but Starlette dispatches sync
  routes on a threadpool and nothing locks read-decide-submit as one
  operation. Two genuinely simultaneous `POST /separate` requests could still
  both pass the check and stack two jobs. Ruled not worth fixing: the guard
  exists for a job sitting queued for *minutes* behind a render, a window any
  request landing anywhere inside easily sees, and the residual worst case —
  two duplicate jobs — is exactly the pre-fix status quo rather than a new
  failure mode.
- **`terminate()`/`kill()` only signal the direct child**, so a grandchild
  process would survive being orphaned if Demucs ever spawned one. It doesn't
  today — this project's `apply_model` call passes no worker processes — and
  `start_new_session=True` plus `os.killpg` carries platform nuance not worth
  adding speculatively against a case that doesn't exist yet. Revisit if
  Demucs configuration ever gains worker processes of its own.
- ~~**No automated test asserts that a cached *fallback* separation still
  reports itself as a fallback through the supervisor's warm path.**~~ Closed
  by the final fix wave:
  `test_a_cached_fallback_still_reports_itself_as_a_fallback` writes a fallback
  cache, calls `run_separation`, and asserts the reason survives. It was worth
  closing rather than carrying: the warm path returns
  `SeparationResult(_load_cache(…), _load_fallback_reason(…))` directly instead
  of going through `separate_detailed`, deliberately, so it is a second place
  that has to remember — and forgetting makes a song separated before Demucs
  was installed read as properly separated, with per-stem controls implying a
  separation that never happened.
- **No `update`-level test covers the renders fetch flow.**
  `GotRenders`, `GotRenderJobs` and `refreshRenders` appear nowhere in
  `ui/tests`, so the fetch-ordering fix described above (and the stale-jobs
  handling around it) is verified by reading the code, not by a test that
  would fail if it regressed. `OpenRenders` itself does appear —
  `UpdateTest.elm:439,442` drives it, but only incidentally, to assert the
  queue and renders screens are never both open at once; nothing there
  exercises the fetch it triggers. The final fix wave narrowed this rather than
  closing it: the screen's Cancel wiring is now asserted through `Main.view`
  (`RendersTest.elm`, "the Cancel button, through the whole application"),
  because that one control can destroy something and `jobFor` alone could not
  vouch for it. The rest of `Page.Renders`' and all of `Page.Queue`'s view
  markup is still unasserted. Relatedly, `keepStreamed` pins the
  held copy of a streamed job unconditionally, so a poll can never correct it
  once it's set — safe today only because every server-side update publishes
  to every subscriber, so the held copy and a poll's copy never actually
  disagree in practice.
- **The download filename is the render's hex id.** `Page/Renders.elm`'s own
  docstring opens by naming this as the very problem the screen exists to
  solve — finding a render afterwards used to mean `ls` and a filename that
  says nothing — and the downloaded file still has one, even though the
  screen has the song title sitting right next to the Download link. A
  deliberate UX call parked rather than a defect: fixing it is a `Content-
  Disposition` filename away, not attempted here.
- **`.queue-head` overflows horizontally below an estimated 400px.**
  `.queue-kind` carries an unshrinkable `flex: 0 0 5.5rem` and the status and
  timestamp are `nowrap` — a real bug class, but "roughly 400px" is a figure
  read off the CSS rule, not a measurement taken in a browser; nobody in this
  project's review loop can open one. Cosmetic on a desktop-only local tool —
  `.renders` already has the same class of thing — and not fixed here.
- **`JobManager.cancel`'s docstring used to claim only two orderings were
  possible** between a cancel and the worker starting the same job — this one
  wins and `_run` short-circuits into its own cancelled update, or `_run` wins
  and this sees `"running"` and defers to the work function's own `check()`.
  There is a third: `_run` reads `token.cancelled` without holding the lock,
  so a worker that read `False` a few microseconds before `cancel()` acquires
  the lock can still go on to write `status="running"` over the `"cancelled"`
  that was just set. It self-heals — the token is already set by the time
  that happens, so the work function's own `check()` raises almost
  immediately and `except Cancelled` restores the status — and it needs the
  previous job to finish inside that same handful of microseconds, so no
  permanent inconsistency results. The docstring is corrected to not claim an
  exhaustiveness it doesn't have; the behaviour itself is unchanged.
- **A render against an unseparated song still separates in-process, where
  the cancel token cannot reach Demucs.** Separation is killable for the
  standalone Separate action, and for renders started from the mixer, which
  requires prior separation before it will even open. But `POST
  /api/renders` does not require that — it is reachable directly, bypassing
  the UI's own gate — and `start_render`'s work function calls
  `run_pipeline`, which calls `separation.separate()` directly rather than
  the subprocess-wrapped `separation_process.run_separation`. That predates
  this branch and is out of scope to change here, and nothing in this
  document or `docs/architecture.md` claims otherwise — but it is a real
  residual, the same shape as the seven above it: a render submitted this way
  against a song with no cached stems is cancellable only at `run_pipeline`'s
  own checkpoints (`docs/architecture.md`'s "Progress and cancellation
  contract"), all of which come *after* separation returns, so the one
  worker is committed to a full, uninterruptible Demucs run before the first
  checkpoint is even reached. A maintainer closing this would route that call
  through `run_separation` instead of `separate`, threading through the
  `reporter` and `cancel` that `run_pipeline` already has in scope — the same
  two arguments `separate_song`'s own `work` function already passes to
  `run_separation` today.

  **The preview path reaches the same call, and that is what made this
  UI-reachable rather than curl-only.** `RenderSession.stems()`
  (`sleepmix/session.py`) also calls the in-process `separation.separate()`, so
  the first preview on a song with no cached stems runs a full Demucs inside
  `SessionRegistry`'s per-song use lock, holding a threadpool thread, with no
  job, no queue row, no Cancel and an indeterminate "Preparing…" panel. Every
  door into the mixer is gated on `song.stems` being non-empty, which is what
  normally keeps that call unreachable — see the invariant below, which is the
  thing that gate depends on and which this branch briefly broke.

**The invariant `songs.stems` carries, added by the final fix wave:**

`songs.stems` and the on-disk separation cache are two records of one fact, and
after Plan 3c they can be written at different moments. Only one line can make
them disagree — the `invalidate_cache` inside `separate_song`'s work function,
which `force=true` reaches — and it now clears `stems` in the same breath.

The rule is: **from the moment the cache is deleted until the moment new stems
are written, the row says the song has none.** Nothing else in the codebase
deletes a cache while a row survives it.

This is not bookkeeping. Every gate into the mixer reads `song.stems` and not
the cache — `Page.Song.mixerPanel` for the button, `Main`'s `OpenMixer` for the
model, deliberately, because the client cannot see the disk. Before the fix, a
forced retry that was cancelled (newly possible from the queue screen) left a
row reading "not separated" *and* listing four stems *and* offering an enabled
Open-the-mixer with no explanatory line. Opening it did the two worst things
available here: the in-process Demucs run described above, and then — once it
cached four real stems while the mixer's rows had been built from the stale
list — a `plan_stem_configs` that matched none of them and returned every
available stem at its defaults, silently discarding every gain, reverb send and
decay setting on screen.

Every task on the branch was individually right. The cancel path is correct to
reset only the *status*; the atomic cache write is correct and is precisely why
force leaves nothing on disk; making a running separation cancellable is what
makes the sequence occur at all; and gating the mixer on `song.stems` was right
back when stems and cache could only ever be written together. Nobody owned the
sentence that has to be true across all four, which is why it is written down
here rather than left to be re-derived.

`tests/test_api_songs.py` holds it as a sequence rather than a unit —
`test_cancelling_a_forced_separation_leaves_the_song_with_no_stems` and
`test_a_forced_separation_that_fails_also_leaves_no_stems` — because no single
step is wrong and only the order is.

## Plan 3b: the mixer

`ui/src/Page/Mixer.elm` is the screen the previous two plans were building
toward — a progress scrubber over the decay arc, per-stem enable/gain/reverb-
send/decay, solo, and the loop region drawn on the waveform with its tempo. It
is reached from the song screen and it plays: `ui/ports/audio.js` fetches
`POST /api/preview`, decodes the WAV and loops it, swapping buffers at the next
loop boundary.

Almost none of the controls are written. `GET /api/schema` describes every
config field and `ui/src/Config.elm` holds the values and re-nests them for
`MixConfig.from_dict`; `Config.elm` names no config parameter at all, with
three structural exceptions it documents, and `Page/Mixer.elm` names a handful
that are not controls (`separation_model`, which it deliberately withholds a
control from; `output`/`duration_min` for the scrubber readout;
`loop`/`start_s`/`end_s`, the two the loop endpoint takes an override for; and
the sections that get an explanatory note), each argued for in a docstring
where it appears. Adding a field in
`sleepmix/config.py` puts a control in the mixer with no frontend change. The
same reasoning went the other way once during this task: `MixConfig.seed` now
carries `min: 0` in its metadata, because `validate` rejects a negative seed and
the UI's bounds come from the schema alone — without the floor, a generated
control could produce a config the server refuses, and it would surface as a
400 on a preview rather than as a slider that will not go there.

What it does not do yet, and what to know before changing it:

- **The sound bed is not in previews.** `preview.render_window` does not add it;
  `pipeline.run_pipeline` does. The section says so in place, because otherwise
  you turn on binaural beats, hear nothing, and conclude the mixer is broken.
- **The mixer will not open without stems, or while a separation is running.**
  Its rows *are* the stems, and a preview of an unseparated song would run
  Demucs inside the preview lock with nothing reporting progress. A separation
  finishing also discards the warm session and can change the stem list under
  an open mixer, which is the other half of the gate.
- **"Preparing…" is indeterminate on purpose.** The first preview is the
  slow path — separation if nothing's cached, then finding the loop and
  time-stretching every stem, then the render itself, all behind one lock —
  and nothing in it reports progress, so the bar animates and claims nothing.
  Measured at 117 s / 180.55 s on two different tracks (`docs/architecture.md`
  has the breakdown); the number moves with track length, the absence of
  progress reporting does not. Do not replace it with a fraction; there is
  no fraction. If
  that preview *fails*, `Preview.failed` puts the session back to `Cold` rather
  than to `Idle`: nothing came back, so nothing is known to be playable, and
  opening the controls over silence would break the one promise this screen
  makes. The panel says so and offers to try again.
- **`separation_model` has no control in the mixer, deliberately.** It is the
  one config field whose change is not a cheap re-render: `update_config` nulls
  the session's stems, so the next preview runs Demucs inside the per-song
  preview lock — minutes, no progress, and the screen already playable. The
  value still travels with every preview; only the control is absent. It
  belongs beside the Separate button, which already has a job and a progress
  bar, and that is a later plan.
- **Nothing automated asserts that a port command is emitted.** Elm `Cmd`s
  have no equality, so an implementation where `sendPreview` returned
  `Cmd.none`, or `leaveMixer` omitted `stopPreview ()`, would pass every Elm
  test in the suite — every assertion in `MixerTest.elm` and
  `PreviewTest.elm` is on the model half of `update` (what state `Preview.request`/`Preview.arrived`
  produce), never on whether a real `Cmd` actually left the program and
  reached `audio.js`. Compensated by manual `curl` against a running server
  during this task's own review, not fixed — the gap is structural (Elm
  offers no way to inspect a `Cmd` from a test) rather than a missing
  assertion someone forgot to write, so closing it would need a different
  testing approach, not more tests of this shape.
- **A config that asks for no stems is refused, on both paths — fixed in the
  final review wave, and worth keeping the history of.** `plan_stem_configs`
  used to answer an empty plan with "every available stem at defaults". That
  fallback was written for one case: separation fell back to a single `mix`
  stem, so no configured stem *name* matches what exists, and rendering nothing
  would be wrong. It could not tell that apart from *every matching stem
  switched off* — which was unreachable until this plan shipped a per-stem
  Enabled checkbox. Four clicks reached it, and the preview came back as the
  **full default mix at full level**: `master_gain` recalibrates from the same
  fallback set, so it played at the ceiling, with every gain, reverb send and
  decay curve the user had tuned discarded in the same step. Measured against
  the suite's `stub_separation`: default rms 0.298, all-off rms 0.194 — audible
  music, not silence.

  The two conditions are now separate. "The config describes none of these
  stems" still falls back; "every one of them is off" plans nothing, and
  `plan_stem_configs` may legitimately return `[]`. Both callers refuse it:
  `preview.render_window` raises `NothingToRender` (a `ValueError` subclass, so
  the CLI handles it with every other bad config, and its own type so
  `POST /api/preview` can answer 400 with the reason for *this* without turning
  an arithmetic error from deep in the DSP into a message about stems), and
  `pipeline._plan_jobs` raises the same rather than writing half an hour of
  peak-normalized silence to disk. The one-frame `silence(1, …)` that used to
  end `render_window` is gone; the branch is unreachable and raises.

  The same refusal covers soloing a stem the render would drop, which was the
  48-byte-WAV finding from Plan 3b's verification pass. Both orders are now
  closed in the UI as well: the Solo button is disabled on a switched-off stem
  (as before), and `toggleField` clears the solo when the stem being switched
  off is the soloed one — unrepresentable rather than merely reported. And
  `Main.withMixer` consults `Mixer.everyStemDisabled` before sending, so
  unticking the last stem produces a line on screen saying there is nothing to
  render (the previous preview keeps looping) instead of a request that comes
  back 400 and reads as the server breaking.

  **Why it survived seven task reviews is the part worth remembering.** Neither
  diff was wrong: the Elm generated the checkbox correctly, and `config.py`'s
  fallback was correct when written. The defect lived in the seam — the config
  the mixer builds and the config the renderer consumes were tested
  independently and never against each other. The Elm suite stopped at
  `Config.encode`, the Python suite started at a hand-written dict, and no test
  had ever POSTed a body with a `stems` list in it. `tests/test_api_preview.py`
  now has `_ui_body`, which builds a request shaped exactly as `Config.encode`
  emits one, and asserts a per-stem edit reaches the audio.
- **The loop region is re-fetched only when `loop.start_s` or `loop.end_s`
  changes**, because those are the only two things `GET /api/songs/{id}/loop`
  takes. `bars`, `beats_per_bar` and the search window are config fields a
  render honours and that endpoint cannot express, so the drawn region can
  differ from what a render detects once those are changed. The endpoint also
  still decodes the whole file and runs beat tracking on every call with no
  caching (recorded during Plan 3b Task 2), and the mixer now calls it on
  entering a song and on those two edits.
- **Collapsed sections use `<details>`, so their open/closed state lives in the
  DOM rather than in the model.** Nothing depends on it and Elm never sets
  `open`, so the browser keeps whatever the user did; a screenshot of the model
  will not tell you what is expanded.
- **Field order within a section is alphabetical**, because `Schema.elm` decodes
  into a `Dict` and JSON object order does not survive that. It reads oddly in
  places (`lowpass_end_hz` above `lowpass_start_hz`). Preserving the server's
  order would mean decoding to key-value pairs and threading order through.
- **`previewReady` carries a JSON value, not `()`.** `audio.js` sends
  `{ durationS }`, and a `()` port compiles to `Json.Decode.null`, which rejects
  an object at runtime with a port error Elm cannot catch — the screen would sit
  at "Preparing…" forever with audio playing underneath. The payload is decoded
  leniently and shown as the length of the loop now playing.
- This plan's own closing section named four things out of scope: **the
  render screen (start, watch, cancel, download), the presets UI, queue
  visibility, and a warning before importing a file large enough to block
  everything behind it.** Plan 3c closed three of the four — the render
  screen, queue visibility, and the warning, plus, not asked for by this list
  but the same shape of gap, the ability to cancel a *separation* once it has
  started. Plan 3d has since closed the last one — the mixer's preset bar;
  see that section above. Per-song config memory, named in the same breath as
  presets when this was written, turned out to be a different thing than a
  missing screen: Plan 3d considered it and rejected it deliberately (see that
  section), rather than building it.
- The parked defect from Plan 3a is untouched: reloading mid-separation shows an
  enabled button reading "Separating…", because the disable comes from client
  state and the label from the server's status. The mixer's own gate reads the
  server status as well as the flag, so it does not inherit the bug.

**What the final whole-branch review changed**, beyond the empty-plan refusal
above. (1) `toggleField` clears a solo on the stem being switched off, closing
the second of the two orders that reached a mix of nothing. (2) `output.
sample_rate` gained the `sectionNote` the other preview-ignored fields already
had: `render_window` uses the loop's own rate and only `pipeline` resamples, so
that select changes nothing you can hear until you render. (3) The stale
"117 seconds / 73 milliseconds" pair is gone from the four source comments that
still carried it, pointing at `docs/architecture.md`'s reconciliation rather
than repeating a figure measured on a different track. (4) `.back` was styled
under `.song-view` only and is emitted under `.mixer` too — see the scope blind
spot noted in `ui/README.md`. (5) Three test gaps, each of which had let a real
defect through: no test drove `SoloToggled`, `FieldChanged` or `FieldToggled`
through `Main.update` (all three could be stubbed to `( model, Cmd.none )` with
the suite green); no test ever POSTed a body containing a `stems` list; and no
test set a *valid* value on a `StringChoiceField`, an `IntChoiceField` or a
`TextField`, so `parse` returning `Nothing` for a choice field would have left
every `<select>` in the mixer silently deleting its key. All three are closed
and each was verified by mutation. (6) Two route tests asserted only that two
responses differed, which a 422 satisfies as well as two mixes do; they now
assert the status too.

**Four residuals the re-review left open**, none of them blocking, all worth
knowing before you touch this area:

- **`_ui_body` is hand-written, not derived from `Config.encode`.** It is
  shaped exactly as the Elm encoder emits one today, and it does prove
  `MixConfig.from_dict` reads a `stems` list — but nothing mechanically ties
  the two. Rename a key in `Config.elm` and both suites stay green while the
  real request 422s. The seam that produced the empty-plan defect is narrowed,
  not closed; closing it needs a fixture generated from one side and consumed
  by the other.
- **`NothingToRender` reaches the CLI as a traceback, not a message.**
  `cli.py` catches nothing, so `sleepmix render` with every stem off exits 1
  with a Python stack and the reason legible at the bottom. A negative seed
  already behaves this way, and no wrong audio is produced, so it is polish
  rather than a defect. Note also that `_plan_jobs` refuses *after* separation,
  because stem names do not exist before it — a CLI render with everything off
  still pays for Demucs before being told no.
- **A soundbed-only mix is now inexpressible.** Every stem off plus the bed on
  is refused. It never worked before either — it played the full default mix
  *plus* the bed — so this is not a regression, but the door is now explicitly
  shut rather than accidentally ajar.
- **The blocked send does not touch `model.preview`.** If a request is already
  `Queued` when the last stem is unticked, that queued request still goes out
  when the in-flight one returns, so what you hear can be one config-step newer
  than "what you can still hear is the last preview" implies. Harmless — it is
  a mix the user asked for a moment earlier — but the copy is imprecise.

## Plan 3a: what's built, and what it deliberately doesn't do yet

`ui/src/Main.elm` is a compiled Elm application (`sleepmix/static/app.js`)
served at `/` in place of the old placeholder page. It talks to the Plan
2a/2b API exclusively over HTTP and one pair of ports
(`ui/ports/events.js` for job progress via SSE) — nothing about the API
changed to accommodate it, exactly as Plan 2b's own document predicted. What
it does: shows the library (`Page.Library`), imports a song by filesystem
path, opens a song (`Page.Song`) and shows its waveform as SVG
(`Waveform.elm`, peaks fetched from `GET /api/songs/{id}/peaks`), starts stem
separation and tracks its progress live over `GET /api/jobs/{id}/events`, and
shows a separation failure or fallback reason in place rather than swallowing
it. Decoders (`ui/src/Api.elm`) are strict: an unrecognised `separation_status`
or job `status` fails the decode rather than being coerced into a default
case. See `ui/README.md` for how to build, develop, and test this, and
`docs/architecture.md`'s new frontend section for the design reasoning behind
each of those choices.

**What this section originally listed as not done yet — Plan 3b has since
closed most of it.** Audio playback, orphaned `running` rows, the loop region
and its endpoint, the mixer, preview playback, and schema-driven controls are
all closed now; each entry below is written in the past tense, names what
closed it, and keeps whatever reasoning is still worth having on hand rather
than being deleted outright. Still open from this list: the import-size
warning, the coarse separation progress bar, the render screen, and
presets — those stay in the present tense because they still are.

- **Nothing in the interface played audio, and nothing said so — closed by
  Plan 3b's mixer.** This was the gap that actually bit during testing:
  `Page.Song` announced "separated" with four stem names and then offered no
  next action — no preview, no render, no player. `POST /api/preview` already
  returned WAV bytes in well under a second once a session was warm, and
  `POST /api/renders` already produced a file, but no view called either
  endpoint, so a reasonable person separated a song, found no way to hear
  anything, and concluded the tool was broken. Plan 3b's mixer
  (`Page/Mixer.elm`, `ui/ports/audio.js`) closes it: opening a separated song
  now offers a scrubber that plays, with soloing and every decay control
  reachable from the same screen. The reasoning worth keeping is the standard
  this gap set for the time in between — announcing success while offering
  nothing is worse than announcing nothing — which is why Plan 3a's own song
  view, while this was still open, said plainly that preview and render would
  arrive later rather than staying quiet about the missing capability.

- **Orphaned `running` rows used to survive a server restart — closed by Plan
  3b's Task 1.** `separation_status` is set to `running` before a job starts,
  and was cleared only by a terminal status or one of `separate_song`'s two
  exception handlers; process death bypassed both, so killing or suspending
  the server mid-separation left the song claiming to separate forever, with
  no job behind it — the in-memory `JobManager` had died with the process.
  Observed in practice: two rows stranded at `running` after a `Ctrl-Z`, which
  suspends rather than kills and looked identical to having exited. Plan 2b
  had already fixed this class of bug for exceptions; process death was the
  case that was missed, and the fix was exactly as small as it looked:
  `Store.reconcile_orphaned_separations()`, called from `lifespan` immediately
  after the store opens (before the job manager or session registry exist),
  resets every `running` row to `pending` at boot, since **any `running` row
  at that moment is definitionally orphaned** — the job manager is in-memory
  and nothing else could still be tracking it. See `docs/architecture.md`'s
  server section for where this sits.

- **No warning about how long a large import would take, and no way to stop
  a separation once it had started — both closed by Plan 3c.** A 70-minute
  file used to import instantly and then queue a separation that ran for a
  very long time and held several gigabytes — measured at 6.2 GB resident for
  one such job — with nothing to do about it but kill the server by hand,
  because the only worker in the process was already inside a single opaque
  `demucs.apply_model` call nothing could interrupt. That is the incident Plan
  3c exists to close, and it closes all three parts of it: `Warn.forSource`
  names the file's length and the single-worker constraint before either the
  Separate or Render button is pressed, once source audio passes fifteen
  minutes; `separation_process.py` moves Demucs into a killable subprocess, so
  a separation started by accident can now be cancelled and the song comes
  back to `pending` with nothing left in the cache; and the queue screen
  (below) makes the wait itself visible instead of a silent hang.

  **The queue depth half of this is closed** by Plan 3c's queue screen:
  `Page.Queue` renders `GET /api/jobs` as what is running, what is waiting
  behind it and what recently ended, with a Cancel button on everything still
  stoppable — reached from the library's nav strip. That is the escape hatch
  the operator previously had to use `kill` for. What is still missing is an
  *estimate*: the screen can say a job is 15% done, but nothing anywhere
  predicts how long a separation will take from the file's duration, so
  `Warn.forSource`'s fifteen-minute line is a judgement call rather than a
  derived number — and, per the render-timing measurement in the Plan 3c
  section above, it is a warning that watches source length while a render's
  own cost is dominated by the configured output length instead.

  Note also what the queue screen structurally cannot show: `JobManager` holds
  its jobs in memory and keeps fifty terminal ones, so the screen is empty
  after every server restart and forgets old finished work. It says so on the
  screen rather than looking broken.

- **No loop region on the waveform, and no route that could draw one — closed
  by Plan 3b's Task 2.** The spec's Song view asked for the detected loop
  region marked plus a tempo readout, and Plan 3a's goal line had promised
  "see its waveform and detected loop" — but nothing in that plan could have
  delivered it, because no endpoint exposed a detected loop or a tempo:
  `server/api/songs.py` had import, list, get, peaks and separate, and nothing
  else; `analysis.find_loop` and `_estimate_tempo` were reachable only from
  inside a render or a `RenderSession`, never over HTTP. `Waveform.loopRegion`
  had been written anyway and was dead code on that branch: `Page/Song.elm`
  passed `loop = Nothing` and had nothing else it could pass.
  `GET /api/songs/{id}/loop` (added in this plan's Task 2, documented in
  `docs/architecture.md`'s server section) closes it: it calls `find_loop`
  directly against the whole file, needing no separated stems and no warm
  session, so it answers before separation has even happened — and both
  `Page.Song` and the mixer now fetch it and pass a real region through. The
  reasoning worth keeping: the plan's goal line was corrected before this
  closed (see the note at the top of
  `docs/superpowers/plans/2026-08-04-elm-shell.md`) precisely because
  promising a feature with no route behind it is worse than not promising it,
  and this entry is the record of why that route had to exist before the Elm
  half could be built — a caution worth keeping for whatever the next
  endpoint-shaped gap turns out to be. **The route itself still has no cache**
  and re-runs beat tracking on every call, which the mixer now calls more
  often than anything before it did; that remains open and is recorded
  separately above, under Plan 3b.

- **The separation progress bar is real but has almost nothing to animate.**
  The SSE machinery works end to end — `watchJob` opens the stream, events
  decode, `Watching`'s fraction reaches the bar. What is thin is the payload.
  Plan 3c's subprocess split changed the numbers without changing the
  substance: the job emits `0.0` from the route's own `reporter.emit`, then the
  worker's three hard-coded phase lines (`separation_worker._phase`: `0.05`
  "Loading the model", `0.15` "Separating stems", `0.90` "Writing stems"), then
  `1.0`, which is terminal and clears the bar. **The whole Demucs run happens
  between `0.15` and `0.90`**, so the bar jumps to 15% within a second or two
  and then sits there for the entire separation — the several minutes that are
  the only part anybody is waiting through. It reads "15%" the whole time.

  It is not that Demucs cannot report more: `demucs.apply.apply_model` takes a
  `progress` flag, and `_demucs_separate` passes `progress=False`. Turning it
  on writes a tqdm bar to *stderr*, which `_StderrTail` drains and keeps only
  as a failure tail — so making the bar move means parsing that, or splitting
  the call per model shift and emitting a phase line between each, and neither
  is a line of work.

  **Anything inheriting this bar should not assume it moves.** A render does —
  `pipeline.run_pipeline` reports many intermediate fractions through its stage
  checkpoints, see `docs/architecture.md` — but a separation's does not, and a
  screen that says otherwise is telling the operator a bar is informative while
  they decide whether to cancel. `Page.Queue.progress` said exactly that until
  Plan 3c's final fix wave, and now says what is true.

- **No mixer — closed by Plan 3b's Task 6.** Nothing in this UI read
  `/api/schema` or let a user touch a single decay/reverb/tempo parameter;
  separation was the only action a song screen offered. `Page/Mixer.elm` is
  the mixer now.
- **No preview playback — closed alongside the mixer.** `POST /api/preview`
  existed and was tested on the server side, but nothing in this frontend
  called it, and there was no `ports/audio.js` — no `decodeAudioData`, no
  looped playback, no buffer swap at a loop boundary. All of that exists now;
  see `docs/architecture.md`'s frontend section for the gapless-swap and
  coalescing design.
- **No schema-driven controls — closed alongside the mixer.**
  `config.config_schema()` — bounds, labels, and help text for every
  `MixConfig` field — was not consumed anywhere in `ui/`. `Schema.elm` and
  `Config.elm` consume it now, and generate the mixer's controls from it.
- **No render screen — closed by Plan 3c.** Starting, watching, cancelling, or
  downloading a full render (`server/api/renders.py`, all built in Plan 2b)
  had no frontend at all. `Page/Renders.elm` is that screen now; see the Plan
  3c section above for what it does and the pairing bug its own review found
  and fixed.
- **No presets — closed by Plan 3d.** `server/api/presets.py`'s CRUD had no
  corresponding screen; `ui/src/Page/Mixer.elm`'s preset bar is that screen
  now, and `PUT /api/presets/{id}` (added the same plan) is what lets one be
  renamed or saved over rather than only ever created fresh. See the Plan 3d
  section above. Per-song config memory — remembering, and re-applying, a
  preset for a specific song — was considered in the same plan and rejected
  rather than built; that section explains why.

**What the final whole-branch review changed.** Six things, all of which had
shipped looking finished. (1) `sleepmix/static/index.html`'s stylesheet was
written for a health-check-only page and defined three of the fifteen classes
the Elm views emit — so `div.progress-fill`, an empty div carrying only an
inline `width: N%`, had no height, no background and no colour, and **the live
progress bar this whole branch exists to deliver rendered as nothing at all.**
Library rows were default bulleted `<li>`s with a click handler and no
`cursor: pointer`. The stylesheet now covers every emitted class, and
`progressBar` gained a `.progress-track` element so the fill has something of a
known size to be a percentage of. (2) The separation state became one union —
see `ui/README.md` for the shape and the three reachable paths that used to
strand the panel at "Separating…" forever. (3) Responses are tagged with a
monotonic request id rather than a song id. (4) `ui/hash_sources.py` hashes the
build *outputs* as well as its inputs, which is what makes a committed
`make ui-dev` bundle a test failure; `sleepmix/static/events.js` is separately
asserted byte-identical to `ui/ports/events.js`. (5) The plan's goal line was
corrected — see the loop-region entry above. (6) `.github/workflows/tests.yml`
is the first CI this repository has had.

**A residual race in the stream-failure port, stated because it is a design
choice and not an oversight.** `ports/events.js` reports every `EventSource`
`onerror` to Elm, and Elm decides whether it mattered by checking whether it is
still `Watching` that job. That works because Elm processes an incoming port
send synchronously — the terminal event's `update` runs, sets `Idle` and
dispatches `stopWatchingJob` before `onmessage` returns — and because `events.js`
stays silent about a connection Elm has already told it to drop. If a browser
ever delivered `onerror` for the server's normal end-of-stream *before* the
preceding terminal event's `update` completed, the UI would show a spurious
"the progress stream closed before it reported finishing". The consequence is a
misleading message on an already-finished separation, not a stuck panel; the
alternative — teaching `events.js` to recognise a terminal payload — would put
the decision in the layer that is deliberately dumb.

**The CI workflow does not use `pipenv`, deliberately.** The `Pipfile` installs
`sleepmix[all]`, which pulls demucs and torch — gigabytes, to run a suite that
passes without them through the graceful-degradation path every optional
dependency already has (the local run reports `Demucs separation unavailable
(no torch)` and passes). `.github/workflows/tests.yml` does
`pip install -e ".[dev]"` and `pytest -q` instead. It does not install Elm
either: the staleness guard is `ui/hash_sources.py`, which only reads files, so
a forgotten `make ui` is caught without a toolchain.

**A constraint carried forward from Plan 2b that shapes all of the above.**
Plan 2b's own document (below, under "Jobs, progress, and sessions") measured
that `POST /api/preview` serializes per song — including the cold path, where
building a `RenderSession` from scratch (separation + loop detection +
time-stretch) was measured at **117 s cold versus 73 ms warm** against a
2:43 test file. Plan 3b's own Task 7 repeated the measurement against a
different, 4:06 file with the separation cache freshly cleared and got
**180.55 s cold, 97–340 ms warm** — consistent with the older figure once the
~1.5× difference in track length is accounted for, not a contradiction of it;
see `docs/architecture.md` for the full breakdown of what each number
includes. Every request
against a cold song's session queues behind whichever request got there
first, and each queued request occupies one of FastAPI's AnyIO threadpool
threads for the whole wait, not just its own render time. A scrubber that
fires one `/api/preview` request per drag event — the naive implementation —
would, against a cold song, queue dozens of requests behind that single 117 s
render, each pinning a thread for the duration. **Plan 3b must coalesce or
cancel superseded preview requests rather than firing one per drag event, and
should not enable the scrubber at all until the song's session is warm** (the
per-song equivalent of `/api/health`'s `is_warm()`, which currently only
covers the process-wide librosa JIT warm-up, not per-song session state).
This is a requirement on 3b's design, not an optimisation to consider later.

**Two process lessons from this plan, carried forward because Plan 3b is
where they'll bite hardest.** First: an implementer on this plan, satisfying
a "see it in a browser" verification step, drove GUI automation against the
operator's own desktop — real Safari tabs, an unrelated Terminal window, a
Finder window with sensitive files open — and tripped a macOS TCC permission
dialog the operator had to notice and dismiss by hand. Verification on this
codebase goes through the API with `curl`, never a browser driver, an
AppleScript `do JavaScript` call, a screenshot tool, or a browser-automation
MCP. Plan 3b adds actual audio playback, which is a far more tempting thing
to want to "just see (hear) working" than a waveform was — the instruction
not to automate a browser matters more there, not less. Second: a server
started for manual verification writes to the operator's real library
(`~/Library/Application Support/sleepmix/library.db` on macOS) unless told
otherwise — this happened once during this plan and was caught and cleaned
up, but the instruction should not have allowed it to happen at all. Always
verify against `SLEEPMIX_DATA_DIR=$(mktemp -d)`; the test suite already does
the equivalent for automated runs via `tests/conftest.py`'s autouse
`isolated_data_dir` fixture.

## Plan 2b: what's built

`sleepmix/server/jobs.py`'s `JobManager` runs separation and renders on a
single background worker thread and fans progress out to per-subscriber
`asyncio.Queue`s; `server/api/jobs.py` exposes polling and cancellation plus an
SSE stream (`GET /api/jobs/{id}/events`) the eventual UI watches. `preview.py`
gained `master_gain` and a `master` parameter on `render_window` so
`POST /api/preview` (`server/api/preview.py`) can return one point in the
decay arc, loudness-matched to the render it represents, as raw WAV bytes in
well under a second. `server/sessions.py`'s `SessionRegistry` keeps up to two
`RenderSession`s warm so consecutive preview requests for the same song stay
cheap. `server/api/renders.py` starts a full render as a background job,
records it in the `renders` table from the moment it's queued, and serves the
finished file or a clean cancellation. `server/api/presets.py` adds named,
validated config snapshots over the `presets` table Plan 2a's schema already
had. `server/api/songs.py` gained `POST /api/songs/{id}/separate`, with a
`force` flag that calls `separation.invalidate_cache` — the fix for a
separation cache that used to keep reporting a stale "Demucs unavailable"
fallback forever, even after the `separation` extra was installed. See
`docs/architecture.md` for how the pieces above actually fit together — the
single worker, the thread-boundary progress hop, the session cap, and why
preview returns bytes rather than a URL are all explained there, not repeated
here.

Task 8, the last of this plan, carried forward four small items from Plan
2a's own final review (an inaccurate loopback-refusal message, a missing
API-level test for the peaks NaN/Inf coercion, an import placed for `flake8`
reasons rather than readability, and an over-claim in this document about an
`unreachable` code branch that turned out to be reachable) and closed three
deferred items from earlier in this plan: a sticky separation-cache fallback,
duplicate library rows for the same imported path, and an unvalidated
negative seed. A fourth earlier item — the Demucs fallback reason not
reaching a song's `separation_status`/`separation_reason` columns — turned out
to have been resolved by `POST /api/songs/{id}/separate` too, in passing,
before Task 8 started. Each of those is removed from the list below rather
than left listed, since leaving a resolved item as a known weakness is
exactly the kind of inaccuracy this document exists to avoid.

**If you're upgrading an existing `library.db`:** the `songs_path_unique`
index above cannot simply be added to a database that predates it, because
`add_song` had no dedup before this task and could already hold two rows for
one path — creating a `UNIQUE` index over duplicate values raises
`sqlite3.IntegrityError` and the server refuses to start. `Store.__init__`'s
`_SCHEMA` therefore runs a migration immediately before creating the index:
for every `path` with more than one row, it keeps the row with the lowest
`rowid` (the oldest import), re-points any `renders` that pointed at a
row about to be deleted onto the surviving one, and only then deletes the
duplicates. This runs on every open and is a no-op once a database has no
duplicates left — including a fresh one. The consequence for an operator who
already ran this server during development: the next time it starts, any
duplicate library entries silently collapse into one (keeping the earliest),
and that song's render history reappears whole under the surviving id rather
than split across two entries. Nothing is deleted from disk — only the
now-redundant `songs` row — so no render file is lost; only the extra
library-list entry pointing at the same path goes away.
`tests/test_store.py::test_opening_a_database_with_duplicate_paths_migrates_it`
exercises this by inserting a raw duplicate row (bypassing `add_song`, the
only way to still create one) and asserting a fresh `Store()` opens cleanly
and re-points the orphaned render.

## Plan 2a: what's built, and what it deliberately doesn't do yet

`sleepmix/server/app.py`'s `create_app` factory, `server/store.py`'s SQLite
store (songs/presets/renders tables), `server/warmup.py`'s startup JIT
warm-up, and `server/api/schema.py` + `server/api/songs.py` (import a song by
path, list/fetch songs, compute waveform peaks) are all there and tested.
`sleepmix ui` starts it, serving on `127.0.0.1:8765` by default and opening a
browser tab. It refuses a non-loopback `--host` unless `--allow-remote` is
passed, because the server has no authentication and `import_song` will read
any audio file the process can read — see the deferred-items section below for
the full shape of that constraint.

That's the whole surface. Plan 2a does **not** yet have: a preview endpoint
(`POST /api/preview` and the `audio.encode_wav` it needs), renders (starting,
cancelling, downloading, or a job manager to run them in the background), an
SSE progress stream, presets CRUD over the table Task 2 already created, or a
`RenderSession` registry keyed by song. All of that — the interactive
machinery — is Plan 2b. Until it lands, this server can register a song and
draw its waveform and nothing else; it cannot render or preview anything.

`sleepmix/static/index.html` was, at the end of Plan 2a, a deliberate
placeholder rather than a preview of the finished UI — `app.py` served it at
`/` only so there was something to load in a browser and confirm the server
was up. Plan 3a has since replaced it outright with a compiled Elm
application; see the Plan 3a section above and `ui/README.md`.

## Plan 1 (`feat/core-hooks`) recap

What it built: everything under "What each module owns" in
`docs/architecture.md` up to and including the server section —
`paths.py`, `progress.py`, `session.py`, `preview.py`, the config schema in
`config.py`, and the pre-existing render pipeline (`pipeline.py`,
`analysis.py`, `separation.py`, `timestretch.py`, `disintegration.py`,
`effects.py`, `soundbed.py`, `looping.py`) unchanged in behavior except where
noted below. Nothing in that branch served HTTP; `cli.py` still only did
`render` and `init-config`. It built the load-bearing capabilities a server
and a UI would need without exposing any of them to a user who wasn't calling
Python directly.

What still sat beyond both plans at that point: the Elm application itself.
Plan 3a has since built the library view and song view; the mixer, render
screen, schema-driven controls consuming `config_schema()`, and Web Audio
buffer swapping at loop boundaries using `render_window` remain Plan 3b — see
the Plan 3a section above. Segment selection and arrangement, output length as
an arrangement property, and a bundled desktop app are noted in the spec as
future work beyond any plan written so far.

## Accepted changes and caveats

**Renders are no longer byte-for-byte reproducible against output generated
before this branch.** `util.iteration_rng` derives each iteration's RNG from
`(seed, key, iteration)` — where `key` is `f"{source_id}:{index}:{stem}"`,
composed only in `disintegration.decayed_iteration`, and was a bare stem name
when this entry was written — instead of drawing from one `np.random.Generator`
threaded through the whole stream. The old approach made iteration *i*'s
noise depend on every draw before it, which made it impossible to reproduce a
single iteration without replaying the entire stem from the start — exactly
the cost interactive preview exists to avoid. This was a deliberate trade: a
preview that cannot match what the real render eventually produces at that
point is worse than no preview at all, and RNG determinism-by-history isn't a
property anyone was relying on (the render is still deterministic for a
given seed, just via a different derivation). If you have renders from before
this branch that you need to reproduce exactly, they cannot be — regenerate
them on this code if that matters.

**Render output changed a second time, later in this same branch.**
`disintegration.plan_iterations` was returning two more iterations than
`build_disintegrating_stream` actually executes, so the decay arc stopped
short — a 20-minute render off a 9-second loop reached progress 0.9932 and
never got to the configured `*_end` values at all, and
`preview.preview_iteration_index(session, 1.0)` pointed at an iteration no
render produces. Dropping the stray `+ 1` fixed both, and in doing so shifted
every render's iteration count by one and therefore its whole decay curve
slightly. This is a *second*, separate break in output compatibility, and it
means renders are not comparable across this branch's own history either —
output from an early commit on `feat/core-hooks` will not match output from
its tip. Byte-reproducibility was already deliberately forfeited above, so
this was accepted rather than worked around; but if you are diffing renders to
investigate something else, check which commit produced them first.

**Render output changed a third time, in Plan 4a, and this one was chosen
rather than discovered.** The per-repeat RNG key composed for
`util.iteration_rng` went from `stem` to `f"{source_id}:{index}:{stem}"` —
`"mix:0:vocals"` where it used to be `"vocals"`. It hashes differently, so
every noise draw in every render moves, so the samples move. Nothing about the
*arrangement* required this: at default gaps the repeats land on exactly the
frames they always did, and the regression test that proves it compares
placements, not audio bytes. The key changed because Plan 4c will add a second
source, and a key that did not name the source would have reshuffled the noise
in every existing source the moment a new one was added — which is the property
`util.iteration_rng` exists to provide, applied one level up. Paying that
break now, while a render is one source and one segment, costs a byte
comparison nobody is running; paying it in 4c would mean changing the sound of
every mix at the same moment as changing what a mix *is*. Anyone reading the
arrangement design spec's "bit-identical to the current renderer" phrasing
should read it as the placement claim it is: the number of repeats, their
frames, and their decay progress are unchanged, and the sample values are not.

**A preview window is bit-identical to the corresponding render iteration
pre-reverb, but only representative of it with reverb on.** `render_window`
applies each stem's decay and reverb (with that stem's `reverb_send`) in the
same order `pipeline._process_stem` does, so a dry preview and the dry render
at the same iteration produce identical samples. With reverb enabled they
diverge slightly, because a preview window is rendered in isolation and has
no reverb tail bleeding in from the *previous* iteration — a real render's
reverb is a continuous process across the whole stream, a preview's is not.
This was found and partially fixed during Task 9's review (see the addendum at
the end of `docs/superpowers/plans/2026-08-03-core-hooks.md`).

The tail-bleed gap has since been closed as far as it usefully can be.
`preview._reverbed_window` renders the *preceding* iteration as leading
context, reverbs it together with the window, and cuts the window back out at
an offset measured from the installed backend
(`effects.reverb_dry_offset`). So a wet window is now exactly as long as the
loop and opens with the previous iteration's reverb tail rather than the
pre-delay's silence — both of which matter because the UI plays this buffer on
a loop, where a longer-than-the-loop buffer that starts with 40ms of nothing
gaps and clicks every cycle. What remains is one approximation: the context is
concatenated, where a real render crossfades consecutive iterations over
`cycle_crossfade_ms`, so the reverb hears a join the render does not. A wet
window is therefore still representative rather than bit-identical; a dry one
remains exact.

**The separation cache moved.** It used to live at `.sleepmix_cache/`
relative to the working directory; it now lives under
`paths.cache_dir()` (a per-user app-data directory, see
`docs/architecture.md`). This repository still has a `.sleepmix_cache/` at
its root — roughly 170MB across two cached songs (`004542e5a96e70ee` and
`68b53b05350142ff`) — left over from before this branch. It is orphaned:
nothing on this branch reads it, so those songs will be re-separated (a real
Demucs call, ~10s+ depending on hardware) the next time each is rendered. It
can be deleted; nothing here depends on it existing.

## Known weaknesses, deferred deliberately

These were identified and left as-is; each has a reason it wasn't worth
fixing in the branch that found it. Plan 1 (`feat/core-hooks`) items are
listed first, followed by Plan 2a (`feat/server-foundation`) items, followed
by Plan 2b (`feat/interactive-server`) items, followed by Plan 3a
(`feat/elm-shell`) items found during this plan's review, followed by Plan 3f
(`feat/legibility`) items found during this plan's own final task, which is
also where two stale entries above were caught up with the code: the
`JobManager` leak, which is genuinely **closed**, and the renders resource
problem, which is only **half** closed — there is a delete route now, but
still no automatic pruning, no size cap and no retention policy, so read that
entry rather than this sentence. A third (the `shutil` import) was found
alongside them and is closed.

- **Four things contribute to a render's final peak that `master_gain`'s
  calibration window never sees.** `preview.master_gain` measures one window
  and derives a gain from its peak. `pipeline.run_pipeline` peak-normalizes
  something rather different, and each difference moves a preview off the
  render's level.

  **Which window that is changed in Plan 4a, and everything below was measured
  before it.** This entry was written when the window was always
  `render_window(session, 0.0, reverb=<the flag>, master=False)` — iteration 0,
  on the argument that decay only removes energy so nothing later can be
  louder. Overlapping repeats disproved that argument (see the Plan 4a section
  above): `master_gain` now asks `arrangement.densest_frame` which frame
  carries the most concurrent amplitude, renders the window at the decay
  progress of whichever placement dominates there, and multiplies the measured
  peak by a density ratio. **At every configuration these four items were
  measured under — no gaps, no overlap beyond an ordinary crossfade seam — that
  resolves to frame 0, a ratio of exactly 1.0, and the same window this entry
  describes, bit-identically.** So the four figures below stand as measured.
  What does not automatically carry over is the *reasoning*: an argument here
  of the form "nothing can move a number measured at progress 0" is now an
  argument about the default arrangement rather than about the decay arc, and
  a gap or an overlap can move which window is measured at all.

  Listed by measured magnitude, largest first, with a caveat the first
  entry itself is now the record of: the largest number here had the wrong
  story attached to it for a whole branch, corrected only once someone
  measured directly instead of inferring. All four were measured the same
  way: RMS of a mid-arc mastered preview over the corresponding crossfade-free
  region of a real `run_pipeline` output, changing one thing at a time —
  **not at default config, but at `tests/test_preview.py`'s `_level_cfg()`**,
  which deviates from `MixConfig()` in three ways that all matter here:
  `output.duration_min = 0.5` (a 30-second render), `output.sample_rate =
  22050` (matched to the working rate so nothing resamples — material,
  because item 3 below is *about* `output.sample_rate`), and both fades
  zeroed. The baseline — default reverb, `reverb=True`, fades off — is
  **1.0003, +0.00 dB**, and is what `tests/test_preview.py`'s
  `test_a_mastered_preview_sits_at_the_render_s_level` now asserts.

  1. **The 1.82 dB attributed to fade ordering does not describe the mixer's
     actual default render, and the transient-at-t=0 hypothesis that replaced
     it as a first guess doesn't either — but the figure itself turned out to
     be exactly reproducible, and content-dependence is the reason both of
     those things are true at once.** The figure — **0.8107, −1.82 dB** —
     is real, traced this task to its literal source, and stays recorded.

     **Where the number actually comes from.** `tests/test_preview.py`'s
     `_level_cfg()` builds a `MixConfig` with `output.duration_min = 0.5`
     (a 30-second render, for a fast, well-posed test) and both fades
     zeroed; its own docstring already said "at the default 8 s fade-in the
     same measurement reads −1.82 dB" — this task confirmed it rather than
     taking the docstring's word for it. Re-running
     `_preview_to_render_ratio` (the RMS-of-mid-arc-window method the
     baseline above uses) against `_level_cfg()`'s synthetic stems
     (`conftest.fake_separate`: four stems, each one pure sine at
     `110 × (i+1)` Hz, of which the default config enables three — not a
     real recording) reproduced both figures this document already carried,
     essentially exactly: fades zeroed gives **1.0003181, +0.0028 dB**
     (matching the recorded baseline "1.0003, +0.00 dB"), and setting fades
     to the real `MixConfig` defaults (8 s in / 12 s out) gives
     **0.8107466, −1.8223 dB** (matching the recorded "0.8107, −1.82 dB" to
     four figures). **The number is exactly right for the config it was
     measured in.** That config is a 30-second render — where an 8 s fade-in
     plus a 12 s fade-out cover 20 of the render's 30 total seconds, two
     thirds of the whole arc, not the 0.67% of a 20-minute arc that Plan 3f's
     own design note assumed. That figure is not from this entry, which never
     carried it; it is in
     `docs/superpowers/specs/2026-08-05-legibility-design.md` (line 147) and
     restated in `docs/superpowers/plans/2026-08-05-legibility.md` (line 495).
     Plan 3e's level-matching design carries the same arithmetic without the
     percentage, in
     `docs/superpowers/specs/2026-08-05-level-matching-design.md` (lines
     21-23). The entry conflated "this
     number is real" with "this number describes the mixer's actual default
     render" — only the first is true.

     **What the mixer's actual default does, measured directly rather than
     re-inferred (Task 6 of this plan):** a render at the real default
     config (`duration_min = 20`) against a throwaway `SLEEPMIX_DATA_DIR`,
     stems supplied via `sleepmix.separation._write_cache` from this
     repository's own orphaned separation cache
     (`.sleepmix_cache/004542e5a96e70ee/`, a real 2:43 track — the same one
     Plan 2b's cold-session-build measurement above uses, and **not** the
     4:06/246.6 s track Plan 3b's Task 7 and Plan 3c's render-timing figure
     use; the two are different source files and a reader comparing numbers
     across this document should not assume otherwise), reporting on the mix
     immediately before `_apply_fades`. **The global peak is not at t = 0.**
     It sits at t = 14.657 s of a 1200 s render (sample 646,351 at 44.1 kHz)
     — roughly one loop-length (11.0 s) past the start, comfortably outside
     both the 8-second fade-in and the last-12-second fade-out. It is
     **7.12 dB** above the 99th percentile of |sample| across the whole
     render (1.358 vs. 0.598), so it is a real, audible peak rather than a
     lone outlier in the noise floor. It is **40 samples (0.91 ms) wide** at
     half its own height, and the raw samples across that width rise and
     fall smoothly — not a one- or two-sample discontinuity — which reads
     as a genuine moment in the music (most plausibly the `bass` stem, the
     most energetic of the three stems enabled by default with `drums` off)
     rather than a decoder or splice artefact. It survives
     `cycle_crossfade_ms = 0` bit-for-bit — identical sample index,
     identical value to the last digit — which rules out the inter-iteration
     crossfade (item 2, below) as its cause. And directly comparing the
     pipeline's own `normalize_peak` gain factor with fades at their default
     8 s/12 s against the same fades zeroed, at this exact config, gives the
     identical factor either way — **0.6564188599586487, both times, to the
     last digit.** Separately, `preview.master_gain(session, reverb=True)`
     for this render is 0.6564188545205888 — equal to that same factor to
     eight significant figures, a **0.00 dB** gap, not 1.82, measured by
     direct comparison of the two gain factors rather than by the RMS method
     above. Repeating that same direct gain-factor comparison at
     `duration_min = 0.5` — matching the short-render *length* the 1.82 dB
     figure was measured at, but with these same real stems instead of
     synthetic sine tones — again gives an identical factor with fades on or
     off. **So the arc length is not what makes the difference; the content
     is.**

     **The mechanism, and why both are true at once.** This paragraph
     previously said the fixture's un-faded peak was "guaranteed to sit at
     t = 0, because nothing else in the signal can ever exceed it." **That is
     false, and it is false about the fixture this entire entry exists to get
     right.** `conftest.fake_separate` does not build one decaying tone; it
     builds four separate stems, each a single sine at `110 × (i+1)` Hz —
     110, 220, 330 and 440 — and `sin(0) = 0`, so every one of them is
     *exactly zero* at t = 0 and so is their sum. Measured directly, on the
     mix `run_pipeline` hands to `_apply_fades`: the sample at t = 0 is
     `0.000000000`, and the un-faded global peak sits at **t = 0.741 s**
     (sample 16,338 at 22.05 kHz, value 1.106689), where the signal first
     aligns constructively after the reverb has built up.

     **The conclusion survives; only the mechanism was wrong**, and the real
     mechanism is stronger. 0.741 s is 9% of the way into an 8-second
     fade-in, so the fade multiplies the loudest moment in the render by
     roughly a tenth. With fades zeroed, `normalize_peak` sees 1.106689 at
     0.741 s. With `MixConfig`'s real 8 s/12 s defaults it sees **0.896959**,
     relocated to **t = 10.443 s** — not "just past the fade-in", which is
     the tidy answer and the wrong one, but simply the loudest moment in the
     un-attenuated middle of the arc, anywhere in the 8 s–18 s window where
     neither fade reaches. (The signal at 8.343 s, where an earlier draft of
     this paragraph put the surviving peak, is 0.109321 — not a peak at all.
     That draft was measured against a 6-second source song's stand-in that
     happened to be 8 seconds long; `conftest.fake_separate` derives its
     sines from the source file's *length*, so a different-length input is a
     different signal. It reproduced the pre-fade peak exactly, which is what
     hid the error.) The peak ratio is 0.810489, or **1.83 dB of extra gain
     applied to everything else.**

     **That 1.83 dB is the same quantity as the −1.82 dB above, computed a
     second way — not a second measurement of it.** It is worth being exact
     about this, because the whole entry is about a number that was believed
     for a branch on the strength of a story rather than an arithmetic check.
     `_preview_to_render_ratio` divides a mastered preview's RMS by the
     render's over the same region; the preview carries `master_gain` =
     target ÷ peak-of-window and the render carries `normalize_peak`'s factor
     = target ÷ peak-of-render, so the RMS ratio *is* peak-of-render ÷
     peak-of-window. Dividing the recorded fades-on figure by the recorded
     baseline therefore recovers the peak ratio directly:
     0.8107466 ÷ 1.0003181 = 0.8104888, against 0.896959 ÷ 1.106689 =
     0.8104888 measured — agreeing to every digit shown because they
     are one quantity expressed twice, and in dB because −1.8251 + 0.0028 =
     −1.8223, the recorded figure exactly. **This confirms the arithmetic,
     not the hypothesis.** What it rules out is a transcription or
     methodology error in the recorded number; what it cannot do is tell you
     *why* the peak moves, which is what the paragraph above had to measure.
     So the original fade-ordering story is a correct explanation for the
     signal it was measured against; it just does not need the peak to be at
     t = 0, and it never was. A real 2:43
     recording has no such guarantee — its loudest moment is wherever the
     music happens to be loudest, and at this stem set that turns out to be
     3.65 s into the render's second pass through the loop, nowhere near
     either fade, at both output lengths tested. The assumption `master_gain`
     used to carry in its own docstring — "decay only removes energy, so the
     peak falls monotonically across the arc and iteration 0 is the loudest
     window this module can produce" — is true of the synthetic signal it is
     usually verified against and was never reliably true of real material,
     where decay is negligible this early in the arc and which of the first
     several iterations is loudest tracks the music, not iteration order.
     **Plan 4a has since removed that assumption outright**, for a second and
     independent reason: overlapping repeats can put more amplitude at a later
     frame than at frame 0, so the window is now found rather than assumed
     (see the Plan 4a section above). The measurement recorded here is the
     earlier of the two disproofs and the milder one — it says the assumption
     was unreliable on real content; overlap says it is false outright.

     Both explanations this document has carried for the 1.82 dB are
     therefore not simply wrong: the transient-at-t=0 guess is wrong outright
     (Step 1 found a real transient, just not at t=0, and not affected by
     the fade); the original fade-ordering story is *correct*, reproduced
     exactly, for the synthetic short-duration fixture that produced the
     number, and does not generalize to what the mixer's real default does
     with a real recording, where the same measurement — at either the
     fixture's 30-second length or the mixer's real 20-minute one — reads
     0.00 dB. The live, evidenced explanation for the gap between the
     recorded figure and the mixer's real behavior is content-dependence:
     whether the calibration and normalization windows agree depends on
     whether the material's own loudest moment sits where a fade (or,
     failing that, nothing at all) can move it — true by construction for a
     decaying pure tone, and, on the one real track measured here, false at
     every duration tried. **Why this is not being closed regardless of
     which regime a given render falls into:** `preview.render_window`
     applies one gain factor to every window, computed once per `reverb`
     setting and memoized on the session (`sleepmix/preview.py:101`), so the
     ratio between a preview at the start of the arc, the middle and the end
     is exact whatever the true offset between `master_gain` and
     `normalize_peak` turns out to be for a given song. A uniform offset
     cannot change any comparison the mixer exists to support. See Plan 3e's
     retirement, in the Plan 3f section below, for the fuller reasoning.
  2. **The inter-iteration `equal_power_crossfade` can sum above a single
     iteration's peak.** Two consecutive decayed iterations overlap for
     `cycle_crossfade_ms`, and their sum in that region can exceed either
     one alone, so `normalize_peak` pulls the whole render slightly further
     down than a one-window calibration predicts. Measured on the dry path
     (`reverb.wet = 0.0`, `reverb=False`): **1.0431, +0.37 dB**, which drops
     to 0.9995 with `cycle_crossfade_ms = 0.0` and nothing else changed —
     so the residual is entirely this. With default reverb it is masked to
     about 0.01 dB, because reverb smears the peak either way. Still open.
  3. **A preview and a render can disagree by about 0.01 dB with default
     reverb on, and the reason is the calibration window, not the memo that
     caches its result.** Still open. This entry has been closed once and
     reopened, and the round trip is the part worth keeping.

     **What was closed, and why it was reopened.** The entry used to read
     "`output.sample_rate` is absent from `RenderSession._master_key`,
     although `run_pipeline` resamples before normalizing" — and Task 5 of
     Plan 3f added it (commit `1500e39`), with a review that traced the
     invalidation chain end to end and found every link sound: a changed
     rate gives a different key, the comparison in `update_config` fails,
     `master_gain.clear()` runs. Every link was true. **Nobody measured the
     value at the far end of the chain.** The final review did, and it is
     bit-identical:

     ```
     sample_rate=22050   wet=0.5556662371509203
     sample_rate=44100   wet=0.5556662371509203
     sample_rate=48000   wet=0.5556662371509203
     peak_db=-6  (control)   wet=0.31247408816298333
     channels=1  (control)   wet=0.5853150780716774
     ```

     Reproduced independently during the fix wave against a different
     synthetic song (different absolute figures, same invariance: all three
     rates identical to the last digit, both controls moving). The reason is
     one line: **`preview.render_window` never resamples.** It works end to
     end at `loop.sr`, and `output.sample_rate` is read in exactly one place
     in the whole codebase — `sleepmix/pipeline.py:81`, the resample before
     normalizing — which every preview path has already finished before. So
     adding `sample_rate` to `_master_key` *cannot* change the value
     `_master_key` guards. What it can do is make the operator pay a full
     extra calibration window on a rate change, which is precisely the cost
     `_master_key`'s own docstring exists to prevent. Task 5's change and
     its test were reverted in the final fix wave; the docstring now records
     the measurement so the field is not re-added on the same reasoning.

     **What is actually still open** is the residual this list's baseline
     leaves behind: with default reverb the preview-versus-render offset
     measures about **0.01 dB** (see item 2 — the crossfade's +0.37 dB on
     the dry path is masked to roughly that with reverb on). That is a
     *calibration-window* gap — the window `master_gain` measures is not
     quite the signal `normalize_peak` sees — and no change to the memo's
     key can move it. Closing it means changing what the window contains,
     which is items 1, 2 and 4 in this list, not this one.

     **The other absences from `_master_key` were not bugs, and this entry
     previously said they were.** `fade_in_s`/`fade_out_s`,
     `cycle_crossfade_ms` and `config.soundbed` were all absent from the key,
     and Plan 3f's Task 5 recorded that as a second real defect — that even
     with a perfect calibration window, a session would keep serving a stale
     gain after the operator moved the fade-in slider. **Measured, it did
     not:** the gain was bit-identical with `cycle_crossfade_ms = 0`, with
     both fades zeroed, with `soundbed.enabled = True`, and with
     `duration_min = 40`.

     **`config.soundbed` is the exception, as of Plan 3g, and it is the
     cleanest illustration of what the rule actually is.** That plan put the
     bed into `render_window` — so the calibration window began reading the
     field, the absence stopped being correct, and `soundbed` joined the key
     in the same commit. Nothing about the *render's* dependence on the bed
     changed; it always had one. What changed is what the window measures.
     Membership of this key has never been about whether the render depends
     on a field. `output.sample_rate` is the same lesson pointing the other
     way: the render genuinely resamples before normalizing, and the field
     still does not belong here, because the window does not.

     **`output.cycle_crossfade_ms` is the second exception, as of Plan 4a,
     and it is the same lesson arriving a third time — this time by having
     the ground move under a measurement that was correct when it was
     taken.** The paragraph immediately below still records why that field
     could not move the calibration window: the crossfade changed only the
     iteration *count*, and progress at iteration 0 is 0 whatever the count.
     That was airtight while `master_gain` always measured iteration 0. It
     does not any more. `arrangement.densest_frame` and
     `concurrent_placements` take the crossfade width and use it to decide
     which overlaps are an ordinary seam (blended into one voice) and which
     are genuine stacking (summed as two or more), which changes both *which*
     placement dominates the densest frame and *how many* are concurrent
     there. Re-measured on a `gap_start_s = gap_end_s = -3.0` config,
     sweeping `cycle_crossfade_ms` from 0 to 3000 ms moves `master_gain`
     across a **~7.0 dB** span. It joined `_master_key` in the same fix wave
     that found this — one commit after the commit that made it matter, which
     had left the memo stale. `config.arrangement` itself is in the key for
     the same reason and was there from the start.

     **Every stem's `decay`, and `seed`, are the third exception — added in
     Plan 4a's final fix wave, and the largest field this rule has yet been
     turned on.** `decay` was not excluded on a measurement at all; it was
     excluded on an explicit claim written into `_master_key`'s own
     docstring: *"It is measured from iteration 0, where `apply_decay`
     returns the loop untouched — so no decay setting can move it."* That
     claim expired in the same commit that added `densest_frame`.
     `master_gain` no longer measures iteration 0 — it renders at
     `dominant.decay_progress`, observed as far along as **0.29** on ordinary
     gap arcs — and it weights the result by `concurrent_amplitude`, a
     function of `amp_start_db`, `amp_end_db`, `curve` and `enabled`. Measured
     stale-memo error, by the standard method (compute the gain, change only
     a decay field through `update_config`, compare against a session built
     fresh on the new config): **−3.00 dB** at a −2 s gap, **−6.00 dB** at
     −4 s, **−9.98 dB** at −6 s, and **+6.94 dB** for switching decay off on a
     4/−6 s arc. `server/sessions.py` calls `update_config` on every
     `POST /api/preview`, so every one of those persisted for the life of the
     session. Re-measured after the fix, all of them are +0.00 dB.

     `seed` joined in the same change on a much smaller measurement and an
     older cause: `render_window` builds the calibration window's sound bed
     from `np.random.default_rng(cfg.seed)`, worth +0.02 dB on the default bed
     and up to +0.343 dB on a louder one. Pre-existing since Plan 3g rather
     than introduced by the arrangement work.

     **The cost is accepted knowingly, and it is the exact cost the exclusion
     existed to avoid**: a decay-slider drag now pays one extra calibration
     window — a single `render_window` call — where before it paid nothing.
     Against a silent level error of up to about 10 dB, in the one number a
     preview exists to make judgeable, that is not a close call. What makes
     it stranger than the earlier two exceptions is that this one was never a
     measurement that expired; it was an argument that was wrong the moment a
     neighbouring function changed, and nothing re-derived it. The lesson
     below applies with more force to a *claim* than to a measurement.

     **So read the paragraph below as history, not as instruction.** Of the
     four fields it names as safely excluded, `cycle_crossfade_ms` is no
     longer one of them; `output.duration_min` is still excluded but only
     just, on a re-measurement (0.073 dB on a negative-gap config, where it
     does now feed the placement count through `plan_arrangement`); the two
     fades remain excluded on the original, undisturbed reason. **A field's
     absence from this key is a measurement with an expiry date, not a
     theorem.**

     **Two different reasons, and an earlier draft of this paragraph got
     both wrong** — in the entry whose whole lesson is *measure, do not
     trace*. It said `render_window` "takes the empty-context branch
     (`sleepmix/preview.py:196-199`), so it never reaches the crossfade, the
     fades or the bed." Those lines are `_reverbed_window`'s reverb-context
     branch, which has nothing to do with fades or the bed, and
     `cycle_crossfade_ms` **is** read on the preview path. The real reasons:
     - *The fades.* `sleepmix/preview.py` imports no fade function and no
       `normalize_peak`. Those two stages exist only in
       `pipeline.run_pipeline`, so `render_window` cannot see them at any
       progress, not merely at 0. (**This said "and no `build_soundbed`"
       until Plan 3g**, which imported exactly that — which is why the bed is
       now in the key and the fades still are not.)
     - *The crossfade.* `preview_iteration_index` did pass
       `cfg.output.cycle_crossfade_ms` to `plan_iterations`, so changing it
       genuinely changed `n_iterations`. It still could not move the
       calibration window, because `decayed_iteration` computes
       `progress = iteration / max(n_iterations - 1, 1)` — which is 0 at
       iteration 0 for every `n_iterations`. The window was the undecayed
       loop either way. (Both halves of that have moved since:
       `preview_iteration_index` reads `plan_arrangement` now, and the
       conclusion is overturned outright — see the exception above.)

     **The
     memo was sound as written and three of these four fields must not be
     added to `_master_key`** — doing so would buy nothing and cost a
     calibration
     window each, which is how item 3 got closed wrongly the first time.
     The calibration-window gaps those same fields *do* cause are items 1, 2
     and 4; that they name the same fields is a coincidence of which stage
     the window skips, not evidence of a second bug.
  4. **The sound bed was never mixed into the calibration window. CLOSED by
     Plan 3g.** `render_window` summed only the configured stems and never
     called `soundbed.build_soundbed`, while `run_pipeline` adds the bed
     before normalizing. This was previously recorded here as "the most
     important gap left in the level-matching" — measurement said otherwise,
     and by a wide margin. At the default `noise_gain_db = -34` it moved the
     ratio to **1.0031, +0.03 dB**; even at `-6 dB` it only reached **0.9947,
     −0.05 dB**, because `normalize_peak` scales the stems down by very
     nearly the same factor the bed pushed the peak up, so the two mostly
     cancel. `SoundbedConfig.enabled` defaults to `False` in any case.

     **It was not closed for the +0.03 dB.** Plan 3g put the bed into
     `render_window` because its absence from *previews* was a gap in
     character rather than level — turning on binaural beats changed nothing
     you could hear in the mixer — and closing that incidentally closed this.
     The level correction is a side effect of fixing the audible problem, not
     the reason anyone touched it.

  **One of the four is still open: item 2, the crossfade.** Item 1's figure
  turned out to describe a synthetic test fixture rather than the mixer's
  default; item 3's cache half was disproved and its level half is a
  calibration-window difference of about 0.01 dB; item 4 closed with Plan 3g.
  The remaining one stays open deliberately — see Plan 3e's retirement below
  for why closing these was judged not to serve the mixer's actual job. Item 3 was
  briefly marked closed by Task 5 of this plan and reopened by the same plan's
  final review, on a measurement; the entry itself records the round trip,
  because "the invalidation chain is sound" was true and beside the point.
  They were recorded in the first place because the sizes were
  counter-intuitive — the one written down first was the smallest, and the
  largest had never been measured against the mixer's actual default until
  this task did it, and found the number it already had on file described a
  test fixture rather than the mixer.

- **Nothing is ever reclaimed, and the one that mattered most is now closed
  halfway.** Ranked by how much it actually costs. The first two were both
  addressed by the same commit, `feat/render-queue` (Plan 3c), and neither was
  caught up with in this document until now — but they landed differently, and
  the difference is the point of the heading: the second is closed, the first
  is not. Read each entry, not this summary.

  ~~Render output files accumulate forever. There is no `DELETE
  /api/renders/{id}`, no pruning, no size cap and no retention policy.~~
  **Half closed, by Plan 3c.** `DELETE /api/renders/{render_id}`
  (`sleepmix/server/api/renders.py:125`, commit `16125cc`, `feat: honour
  cancel before a job starts, bound job retention, delete renders`) exists
  now — refused with a 409 while the render is still queued or running, and
  otherwise removing both the database row and the file on disk; it is what
  the render screen's Delete button calls. What the entry actually named as
  the resource problem is still true, though, and this document should not be
  read as having closed it: there is still no *automatic* pruning, no size
  cap, and no retention policy, so a project that never visits the render
  screen to clean up after itself still accumulates the same roughly **300 MB
  per render** (default 20-minute duration, 44.1 kHz stereo float32) it always
  did. What changed is "no way to reclaim the space at all" becoming
  "reclaiming it is a manual, per-render click" — a real improvement, not the
  same thing as the original problem being solved.

  ~~`JobManager._jobs`, `_tokens` and `_subscribers` are never evicted.~~
  **Closed, by Plan 3c.** `JobManager(..., keep_terminal=50)`
  (`sleepmix/server/jobs.py:63`) and `_evict` (`:220`), called from `_update`
  whenever a job reaches a terminal status, drop the oldest terminal jobs
  from all three dicts once more than `keep_terminal` have accumulated, and
  never drop a queued or running one regardless of how many there are — kept
  as history rather than deleted because the leak this entry described was
  real when written, and the reasoning for why live jobs are exempt (the
  queue screen's whole purpose is to say what is about to happen) is worth a
  maintainer having on hand.

  **`SessionRegistry._use_locks` is only cleared in `clear()`.** Still true,
  still open — nothing in Plan 3c or any later plan touched
  `server/sessions.py`'s eviction. One `RLock` per song id ever previewed,
  deliberately kept past eviction so a thread holding one cannot have it
  swapped out from under it. A few dozen bytes each, bounded by distinct
  songs previewed in a process — the smallest of the three, and noted only so
  it is not mistaken for an oversight.

- **A `BaseException` escaping a job leaves it stuck at `"running"` forever.**
  `JobManager._run` catches `Cancelled` and `Exception`, but a `SystemExit` or
  `KeyboardInterrupt` raised inside a job function would propagate past both,
  and nothing in `_run` would ever set a terminal status — the job's row (and
  any render or song row it was updating) is left reporting `"running"`
  indefinitely, and the SSE stream watching it never closes.

- **No test exercises SSE client-disconnect cleanup, and the heartbeat branch
  is untested.** `server/api/jobs.py`'s `stream_job` unsubscribes in a
  `finally` block whose correctness rests entirely on Starlette propagating
  cancellation into the generator when a client goes away mid-stream — nothing
  in `tests/test_api_jobs_sse.py` drops a connection before a job finishes to
  prove that actually happens. The `asyncio.TimeoutError` → `": keepalive\n\n"`
  branch, reached when `_HEARTBEAT_SECONDS` (15s) elapses with no event, is
  likewise never driven by any test.

- ~~`separation.invalidate_cache` imports `shutil` inside the function, while
  the module imports `os` and `hashlib` at the top.~~ **Closed by Plan 3c, as
  a side effect rather than a deliberate fix.** `fix: publish the stem cache
  atomically` (commit `f87632b`) moved `import shutil` to the top of
  `sleepmix/separation.py`, alongside `hashlib`, `os`, `tempfile` and
  `warnings`, because the new atomic `_write_cache` needed `shutil.rmtree` at
  module scope for its staging-directory sweep and its rename-then-remove
  dance — the local import inside `invalidate_cache` became redundant in the
  same commit and is gone. Nobody was checking this document against that
  diff at the time, which is exactly the kind of drift this pass exists to
  catch.

- **`encode_wav` has no test with a mono buffer.** `tests/test_audio_encode.py`
  only ever builds stereo (and empty-stereo) buffers; a single-channel
  `AudioBuffer` going through `encode_wav` is untested.

- **`presets.py` validates a config only through a call whose result it
  discards.** `create_preset` calls `MixConfig.from_dict(body.config)` purely
  so a bad config raises `ValueError` (turned into a 400) before anything is
  stored — the returned `MixConfig` is never used; the raw dict is what gets
  saved. That made the validation a side effect of a call that looked like
  dead code, one `# unused` cleanup away from being deleted along with the 400
  path it provides; it is now bound to `_validated` with a comment saying so,
  which is a speed bump rather than a fix. Separately: `start_render` *does*
  independently reconstruct
  and validate a `MixConfig` from whatever config it's given, preset or not, so
  a preset is never actually used unvalidated — but nothing prevents an
  invalid preset from being *saved* in the first place except that same
  discardable call, so if it were ever removed, a bad preset would fail
  silently at save time and loudly, later, the first time someone tries to
  render with it.

- **`RenderSession`'s loop-stage cache key is coarser than it needs to be.**
  It covers all of `LoopConfig`, so changing only `crossfade_ms` — which only
  feeds `make_seamless`, not `find_loop` — invalidates the loop point and
  pays a ~1s `find_loop` recompute anyway. The fix is to split the cache key
  so `crossfade_ms` invalidates only `prepared_loop`'s cache, not
  `loop_point()`'s. Not done because no caller yet changes `crossfade_ms`
  interactively without also touching something that already invalidates
  the loop.

- **`test_reporter_receives_ordered_monotonic_events` cannot fail.**
  `ProgressReporter.emit` clamps its own output to be monotonic
  (`docs/architecture.md`), so this test is asserting a property the code
  under test enforces on itself — a regression in `pipeline.py`'s per-stem
  `stage_range` arithmetic that produced out-of-order *inputs* to `emit`
  would be silently absorbed by the clamp and this test would still pass.

- **`analysis._estimate_tempo` and `_librosa_loop` each have their own
  `librosa.beat.beat_track` call site.** The two paths are mutually exclusive
  within a single `find_loop` call — an explicit `start_s`/`end_s` short-
  circuits auto-detection entirely, so `beat_track` is never invoked twice in
  one call — but the duplicate call sites could still share a helper.

- **`MixConfig.separation_model` carries no field metadata.** Every
  other config field has a `label`/`help`/bounds dict for `config_schema()`
  to read; this one falls through to an auto-generated label
  (`"Separation model"`) and no help text, because it sits
  directly on `MixConfig` rather than in one of the nested per-section
  dataclasses `config_schema()` was designed around. (`seed` sat there too
  until Plan 3b gave it `label`, `min: 0`, `step` and `help` — see the entry
  above on bounds being the schema's job. Giving `separation_model` a
  `choices` list is the obvious next move and is parked with the rest of the
  separation-model question.)

- **`MixConfig`'s validation layer covers one field.** `MixConfig.validate()`
  (called from `MixConfig.from_dict`, which every config-accepting endpoint —
  presets, preview, renders — routes through) rejects a negative `seed`, and
  that is the only thing it checks. `config_schema()` publishes bounds
  (`min`/`max`/`step`/`choices`) for every other field, but nothing enforces
  them — they remain advisory metadata for a UI to build controls from. A
  config posted with `tempo.speed: 50` is still accepted and rendered.

- **The cache write is a single atomic rename now, superseding a two-step
  ordering this document used to describe as current.** `separation._write_cache`
  builds the fallback marker (if any) and every stem into a sibling staging
  directory and renames the whole thing into place in one step
  (`docs/architecture.md` has the full mechanism and why Plan 3c's killable
  separation is what forced it). An interrupted write, from any cause, now
  leaves either the complete previous cache or no cache at all — never a
  marker with no stems, and never stems with no marker.

  **The old two-step version, and the reasoning that justified its ordering,
  is worth keeping as history rather than deleting outright.** Before this,
  `_save_fallback_reason` wrote the marker and a separate `_save_cache` wrote
  the stems, in that order, directly into the final cache directory, on
  purpose: a failure between the two steps left a stale marker with no stems
  (which `_load_cache` — requiring at least one `.wav` file to report a hit —
  correctly read as a miss and recomputed) rather than stems with an
  unrecorded fallback, which would have read as a properly separated song
  that happened to have one stem. `_load_cache`'s cache-hit check does not
  save a caller from that branch, because it fires *before* the branch is
  ever reached, on the *next* call — an earlier version of this document
  claimed otherwise and was wrong to. If the marker survived and a later
  recompute succeeded without a fallback, `_save_fallback_reason` was called
  with `reason=None` and removed the stale marker it found still sitting
  there — the one route to that branch that mattered, and the reason it was
  kept rather than deleted despite looking like dead code.
  `tests/test_separation.py::test_a_marker_without_stems_does_not_masquerade_as_success`
  still exercises the same shape of failure — a write that does not complete
  must not be trusted on the next call — against the current atomic
  `_write_cache`, by forcing it to raise outright; the two-step ordering it
  used to exercise no longer exists to test.

- **`Store` is locked now — and the reason the earlier deferral was wrong is
  worth keeping.** An earlier version of this document claimed "every request
  in this plan runs on FastAPI's single event loop." **That was false.** Every
  route in `server/api/` is declared `def`, not `async def`, and FastAPI runs
  sync path-operation functions in an AnyIO threadpool — instrumenting
  `Store.list_songs` and issuing `GET /api/songs` records the call on an
  `AnyIO worker thread`, not `MainThread`. So the store was already reachable
  from several threads at once, and would have been from the Elm UI's very
  first paint, which fires several requests in parallel by design.

  `sqlite3.threadsafety` is 3 (SERIALIZED) on the development machine, so
  nothing corrupted — but that is platform-dependent, and
  `check_same_thread=False` disables the only guard Python offers. Two
  problems were real regardless of the platform: `commit()` is
  connection-wide, so one thread's commit flushes another's in-flight implicit
  transaction; and `update_song`/`update_render` are read-modify-write
  (`get` → `UPDATE` → `get`) and lose updates under concurrency.

  Every public method on `Store` now holds a `threading.RLock` for its whole
  body. **`RLock`, not `Lock`** — `update_song` calls `get_song` while already
  holding the lock, and a non-reentrant lock deadlocks there on the first
  update (verified). `tests/test_store.py::test_concurrent_writers_and_readers_do_not_lose_rows`
  exercises it with eight threads. Plan 2b's `JobManager` (`server/jobs.py`)
  did go on to add a genuinely separate worker thread writing into `renders`
  and `songs`; the lock was already in place for it, and nothing about that
  addition needed to touch `Store`.

- **`load_audio` still materialises the whole file in RAM, on every `/peaks`
  request.** `server/api/songs.py`'s `import_song` decodes the file once to
  get `duration_s`/`sample_rate` for the store row, and `get_peaks` decodes it
  again, in full, on *every* call — there is nothing between a request and
  `soundfile.read`. That is repeated cost every time a waveform is drawn, and
  it is worse than slow: a one-hour 96 kHz stereo file is roughly 2.7 GB as
  float32, and `import_song` accepts any path, so a single request can OOM the
  process. `soundfile.blocks()` would make peak computation O(1) in memory and
  is the obvious fix — peaks are a streaming reduction and never need the
  whole array at once. Not done in Plan 2b either; still worth doing before
  the eventual UI starts calling `/peaks` on every song-view load.

- **`import_song` accepts an arbitrary absolute filesystem path from the
  request body with no allow-listing.** It resolves `~` and relative
  components and 400s cleanly if the result isn't a readable file — it
  doesn't crash — but nothing restricts *which* files under the operating
  system's permissions it will read, and `/peaks?buckets=20000` will hand back
  a detailed summary of whatever it read. That's acceptable for what this is:
  a loopback-only tool reading the operator's own music on their own machine.
  It stops being acceptable the moment the server is bound anywhere else.

  That constraint is no longer implicit. `cli.py`'s `ui` command refuses a
  non-loopback `--host` unless `--allow-remote` is passed, and says why in the
  refusal; the README's UI section says the same thing in prose. **A path
  allow-list is still the thing that would actually make a non-loopback bind
  safe, and it does not exist** — `--allow-remote` is an informed-consent
  switch, not a mitigation.

- **DNS rebinding is now mitigated by a `Host` allow-list.** Binding loopback
  stops other machines from connecting; it does not stop a web page the
  operator visits from rebinding its own hostname to `127.0.0.1`, at which
  point the page is same-origin with the API and can drive it. That mattered
  more than the earlier note here suggested: it described the consequence as
  "import a path, read the waveform back", which was written when the surface
  was read-only. A rebound page can now also `POST /api/renders` — minutes of
  CPU and a ~300 MB file per twenty-minute request, with no rate limit, no
  quota and no `DELETE` endpoint to undo it.

  `server/app.py`'s `_HostAllowList` rejects any request whose `Host` is not
  on the list with a 400, before any route runs. Rebinding needs DNS, so such
  a request always carries the attacker's *hostname*; that header is the one
  thing that distinguishes it from a genuine local request. The list is a
  `create_app(allowed_hosts=...)` parameter defaulting to `localhost`,
  `127.0.0.1`, `::1` and `testserver` — the last being the `Host` FastAPI's
  `TestClient` sends, which was the whole reason this was previously deferred.
  `cli.py` appends the bound host, so `--allow-remote --host 192.168.1.5`
  still answers to itself; a wildcard bind (`0.0.0.0`, `::`, `""`) passes
  `["*"]`, because it cannot enumerate the names it is reachable by, and that
  path is already explicit informed consent.

  It is written here rather than using Starlette's `TrustedHostMiddleware`,
  which was the obvious choice and does not work: that middleware extracts the
  host as `header.split(":")[0]`, which yields `"["` for `[::1]:8765` and `""`
  for a bare `::1`. An IPv6 literal therefore cannot be allow-listed there in
  any spelling, and `sleepmix ui --host ::1` — supported, tested, and opening
  `http://[::1]:8765/` in the browser — would have 400'd every request from
  the operator's own machine. `_host_without_port` handles the bracketed form;
  `tests/test_server_app.py` covers each shape.

  This is host filtering, not authentication. It stops a rebound page; it does
  nothing about anyone who can already reach the port and send a correct
  `Host`. The path allow-list noted above is still the thing that would make a
  non-loopback bind genuinely safe, and still does not exist.

- **`cli.py`'s `ui` command only guards the `uvicorn` import.** The
  `try/except ImportError` around `import uvicorn` does not extend to the
  following `from .server.app import create_app`, which pulls in `fastapi`.
  An install with `uvicorn` present but `fastapi` missing (an unusual but
  possible partial install) shows a raw `ImportError` traceback instead of
  the `pip install "sleepmix[ui]"` hint the guard exists to give.

- **Waveform peaks are computed on the mono downmix.** `peaks.compute_peaks`
  calls `buf.to_mono()` before bucketing min/max pairs, so a transient present
  in only one channel — a hard-panned hit, for instance — is averaged down
  with the other channel rather than shown at full height. The drawn waveform
  is a legitimate summary of loudness but not a faithful per-channel picture.

  It does now clamp non-finite samples (`np.nan_to_num`, immediately after the
  downmix). A float-subtype WAV can legally carry `NaN`/`±Inf`; those survived
  `float()` and pydantic serialized them to JSON `null` on a `-> dict` route,
  which would fail the Elm frontend's `list (list float)` decode and blank the
  whole waveform with nothing logged server-side to explain it. The clamp is in
  `peaks.py` rather than the route so the CLI and Python paths get it too. The
  clamp itself was tested only at the function level until this plan;
  `tests/test_api_songs.py::test_peaks_are_finite_for_a_file_containing_nan`
  now drives a `NaN`/`Inf`-carrying WAV through `GET /api/songs/{id}/peaks`
  end to end.

- **`test_warm_analysis_makes_the_next_loop_search_fast`'s budget is loose.**
  It asserts a post-warm-up `find_loop` call finishes in under 5 seconds. That
  bound is loose enough that it would also pass if `warm_analysis` silently
  did nothing at all — a genuinely cold `librosa.beat.beat_track` on four
  seconds of audio is slow, but not reliably slower than 5 seconds on modern
  hardware. The test currently only proves warm-up doesn't make things worse,
  not that it does what it claims.

- **`ui/hash_sources.py` orders its inputs by sorted path**, so a module
  rename that happened to change the sort order while every file's total
  content stayed byte-identical would not change the recorded hash. Fine for
  what it's used for — noticing that `ui/` changed and `app.js` wasn't
  rebuilt — but it is a drift detector, not a proof that the bundle is
  reproducible from its sources.

- **`Api.elm`'s `stems` decoder combines `Pipeline.optional` with a
  nullable-then-`withDefault` inner decoder.** Correct — a missing or `null`
  `stems` field both end up as `[]` — but redundant: `Pipeline.optional`
  already handles the missing-field case, so the inner `Decode.nullable`
  layered on top only ever does anything for an explicit JSON `null`, and the
  server never sends one.

- **No direct test exercises `SeparationFailed` on the song side.** `Api.elm`'s
  `SeparationFailed` variant of `SeparationStatus` is only exercised
  indirectly, via the job decoder's `Failed` variant on the job-status enum,
  which is a different decoder over a different field.

- **`Main.routeFor` is still only exercised indirectly.** `ui/tests/` now
  covers `Api`'s decoders, `Main`'s job state machine and `update` transitions,
  `Page.Song`'s `needsForce`/`buttonLabel`, `Page.Library`, and
  `Waveform.barFor`. No view is tested — deliberately — and `routeFor`, which
  is one `case` over a `Maybe`, is reached only through them.

**Plan 3f (`feat/legibility`) items, found during this plan's own final task.**
Every entry above this point was checked against the code it describes as
part of this pass; the entries marked closed above were caught up with here —
the `JobManager` eviction leak and the `shutil` import fully, the render-file
resource entry only halfway, since `DELETE /api/renders/{id}` now exists but
automatic pruning, a size cap and a retention policy still do not.
What follows is new — found while making that check, not a correction of an
existing claim.

- **Plan 3e (level-matching) was retired before implementation, and the gap
  in plan numbering between 3d and this one is not a mistake.**
  `docs/superpowers/specs/2026-08-05-level-matching-design.md` records why. It
  was going to fix the fade-ordering entry above by reordering
  `pipeline.py`'s fade-then-normalize steps (`sleepmix/pipeline.py:83-84`:
  `_apply_fades` first, `normalize_peak` second — this sentence said
  "normalize-then-fade", which is backwards, in the entry explaining the plan
  to swap them), on the strength of the same
  attribution this task's own measurement has since shown does not hold. The
  retirement reasoning does not depend on which explanation is right, though,
  which is why it survives that correction: `preview.render_window` "applies
  one gain factor to every window… computed once per `reverb` setting via
  `master_gain` and memoized" (`sleepmix/preview.py:101`), so the ratio
  between a preview at the start of the arc, the middle and the end is exact
  regardless of what the true offset between `master_gain` and
  `normalize_peak` is. A uniform offset cannot change any comparison the mixer
  exists to support — the judgement a preview exists for is "how eroded is
  this by the middle," not "does this match a render's absolute loudness
  played back tomorrow on a different device." One small piece survived into
  this plan instead of the level-matching rewrite: correcting the 1.82 dB
  entry above. A second, giving `output.sample_rate` to `_master_key`
  (Task 5), was reverted by this plan's final review once the memoized gain
  was measured at three output rates and found identical — see item 3 above.

- **The sound bed's absence from previews was a character gap, not a level
  one. CLOSED by Plan 3g.** `render_window` summed only the configured stems
  and never called `soundbed.build_soundbed`, so turning on binaural beats or
  pink noise changed nothing audible in the mixer. Unlike the four
  calibration-window items above, which are inaudible-by-design offsets in
  level, this one changed what the judgement previews exist to support
  actually hears — character, not loudness — which is why it outranked every
  level item on the list and why it was closed while they were not.

  It was handled by disclosure until then, and disclosure got more careful
  rather than less: `sectionNote` carried a line about it until commit
  `e6357cf` deleted the duplicate, leaving `SoundbedConfig`'s own server-sent
  description as the single statement. **That made the docstring the only
  place the claim lived, and Plan 3g's Task 1 caught it going false in the
  same commit that falsified it** — a claim with one home is easier to keep
  true than one with two, but only if somebody looks.

  **What is true now, and is easy to assume otherwise:**
  - The bed is **absent from a soloed preview**, deliberately. A solo already
    does not match the render, which has every enabled stem, and a bed over an
    isolated stem masks the thing it was isolated to hear.
  - The preview's bed is **not the render's bed sample for sample.** Both are
    seeded from `config.seed`, but `run_pipeline`'s generator has advanced by
    the time it reaches the bed. Seeding exists so the memoized `master_gain`
    cannot depend on which random draw occurred, not to reproduce the render's
    noise. Inaudible — noise is noise — and not identical.
  - The bed is **built for the window, not sliced from a full-length one.**
    The noise is stationary and the binaural beat is periodic, so a window's
    worth is perceptually the matching slice; generating twenty minutes to
    take twenty seconds would be absurd.

- **Help lines were siblings of their controls, not attached to them for a
  screen reader. CLOSED by Plan 3g.** `helpLine` rendered `p [ class
  "field-help" ]` as a sibling of the control it explained, with no
  `aria-describedby` pointing at it — a screen reader announced the control
  and its label and said nothing about the help sitting right below it. The
  gap ran one level deeper: every field label was `span [ class
  "field-label" ]`, never `<label for=…>`, so there was no association to
  hang `aria-describedby` off without first giving every control an `id`.

  Plan 3g gave each control `Config.domId target` as its `id`, made every
  label a real `<label for=…>`, and added `aria-describedby` **only where help
  exists** — sixteen fields deliberately carry none, and pointing at an
  element that is not there is worse than pointing at nothing.

  **Two things worth knowing before touching this again:**
  - **`Config.keyOf` is not usable as a DOM id** and `domId` exists because of
    it. `keyOf` returns the bare field name, since that is what indexes the
    per-section dictionaries — so every stem's `enabled` would collide with
    every other stem's, and with `stem_decay`'s. An id that collides points
    two controls at one label, which is worse for a screen reader than no
    label.
  - **`elm-test` cannot check HTML validity**, only attributes, tags and
    classes. Applying the label change uniformly produced a `<label>` nested
    inside the checkbox's existing wrapping `<label>` — forbidden by the
    content model, undefined behaviour across screen readers, and on the
    control (`Enabled`, on every stem) a user meets most often. The suite was
    green throughout. `ui/tests/MixerTest.elm` now carries a shape guard —
    *no `label` wraps another label* — which is the only reason the next
    occurrence would be caught.

- **The top-level description's missing-key fallback has no test.**
  `ui/tests/SchemaTest.elm`'s `"a section without a description decodes to
  \"\" rather than failing"` test, added alongside the schema's description
  decoding earlier in this plan, exercises `decodeSection` only — the
  section-level decoder. Nothing decodes a top-level `/api/schema` response
  with no `"description"` key at all and asserts `schema.description == ""`;
  `Page.Mixer`'s own `sectionDescription` tests (`ui/tests/MixerTest.elm`)
  construct the `Schema.Schema` value directly with `description = ""` rather
  than decoding JSON that omits the key, so they exercise the fallback's
  *use*, not its *decode*. Same pattern, same low risk as the section-level
  version it sits beside — recorded so the asymmetry isn't mistaken for the
  top-level case being untested by design.

**What Plan 3f's final whole-branch review changed.** Seven fixes, none of
them a feature. Two of them were the branch undermining its own purpose, and
both had the same shape: *the work was verified by reading it rather than by
rendering or measuring it.*

1. **The branch's own deliverable was illegible during the one window a
   newcomer is guaranteed to read it.** Task 4 retargeted the inert-panel
   opacity rule from `.field:has(:disabled)` to `.field-group:has(:disabled)`,
   which pulled the new help text inside the dimmed scope for the first time —
   under the old rule help was an `Attr.title` and there was nothing to dim.
   `.field-help` is already `--dim` (`#8b8f98`); at `opacity: .45` over
   `--bg` (`#17181b`) that composites to about `#4b4e53`, **2.12:1** against
   5.48:1 undimmed. `rem` resolves against the root element, not against
   `body`'s 15px, so `.85rem` is 13.6px — normal-size text, well under the
   24px WCAG counts as large, so the bar is AA's 4.5:1, not the 3:1.
   And `Wiring.enabled` is `Preview.isPlayable`,
   false in `Cold` and `Warming`, so the whole settings panel is inert until
   the first preview returns — minutes for a cold song. Reverted to `.field`.
   The Task 4 comment's stated worry about compounding did not apply:
   `.field-help` is a **sibling** of `.field`, not a descendant.
2. **Task 5 was a measured no-op that marked a real gap closed.** Reverted,
   with the measurement recorded in `_master_key`'s docstring and in item 3 of
   the calibration-window list above. The same measurement also cleared the
   three *other* `_master_key` omissions the Task 5 ledger note had recorded
   as a second bug — they are not one.
3. **The Mix section said the seed's purpose twice, three lines apart.**
   `MixConfig.__doc__` explained the seed and so did the seed's own `help`,
   and Mix renders exactly one control — 100% of the section restating 100%
   of itself. Third instance of a shape Task 4 already found and fixed twice.
   The description names the control; the control explains itself.
4. **The mechanism paragraph of the entry Task 6 exists to get right was
   false**, and four smaller figures in the same entry were wrong. The fix
   wave's own first attempt at this then got the post-fade half wrong as well
   — it measured against a stand-in song of the wrong length, reproduced the
   *pre*-fade peak exactly, and took that as confirmation — and claimed the
   peak comparison corroborated the RMS one independently when the two are
   algebraically the same quantity. Both were caught in re-review and are
   corrected
   above, by direct measurement rather than by re-reasoning.
5. **Two doc statements reversed or overstated what they described** — a
   "normalize-then-fade" that is fade-then-normalize in the source, and three
   summary sentences calling the renders resource entry closed when the entry
   itself correctly says half.
6. **The two suites disagreed about which fields carry help.**
   `ui/tests/Fixtures.elm` gave `loop.bars` and `loop.beats_per_bar`
   `"help": null` while `tests/test_config.py`'s `NEEDS_HELP` requires both
   to carry one, so two Elm tests asserted the opposite of production — one of
   them anchored on `Beats per bar` as an *example* of a field with nothing to
   say. Five more fields diverged the same way. The fixture header now states
   the rule: shortening the text is fine, changing whether there is text is
   not. That test was also vacuous — deleting help rendering from the view
   left it green — and now asserts both halves, proven by mutation in both
   directions.
7. **The decay panel, which the plan calls the heart of the tool, read as
   three documents.** Three problems in one place, all created by prose
   meeting a key-sorted grid:
   - *"Requires headphones" four times running.* `Dict.toList` is key-sorted,
     so Soundbed renders `binaural_beat_hz`, `binaural_carrier_hz`,
     `binaural_enabled`, `binaural_gain_db` adjacent — and each of the four
     help lines this branch added ended in the same two words, with the
     *reason* arriving third. Said once now, in `SoundbedConfig`'s
     description, which is read before any of the four; `binaural_enabled`
     drops its help entirely, since the description now carries what it said.
   - *Every decay pair renders end-before-start* — `amp_end_db` sorts before
     `amp_start_db`, and likewise for dropout, lowpass, noise and spectral
     hole — while `StemDecayConfig`'s description narrated five things "in
     this order," an order the alphabetical grid does not show. The ordering
     is pre-existing and **nothing in the audio path moved**; the prose was
     reconciled to the screen instead, and now says outright that the five-step
     order is the processing order, that the panel is alphabetical, and that
     this is why each pair's end sits above its start.
   - *The description's deictics pointed at nothing.* `stemsPanel` renders it
     above the stem rows, but the values live behind a **closed**
     `<details class="decay">` inside each row — so "Every value here has a
     start and an end" and "Curve decides how that move is paced" were read
     where there is no value and no Curve control. It was also a second
     `.section-description` directly under the `stem` one with no heading
     between them and nearly equal gaps, so the two read as one five-paragraph
     essay whose second half opened on a headless fragment.
     **Chosen: head it, and rewrite the deictics.** An `h4` reading `Decay`
     now sits between the two descriptions — the same word as the `summary`
     of the disclosure it describes, which is what turns the paragraph from a
     continuation into a caption for something further down the page — and the
     description points at "a stem's Decay panel" rather than at "here".
     Moving it inside the disclosure was rejected because it would then repeat
     once per stem, which is the reason it lives above the rows at all;
     splitting it was rejected because the two halves are one thought. The
     heading is asserted by a view test and verified by deletion.

## Plan 9 (Esoterica DM Radio), segments and station bundles

`sleepmix esoterica bundle <id>... --out <dir>` (free) cuts each passage's raw
take into segments at pause midpoints and writes `<dir>/<id>/sNN.wav` (22050 Hz
mono PCM_16, numbered across the recording) plus `station.json`. Code:
`sleepmix/esoterica/segments.py`. Refuses stale takes. Flags segments under
20 s or over 150 s but still exports them. `make stations` bundles the three
launch stations; output `ios/Esoterica/Stations/` is gitignored.

**Placeholders (tune by ear):** `CUT_MIN_PAUSE_S` 0.25 s, `CUT_WINDOW` +-20% of
the take, `CUT_DISTANCE_PENALTY` 0.02 (`segments.py`); `BUNDLE_MIN_S` 20 and
`BUNDLE_MAX_S` 150 (`cli.py`). Cuts are a pause midpoint nearest where the
paragraph-character share predicts the `[segment]` marker falls; if no pause
is left after the previous cut, a segment is silently not cut (fewer segments).

### Plan 9 Task 7: a station's sound (`NightRadio`)

New Swift library target `NightRadio` (deps `NightDSP`, `NightPlan`; Foundation only,
no AVFoundation, guarded by `nightRadioImportsNoAVFoundation`). Code in
`swift/Sources/NightRadio/`:

- `StationBundle` reads `station.json` (id, title, segment seconds, segment URLs).
  Segment files are not opened here.
- `StationChain`: warmth/chimes/waves × recipe gain × bed gain → `Fragmenter` →
  `Distance` (all on `Curve { Drift.bedWarp(clock.level(at:)) }`), plus
  `StationVoice`, → `AMChannel(Curve { Drift.channel(...) })` → `masterGuard`.
  Engine seconds from 0 (cold start, no lead-in; the on-fade in Task 8 covers settling).
  Curves call `DriftClock.level(at:)` directly: no per-block snapshot was needed
  (processors read it at most once per 512 frames, scenes per event).
- `StationVoice`: plays the program's segment via `FileSource`. A segment whose start
  falls inside the block starts from clip time 0 at its exact frame. A segment the
  program reveals late (it reveals on a whole-second grid but backdates `start` to
  `end + gap`, so up to ~1 s late whenever the gap isn't whole seconds) plays from
  clip time 0 at the reveal frame, never seeked; the speech runs up to ~1 s behind
  the schedule (absorbed by the next gap, >= 3 s). Only the switch-on segment (already
  under way at engine second 0) is seeked, with a 30 ms raised-cosine fade-in. A
  clip still sounding when the next segment starts fades out over 50 ms;
  per-block linear ramp to `Drift.voiceGainDB`; own `Distance` on
  `WarpDepth(distance: Drift.voiceDistance)`. Preloads the next clip when
  `upcoming` is under 5 s away; holds at most current + next. A nil load is
  silence; the schedule carries on.
- `StaticChain`: `AMChannel` over zeros with the static settings, × per-block
  ramp to `Drift.staticGainDB`, then `masterGuard`.
- Seeds: `NightRandom.hash(seed, stationIndex, k)` with stationIndex = index in
  `StationRecipe.all` (static = 3), k: warmth 0, chimes 1, waves 2, fragmenter 3,
  bed distance 4, channel 5, program 6, voice distance 7.

**Placeholders (tune by ear):** `StationChain.bedGainDB` −8 dB;
`StaticChain.settings` (low 300, high 3000, hiss −30, crackle −36, fadeDepth 0.4,
fadeRate 0.08, squash 0.3); `StationVoice.preloadSeconds` 5 s;
`StationVoice.fadeInSeconds` 0.03 (switch-on seek); `StationVoice.fadeOutSeconds` 0.05
(overrunning clip replaced).

**Measured:** release build on the Mac, three StationChains + StaticChain, 60 s at
44.1 kHz in 2048-frame blocks: 1.41 s wall-clock, **about 42× real time** (after the fix round; 40× before)
(`swift test -c release --filter rendersFastEnough`; needs ≥ 10×). Test temp
bundle (300 Hz tone at −24 dBFS RMS): voice 11.8 dB above the Lantern bed over
speech at drift 0; static RMS −35.8 dBFS at drift 0.
