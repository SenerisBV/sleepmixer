# Plan 8: Esoterica — a collection of found recordings that prime the mind for dreams

**Status:** design approved by the operator 2026-11-03 ("Everything else is good", with the no-intros rule added). Not yet planned.

**Amends** `2026-11-02-am-night-design.md` (Plan 7), section "Voices". That
section's voice layer, which plays spoken word from pasted links (podcast
feeds, audiobooks, the public-domain starter list), is **demoted to a later
option**. Its slot in the engine and its treatment stages stay; its link
importing, feed handling and starter list are not built now. Everything else
in Plan 7 stands.

## What this is, and where it came from

After hearing the soft-mallet chimes and low warmth ("this is sounding great …
this is great and soothing"), the operator brought a new idea for the voice:

> Godspeed You Black Emperor's *Lift Your Skinny Fists Like Antennas to
> Heaven*, the track *Storm*, contains a long low-quality excerpt of someone
> talking about an ecstatic religious experience they had, going through
> corridors and being in the presence of god. I've never learned where it came
> from, but I had this thought that the mood of that coupled with the low
> quality and the feeling of a found fragment — that we could generate
> recordings like that ourselves that are strange, esoteric, describing some
> alluring experience or unusual topic, full of passion, comes at things
> sideways, spiritual, etc. — and make that the voice library. The app could
> even be framed as a collection of these recordings, esoterica or something,
> and that's what both sparks intrigue and actually works.

They named the shapes it could take: commentating a made-up sport ("Northwoods
Sleep Baseball"), "famous speeches from alternate worlds", "1010 WINS but
alien or the spirit realm", "Pimsleur lessons but a made up language", "just
these different kinds of long-form generated spoken word experiments that
prime the brain for dreams." "I think that might be the direction I want to
go in."

**What makes the *Storm* recording work, in their words**, which is the
brief for every testimony and the north star for every other show:

> The person sounds like this is the most important thing that has ever
> happened to them, that they want everyone to know this, that their
> experience of ecstasy sounds plausible and even relatable, that it's
> familiar but unrecognizable and I don't know what kind of church or setting
> this person is speaking to or about, or when they were recorded — yesterday?
> 50 years ago? — or whether what they're describing is sinister or sublime,
> that they describe a strange journey in details.

**The ambiguity is human, not horror.** Asked whether a hint of the sinister
belongs at bedtime:

> I think anytime anyone speaks of something that intensely about an inner
> experience they had, I wonder if they're ok. In this case, was she in a
> cult? Or was she able to connect to something vital.

**The spirit it reaches for**, also theirs: "That recording, Alan Watts, that
whole vibe of the mid 20th century — existentialism and Sartre, the Beats,
spiritual jazz — felt like it was probing new approaches of spirituality that
pinned certain aspects as intensely serious even as it played with others.
Those intensely spiritual experiences I feel aren't sought out in the same way
now … (*Letters to Wendy's* is the last thing I can remember that felt that
way), or that part of life isn't treated as seriously and essentially as
something that needed reclaiming and reexploration … I think whatever toys
with that while also taking it seriously works."

So the collection is partly a **reclaiming**: inner experience treated as
serious and essential, approached with play but never with irony.

**Also from the operator, in the same conversation:**
- They have been falling asleep to French meditations: "add that to the list,
  but also maybe the meditations go in weird directions."
- From a past Yoga Nidra experience: "the rapid succession of phrases of
  different sensory experiences — bright yellow, warm rain, sour apple — that
  made my mind feel like it was being worked to exhaustion. That was really
  great and I've never found it again. Little 'scenes' like this are nice to
  mix in." (Claude's naming: Yoga Nidra's rapid-visualisation stage, and the
  sleep technique called *cognitive shuffling* or *serial diverse imagining*:
  a stream of unrelated concrete images that occupies the mind without
  letting it build a story or a worry.)
- On endings: "Murmur is good — that track dissolved into static at a certain
  point. Any way to end it is fine but it should probably trail off rather
  than conclude."
- On shape: "recordings may be long but we can break them up a bit, have long
  pauses or intermissions and then they come back later, and overall are just
  a component that can be altered within the whole experience."
- On links: "I lean towards replacing it. I do feel like it would be nice to
  be able to customize what you sleep to — maybe this is how you catch up on
  a comforting podcast and fall asleep to it. Can we focus on the esoterica
  but not shut the door on importing a link later, even if the experience is
  not quite as tuned for it?"
- On growth: "Let's do a starter set of all the ideas and then grow it out as
  we evaluate them."
- On the mix: "when we add the voice audio, the chimes need to be quieter."
- On voices: "if the voices can change their tone to speak intimately rather
  than like a customer service person, then I'm open to being surprised on
  both counts" (script and voice choices are Claude's).
- They hold ElevenLabs and Cartesia credits, with keys in the repo's `.env`
  (git-ignored). They noted that ElevenLabs promotes its v4 model as its most
  emotive.

## Goals

1. **A starter collection of esoterica**: one or two recordings for each of
   the seven shows below, written, voiced and treated, so each idea can be
   judged by ear.
2. **Recordings are components, not tracks.** Each is written in passages the
   night can place, pause, return to, thin out and warp, like the scenes.
3. **Intimate delivery.** Every voice sounds like a person talking close to
   you about something that matters to them.
4. **A repeatable production path**: script → voice → source character → a
   manifest the engine reads, so growing the collection later is running a
   tool, not rebuilding anything.
5. **Hear it through the engine**: `nightctl` can audition any passage through
   the existing distance, fragmentation and AM channel, so the
   found-recording treatment is judged together with the voice.

## Non-goals (for this plan)

- **Importing links** (podcasts, files). The door stays open: the engine's
  voice slot takes passages from a manifest, and a later importer can write
  that same manifest for any audio. Nothing link-specific is built now.
- **Automatic daily growth.** Growth is on request for now. Automating it
  later needs an Anthropic API key, which isn't in `.env` yet.
- **The night planner's placement of passages** across a whole night. This
  plan defines what a recording is and how one sounds; *when* passages play
  is the planner milestone's job (with the mix note that chimes sit quieter
  under a voice).
- **The iPhone app.** Files are produced on the Mac; getting them to the phone
  is the app milestone.
- **The late-night DJ / call-in show.** Still the operator's to design. The
  strange-stations show is a neighbour of it, not it.

## Anti-goals: it fails if…

- **A voice sounds like customer service**, an audiobook narrator, or an
  ad read: bright, projected, smiling, evenly paced. The target is close,
  unhurried, a little unguarded, with real breath and pauses.
- **It's ironic.** The collection toys with spirituality but never sneers at
  it. No speaker is a punchline; no script winks at the listener.
- **It's frightening.** The "is this person OK?" flicker is allowed and
  wanted. Horror, violence, menace, distress, self-harm, and anything that
  could wake someone are not.
- **It introduces itself.** On approval the operator said: "we don't need
  intros or table-setting, just go into it." No recording opens with a title,
  a welcome, a framing narrator, or scene-setting ("this recording was found
  in…"). Every recording starts *in medias res*, mid-thought or even
  mid-sentence, and its first passage is written that way. The source-character
  treatment is sound only, and nothing about it is ever spoken.
- **It concludes.** No recording wraps up, summarises or signs off. The last
  passage trails off mid-thought.
- **It impersonates a real person.** No real person's voice is cloned, and no
  real, named person (living or dead) is depicted saying things they didn't
  say. Alternate-world speeches are by invented figures from invented
  histories. Shows may be *in the manner of* a format (Pimsleur-style,
  news-radio-style) but never use a real brand's name or identity in the
  audio.
- **It demands attention late at night.** Content is written so that it is
  followable early and loses nothing by being half-heard; the warping does
  the rest (Plan 7's voice stages: clear → on the radio → next room →
  fragments → the shape of a voice).
- **Two nights sound the same.** Passages are mixed, reordered and warped by
  the night; the collection grows.

## The shows (the starter set)

Every show shares the collection's voice: sincere, specific, sideways,
mid-century in spirit without being dated to a year, familiar but
unrecognisable. Lengths are placeholders.

| Show | What it is | Shape | Language |
|---|---|---|---|
| **Testimonies** | Someone recounts a strange inner journey (corridors, thresholds, a presence) as the most important thing that has ever happened to them. You can't tell if they're OK. | 4–6 passages of 2–5 min | English |
| **Sideline** (sport commentary) | Play-by-play and colour commentary of a made-up sport whose rules are never fully explained, as if to a regional audience that knows them. Gentle, patient, full of small reverent details. | 4–6 passages | English |
| **Addresses** (alternate-world speeches) | Speeches by invented figures at invented occasions in histories that didn't happen: a dedication, a farewell, a call to something. Grand in cadence, strange in content. | 3–5 passages | English |
| **Strange stations** | A news-radio format (headlines, weather, traffic, time checks) from somewhere else: an alien city, the spirit realm. Calm, routine, impossible. | many short segments | English |
| **Lessons** | A call-and-response language course for an invented language: phrases, repetition, pauses for the listener, a gently widening world glimpsed through the example sentences. *Amended at STOP 1 (2026-11-03), see below.* | 4–6 passages | English + invented |
| **Méditations** | French guided meditations that begin conventionally and drift somewhere unexpected. | 3–5 passages | French |
| **Shuffles** | Bursts of rapid, unrelated, concrete sensory images ("bright yellow … warm rain … sour apple"), one every 2–3 s, 20–40 per burst. Mixed between the longer pieces like the scenes are. | many 1–2 min bursts | English (a few French) |

**Writing them** (*Claude's call*): Claude writes the starter scripts in this
session, as plain text files in the repo, so the operator can read and react
before anything is voiced. Each script carries:

- **Light delivery cues where the provider supports them**, such as pauses,
  breaths, a whisper or a laugh. These are used sparingly.
- **Passage breaks.**
- **A note on the speaker**: who they are, their age, how close the
  microphone is, what kind of room they're in. The speaker stays invented and
  is never named after a real person.

## How a recording is made

1. **Script**: `esoterica/scripts/<show>/<recording-id>.md`. Front matter
   holds the show, title, language, speaker note, and voice choice, with
   passages separated by a marker.
2. **Voice**: a tool sends each passage to ElevenLabs or Cartesia and writes
   one WAV per passage. Provider, model and voice are per recording, from the
   script's front matter.
3. **Source character**: a light, per-recording "where was this found"
   treatment baked into the file, such as tape wear, a particular room, a
   narrow old microphone, or a faint hum. This makes recordings differ from
   each other before the engine's shared AM channel and warping get to them.
   It stays subtle, because the engine does the heavy lifting.
4. **Manifest**: `esoterica/library/<recording-id>/recording.json`. It holds:
   - a format version, the id, show, title and language;
   - the source-character recipe;
   - for each passage, its file, duration, text and an *intensity* tag (how
     attention-holding it is), which the planner can use to keep demanding
     passages early;
   - the provider, model and voice;
   - the date it was made.

   The audio files live next to it. The engine's voice slot reads this
   manifest, and a future link importer would write the same manifest.

**Where the audio lives** (*Claude's call*):
- Generated WAVs are large binary files. They go in the repo's git-ignored
  `esoterica/library/`; only scripts and manifests are committed.
- Manifests are small, but they point at audio, so commit them only if the
  audio can be regenerated from the script. With TTS it can't be reproduced
  exactly, so the builder decides whether manifests are committed. This is
  recorded under "Left to the builder".

**Tooling** (*Claude's call*): Python, in the existing `sleepmix` package, as
a new `sleepmix esoterica` CLI group with `voice`, `audition` and `treat`.
Python because the repo already has the CLI, pipenv and HTTP libraries
(`requests`/`httpx`), and these are offline batch jobs, not playback. Keys
are read from `.env`, and nothing ever logs or prints a key.

## The voices: intimate, not customer service

- **Audition first, then commit** (*Claude's call; the operator opted into
  being surprised*):
  - For each show, voice one short excerpt, about 45–60 s (*Claude's call after the builder check*, to keep the audition cheap), with 2–3 candidate voices
    on each provider. That includes ElevenLabs' newest, most expressive model
    (the operator flagged v4) and Cartesia's most expressive model, using
    each provider's emotion and delivery controls.
  - Claude picks per show by measurable proxies plus the scripts' intent.
    The operator still hears the full audition set and can overrule.
  - The builder checks each provider's *current* documentation for models,
    expressive controls, French support and pricing at build time, rather
    than trusting this document's knowledge.
- **The intimacy recipe**, applied through whatever controls each provider
  offers:
  - lower energy and slower pace than the default;
  - close-mic, conversational delivery;
  - permission to pause, breathe and trail off;
  - higher expressiveness or variability where the model allows it, rather
    than maximum stability;
  - voices chosen for warmth and age over polish.
- **No cloning of real people.** Use provider library voices or designed
  voices only.
- **Cost guard.** Before any bulk voicing run, the tool prints the character
  count and estimated cost per provider, and proceeds only when told to.

## In the engine (minimum for this plan)

A passage auditions through the same chain as the scenes:

```
nightctl audition voice --file <passage.wav> [--distance … --fragmentation …]
```

That is, a file source, then Fragmenter, then Distance, then the AM channel,
then the guard, through the one factory. That is enough to judge "found
recording plus our channel" by ear.

**Not in this plan:**
- slowness for voices (*Claude's call, settled after the builder check*): the `voice` audition takes no `--slowness` and rejects it with a clear message, because a file source has no generator to slow. Varispeed ("slower, slightly lower") is a planner-milestone voice stage;
- the five voice stages over a night;
- the memory replay of earlier passages.

All three belong to the planner milestone. Plan 7's voice requirements
(loudness matching and a slow limiter on the voice path) apply when voices
are mixed into a night. The tool also normalises every passage to a common
loudness when it writes the file, so auditions compare fairly.

## Budget and the two stops (the operator's answers after the builder check)

- **ElevenLabs:** the operator holds 265k credits and is fine with the
  starter set spending from them ("that would be fine"). Cartesia's balance
  wasn't stated, so it is used only for the audition comparison unless it
  wins a show, in which case its spend is reported first.
- **Stop 1, after the scripts.** The operator reads them before anything is
  voiced.
- **Stop 2, after the audition.** "Let's do the audition first." The audition
  runs (short excerpts, both providers), the operator hears it, and only then
  does the bulk voicing of the starter set run. Bulk voicing stays inside the
  ElevenLabs credits, and the cost guard prints the estimate before it
  spends.

## Placeholders (to be tuned, recorded in project-state when built)

- Passages per recording (3–6) and passage length (2–5 min)
- Shuffle bursts: 20–40 images, 2–3 s apart, bursts of 1–2 min
- Starter set size: one or two recordings per show
- Target loudness for passages
- Source-character recipes and their strength
- Candidate voices per show (2–3 per provider)

## Left to the builder

- **API details.** Exact provider endpoints, model names and delivery
  controls, verified against current docs.
- **Formats.**
  - The script file format details, and the manifest schema details beyond
    the fields named above.
  - WAV sample rate and bit depth (match the engine: 44.1 or 48 kHz mono).
- **Storage.** Whether manifests are committed, and where the git-ignored
  library lives if not at `esoterica/library/`.
- **Source character.** How it's implemented. Reusing the existing Python
  `effects`/`disintegration` code is welcome.
- **The Swift file source.** Its WAV decoding, using Foundation only, to stay
  iOS-portable.

## Order of work (suggested)

1. **Scripts.** Claude writes the starter set (all seven shows) and the
   operator reads them.
2. **Voicing tool and audition.** Build `sleepmix esoterica voice` and its
   cost guard, run the audition, and pick voices.
3. **Voice the starter set**, with source character and manifests.
4. **Engine file source** and `nightctl audition voice`.
5. **Listening set and docs**, with the operator listening.

## Amendment at STOP 1 (2026-11-03): lessons are not a real-sounding language

The first lesson, *Aurish*, had a consistent invented grammar (*Vela en lume*). The operator read it and said it "feels too much like a romantic language, which is going to be distracting". A language that sounds learnable invites the half-asleep mind to try to learn it. The operator offered three directions:

1. **One repeated nonsense word,** in the spirit of the Hamburglar's "robble robble" but not a clone of it. Spoken clinically, "this would actually be soothing".
2. **An animal:** birds, whales, or "a non-specific animal that just growls, roars, and makes other guttural inarticulate noises" (not a dog or cat).
3. **The same sentence with the letters reversed.**

**Taken (Claude's call):** 1 and 3, written as two lessons so the audition can compare them:

- `lessons/backward-lesson-one.md`: whole-sentence letter reversal ("Retaw eht no si noom eht"). It is never explained, and the vocabulary was chosen so the reversals stay pronounceable.
- `lessons/mubba-lesson-one.md`: a whole language built from *mubba* and *mub*. The teacher calmly insists on distinctions no one can hear.

Both are taught clinically: the teacher is never amused and never checks on you. *Aurish* was removed; it remains in git history.

**Parked:** the animal lesson. A voice model can't growl or sing a whale call convincingly. It would need ElevenLabs' sound-effects generation (a different endpoint), with the teacher's line followed by a generated call. That is a pipeline change, so it is recorded in `docs/project-state.md` as a later door.

**Also added at STOP 1:** the operator added a `voice_profile` front-matter field to each script, a few words describing the voice as they imagined it. STOP 2 picks voices against it.

**Who speaks (operator, STOP 1).** A show with a recurring host keeps one voice: "we should keep one voice for the language" (one teacher across all lessons), and the same holds for the commentator, newsreader, meditation guide and shuffler. But "testimonies should actually change and not be the same person repeated": every testimony is a different person with a different voice. *Claude's call:* addresses get the same treatment, since each is a different invented figure. As the library grows, the voice pool for testimonies has to grow with it, so that no two testimonies share a voice.
