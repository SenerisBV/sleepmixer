# Plan 8a: the Esoterica starter set — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A starter collection of generated "found recordings" across seven shows (written, auditioned, voiced, given a source character and described by manifests) that the operator can hear raw and through the Swift engine's channel.

**Architecture:**
- **Scripts:** plain-text files under `esoterica/scripts/`, written by Claude.
- **Production tooling:** a new Python subpackage `sleepmix/esoterica/` with a `sleepmix esoterica` click group. It parses scripts, estimates cost, voices passages through ElevenLabs or Cartesia behind one provider interface, applies source character and loudness, and writes manifests. Audio lands in the git-ignored `esoterica/library/` and `esoterica/audition/`.
- **Playback:** the Swift engine gains a file source and `nightctl audition voice --file`, built through the one factory.

**Tech Stack:** Python 3 (repo's pipenv), click, pyyaml, requests, numpy/scipy/soundfile/pedalboard (all already deps), pytest. Swift 6.4 package at `swift/` (from Plans 7a/7b). ElevenLabs and Cartesia HTTP APIs.

**Spec:** `docs/superpowers/specs/2026-11-02-esoterica-design.md` (approved 2026-11-03). It amends `docs/superpowers/specs/2026-11-02-am-night-design.md` ("Voices").

## Two operator stops: the controller MUST pause at each

- **STOP 1 — after Task 1.** The operator reads the scripts. The controller reports their paths and waits for the operator's go. Edits the operator asks for are made before continuing.
- **STOP 2 — after Task 3's audition run.** The operator hears the audition. The controller reports the audition paths and Claude's per-show voice picks, then waits. Bulk voicing (Task 4) spends only after the operator's go.

These are spending and creative gates the operator asked for ("Let's do the audition first"). They are not optional.

## Global Constraints

**Content** (spec anti-goals):
- intimate delivery, never "customer service";
- never ironic about spirituality;
- never frightening (the "is this person OK?" flicker is allowed; horror, violence, menace, distress and self-harm are not);
- never concludes (the last passage trails off mid-thought);
- never introduces itself ("we don't need intros or table-setting, just go into it"): every recording starts *in medias res*;
- no real, named people depicted;
- no cloned voices;
- no real brand names in the audio.

**Secrets:**
- API keys come only from the repo-root `.env` (git-ignored; keys `ELEVENLABS_API_KEY`, `CARTESIA_API_KEY`) or from the environment.
- No code path prints, logs, writes or includes a key in an exception message.

**Tests never touch the network and never spend credits.**
- Provider clients take an injected HTTP session.
- An autouse fixture in `tests/esoterica/conftest.py` makes any real `requests` call raise.
- Tests write only under `tmp_path`, never into `esoterica/library/` or `esoterica/audition/`.

**Cost guard:**
- Every command that calls a voicing API first prints the character count and estimated cost per provider.
- It spends only with `--yes`.
- It never re-voices a passage whose audio already exists (resumable; don't pay twice).

**Budget:** ElevenLabs bulk voicing stays within the operator's 265k credits. Cartesia is audition-only unless it wins a show, in which case report its estimated spend at STOP 2.

**Audio contract:**
- Passages are written as mono float32 WAV at 44100 Hz.
- Loudness is normalised to −24 dBFS RMS over speech-active frames (frames above −50 dBFS), with peaks limited to −3 dBFS (placeholders).

**Builder checks live docs:** provider endpoints, model names (including ElevenLabs "v4", which the operator flagged as its most emotive), delivery/emotion controls, French support and pricing come from each provider's *current* documentation, read at build time. Record what was found in the task report.

**Swift:**
- Plans 7a/7b's constraints hold: NightPlan stays pure; NightDSP uses Foundation only; one factory; tests run with `swift test -c release`.
- `nightctl audition voice` takes no `--slowness` and rejects it with a clear "must be 0 for voice" style message.

**Docs:** every invented number is recorded in `docs/project-state.md` (user CLAUDE.md rule).

## Review Focus

1. **A provider error part-way through a run** (HTTP 429/500, a timeout): files already written stay, no manifest is written for an incomplete recording, and a rerun skips what exists. Test in Task 3.
2. **A passage longer than a provider's per-request limit:** it splits at sentence boundaries and joins seamlessly, with no click and a short silence. Test in Task 3.
3. **A key leaking in an error:** a provider error raised while the client holds a key must produce a message with no key text. Test in Task 3.
4. **A malformed script** (missing front matter, unknown show, unknown cue, empty passage): a clear error naming the file and line, before any spend. Test in Task 2.
5. **A voice WAV the engine didn't make** (stereo, int16, 48 kHz, shorter than `--seconds`): it is decoded or resampled, or rejected with a clear message. A short file ends in a fade to silence, never a click. Test in Task 5.

---

### Task 1: The starter scripts → STOP 1

**Files:**
- Create: `esoterica/README.md` (the format, below)
- Create: `esoterica/scripts/<show>/<recording-id>.md` (8 files, below)
- Modify: `.gitignore` (add `esoterica/library/` and `esoterica/audition/`)

**Interfaces:**
- Produces: the **script format**, consumed by Task 2's parser.
  - **Front matter:** a YAML block between `---` lines, with these keys:
    - `id` (kebab-case, matches the filename);
    - `show` (one of `testimonies`, `sideline`, `addresses`, `stations`, `lessons`, `meditations`, `shuffles`);
    - `title` (internal only, never spoken);
    - `language` (`en`, `fr`, or `en+invented`);
    - `speaker` (a prose note: age, manner, how close the microphone is, the room; invented, never a real person);
    - `source_character` (one of `tape`, `room`, `oldmic`, `hum`, `clean`);
    - `voice` (left empty until STOP 2).
  - **Passages:** separated by a line containing exactly `[passage]`. Each passage may start with an HTML comment `<!-- intensity: low|medium|high -->` (default `medium`).
  - **Neutral delivery cues,** inline, the only allowed set: `[pause]`, `[long pause]`, `[breath]`, `[softly]`, `[whisper]`, `[laughs quietly]`. Task 3's adapters translate or strip them per provider.
  - **Shuffles:** each passage is one burst, with one image per line and no cues.

**The starter set:**

| File | Recording | Passages | Approx. words |
|---|---|---|---|
| `testimonies/the-corridors.md` | A testimony: a journey through corridors to a presence. This is the *Storm* north star. | 5 | 2400 |
| `testimonies/the-orchard-light.md` | A second testimony, different in setting and speaker | 4 | 1800 |
| `sideline/northern-tide-final.md` | Commentary on an invented sport | 5 | 2400 |
| `addresses/the-lantern-accords.md` | An address by an invented figure in an invented history | 4 | 1800 |
| `stations/wbx-the-far-shore.md` | A news-radio hour from somewhere else (headlines, weather, traffic, time checks) | 6 short | 2000 |
| `lessons/aurish-lesson-one.md` | A call-and-response lesson in an invented language, with consistent grammar and vocabulary | 5 | 2000 |
| `meditations/la-maison-sous-la-mer.md` | A French guided meditation that drifts somewhere strange | 4 | 1600 |
| `shuffles/shuffles-one.md` | Bursts of 20–40 concrete sensory images each, a few in French | 8 bursts | 1200 |

Titles and ids are suggestions; the writer may rename them.

Total: about 15k words, roughly 90k characters, within budget.

- [ ] **Step 1: Read the spec's whole "What this is" section and the shows table.** That section is the brief, especially the *Storm* paragraph and the mid-century-spirituality paragraph.
- [ ] **Step 2: Write `esoterica/README.md`.** It holds the format above, the cue set, the show list and the content rules, copied from Global Constraints.
- [ ] **Step 3: Write the eight scripts.** For each one:
  - The first words are mid-thought.
  - The last passage trails off.
  - The speaker is specific, sincere and sideways.
  - Intensity runs `high` or `medium` in early passages and `low` later, so they're followable early and lose nothing half-heard late.
  - Passage lengths are about 2–5 minutes at roughly 120 words per minute. Bursts are about 1–2 minutes.
- [ ] **Step 4: Self-check every script against the content rules.** Confirm:
  - nothing opens with framing;
  - nothing concludes;
  - no real names or brands;
  - nothing frightening.

  Record the check in the report.
- [ ] **Step 5: Commit** `feat(esoterica): starter scripts for seven shows`.
- [ ] **Step 6: STOP 1.** The controller gives the operator the eight paths and waits.

---

### Task 2: Script parsing, the manifest model and cost estimates

**Files:**
- Create: `sleepmix/esoterica/__init__.py`, `sleepmix/esoterica/script.py`, `sleepmix/esoterica/manifest.py`, `sleepmix/esoterica/cost.py`, `sleepmix/esoterica/env.py`
- Create: `tests/esoterica/__init__.py`, `tests/esoterica/conftest.py`, `tests/esoterica/test_script.py`, `tests/esoterica/test_manifest.py`, `tests/esoterica/test_cost.py`, `tests/esoterica/test_env.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Passage: index: int; text: str; intensity: str  # "low"|"medium"|"high"`
  - `@dataclass(frozen=True) class Script: id: str; show: str; title: str; language: str; speaker: str; source_character: str; voice: dict | None; passages: tuple[Passage, ...]; path: Path`
  - `class ScriptError(ValueError)`. Its message always names the file, and the line where one applies.
  - `def load_script(path: Path) -> Script`
  - `def load_all(root: Path) -> list[Script]`
  - `SHOWS: frozenset[str]`, `CUES: frozenset[str]`, `SOURCE_CHARACTERS: frozenset[str]`
  - `def spoken_text(p: Passage) -> str` returns the text with cues and comments removed. Use it for character counts.
  - `@dataclass class PassageEntry: index: int; file: str; duration_s: float; text: str; intensity: str`
  - `@dataclass class Manifest: format_version: int = 1; id; show; title; language; source_character; provider; model; voice_id; made_at: str; passages: list[PassageEntry]`
  - `def write_manifest(m: Manifest, dir: Path) -> Path` writes `recording.json` atomically (temp file plus rename).
  - `def read_manifest(path: Path) -> Manifest`
  - `def estimate(scripts: list[Script], provider: str, prices: dict[str, float]) -> CostEstimate`, where `CostEstimate` has `characters: int`, `cost: float` and `per_recording: dict[str, int]`.
  - `def load_env(path: Path) -> dict[str, str]` is a minimal `.env` reader, `KEY=VALUE` per line with `#` comments. It adds no new dependency. `def api_key(name: str, env_path: Path) -> str` checks the environment first, then `.env`, and raises `KeyError(name)` without the value if the key is missing.

- [ ] **Step 1: Write the failing tests.**
  - **`conftest.py`:** an autouse fixture that monkeypatches `requests.Session.request` and `requests.request` to raise `RuntimeError("network disabled in tests")`.
  - **`test_script.py`:**
    - Parses a fixture with 3 passages, intensities and cues.
    - `spoken_text` strips every cue.
    - Malformed inputs each raise `ScriptError` naming the file:
      - missing front matter;
      - an unknown `show`;
      - an unknown cue `[shouts]`, with the line number in the message;
      - an empty passage;
      - an `id` not matching the filename.
    - `load_all(esoterica/scripts)` parses all eight real scripts from Task 1.
  - **`test_manifest.py`:**
    - A round trip.
    - An atomic write: no partial `recording.json` remains if serialisation fails (monkeypatch `json.dump` to raise).
  - **`test_cost.py`:** the count equals the sum of `len(spoken_text)`, and the cost equals the count times the price.
  - **`test_env.py`:**
    - Parses comments and blank lines.
    - An environment variable wins over `.env`.
    - A missing key raises an error whose message holds the name, never any value.
- [ ] **Step 2: Run** `pipenv run pytest tests/esoterica -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement the five modules.**
- [ ] **Step 4: Run** `pipenv run pytest tests/esoterica -q` and then the full `pipenv run pytest -q -m "not slow"`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(esoterica): script format, manifests, cost estimates`.

---

### Task 3: Providers, `sleepmix esoterica voice`, and the audition → STOP 2

**Files:**
- Create: `sleepmix/esoterica/providers.py`, `sleepmix/esoterica/voicing.py`, `sleepmix/esoterica/cli.py`
- Create: `esoterica/voices.yaml`
- Create: `tests/esoterica/test_providers.py`, `tests/esoterica/test_voicing.py`, `tests/esoterica/test_cli.py`
- Modify: `sleepmix/cli.py` (register the `esoterica` group)

**Interfaces:**
- Consumes: Task 2's `Script`, `spoken_text`, `estimate`, `api_key`.
- Produces:
  - **`providers.py`:**
    - `class Provider(Protocol)` with `name: str`, `max_chars: int`, `def synthesize(self, text: str, voice_id: str, model: str, language: str) -> tuple[np.ndarray, int]` (returns mono float32 samples and a sample rate), and `def translate_cues(self, text: str) -> str`.
    - `class ElevenLabs(Provider)` and `class Cartesia(Provider)`, each constructed with `(api_key: str, session: requests.Session)`.
    - `class ProviderError(RuntimeError)`.
  - **`voicing.py`:**
    - `def chunk(text: str, max_chars: int) -> list[str]` splits at sentence boundaries. It hard-splits at a word boundary only if a single sentence exceeds `max_chars`.
    - `def voice_passage(provider, text, voice, language, out: Path) -> float` does chunk → synthesize → join with 250 ms of silence and 10 ms raised-cosine edges per chunk → resample to 44100 → loudness-normalise → write WAV. It returns the duration. It does nothing if `out` exists.
    - `def voice_recording(script, provider, voice, library: Path) -> Manifest | None` voices every passage. It writes the manifest only when all passages exist, so a failure mid-way leaves the passage WAVs and no manifest. Shuffles are voiced one image per call and assembled with seeded 2–3 s gaps (seed = hash of the id).
  - **`cli.py`:** commands `sleepmix esoterica estimate`, `sleepmix esoterica audition --show <show>|--all [--yes]` and `sleepmix esoterica voice <id>|--all [--yes]`. Each prints the estimate and spends only with `--yes`.
  - **`esoterica/voices.yaml`:**
    - `providers:` gives per-provider `model`, `price_per_char` and `max_chars`, all from the current docs.
    - `candidates:` gives, per show per provider, 2–3 `{voice_id, name, why}` entries.
    - `chosen:` gives, per show, `{provider, model, voice_id}`. It stays empty until STOP 2.
    - The audition excerpt is about 120 spoken words from the first passage of each show's first script (45–60 s). Audition output goes to `esoterica/audition/<show>/<provider>-<voice-name>.wav`, plus `esoterica/audition/index.md` listing them.

- [ ] **Step 1: Read the current docs.** For each provider, record in the report:
  - the TTS endpoint and the most expressive model (ElevenLabs "v4" if it exists, as the operator flagged);
  - the per-request character limit;
  - French support;
  - expressive and delivery controls, and how they map the six neutral cues;
  - output format;
  - price per character.

  Choose the intimacy settings per the spec recipe: lower energy and slower pace, close and conversational, variability over maximum stability.
- [ ] **Step 2: List voices through each provider's voice-listing API.** These calls are free; run them outside tests, and write no key. Pick 2–3 candidates per show per provider for warmth, age and intimacy, and for French-capable voices for `meditations` and the French shuffles. Write `voices.yaml`, with each candidate's `why`.
- [ ] **Step 3: Write the failing tests.** Use fake sessions returning canned audio bytes, and never the network.
  - `chunk` keeps sentences intact and respects `max_chars`, and a 1,000-character single sentence hard-splits at word boundaries.
  - `voice_passage` joins chunks with no sample-to-sample jump greater than the jump inside the canned audio itself. Its RMS over speech frames is −24 ± 0.5 dBFS and its peak is ≤ −3 dBFS.
  - It is resumable: a second `voice_recording` run issues zero synthesize calls.
  - A mid-run failure (the fake raises `ProviderError` on passage 3) leaves passages 1–2, writes no manifest, and lets a rerun finish.
  - **Key never leaks:** construct a provider with key `"sk-TESTSECRET123"`, make the fake session return HTTP 401 with the request headers echoed in the body, and assert `"TESTSECRET"` appears in neither `str(error)` nor the captured logs.
  - **CLI:** `estimate` prints characters and cost, and `voice --all` without `--yes` makes zero synthesize calls and exits 0 with a "re-run with --yes" note.
  - Cue translation: every neutral cue maps to the provider's form or is stripped, and the provider never receives a raw `[`-cue it doesn't support.
- [ ] **Step 4: Run** `pipenv run pytest tests/esoterica -q`. Expected: FAIL.
- [ ] **Step 5: Implement it.**
- [ ] **Step 6: Run** the esoterica tests and the full non-slow suite. Expected: all PASS.
- [ ] **Step 7: Commit** `feat(esoterica): providers, voicing, cost guard, audition`.
- [ ] **Step 8: Run the audition for real.** The spend is approved by the operator. Run `pipenv run sleepmix esoterica audition --all`, record the printed estimate in the report, then run it with `--yes`.
- [ ] **Step 9: Measure each audition file** (duration, RMS, peak) and note Claude's pick per show in `voices.yaml` `chosen:`. Base the pick on the spec's recipe, the script's speaker note and any measurable proxies; don't describe sound qualities as heard. Commit `voices.yaml`.
- [ ] **Step 10: STOP 2.** The controller gives the operator `esoterica/audition/index.md`, the per-show picks, and any Cartesia spend estimate, and waits for go.

---

### Task 4: Source character, and voicing the starter set

**Files:**
- Create: `sleepmix/esoterica/character.py`, `tests/esoterica/test_character.py`
- Modify: `sleepmix/esoterica/voicing.py` (apply the source character after loudness, then re-normalise), `sleepmix/esoterica/cli.py`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces: `def apply_character(x: np.ndarray, sr: int, kind: str, seed: int) -> np.ndarray`. The recipes are all subtle (placeholders):
  - **`tape`:** wow at 0.4 Hz, ±3 cents; flutter at 7 Hz, ±1 cent; hiss at −52 dBFS; a 7 kHz lowpass.
  - **`room`:** a small-room reverb, 0.4 s decay, 15% wet.
  - **`oldmic`:** a 150–5000 Hz band, gentle `tanh` drive 1.3.
  - **`hum`:** a 50 Hz hum plus 2nd and 3rd harmonics at −55 dBFS.
  - **`clean`:** the identity.

  Reuse `sleepmix.effects` (reverb) where it fits.

- [ ] **Step 1: Write the failing tests.**
  - `clean` is the identity.
  - Each recipe keeps the RMS change within ±1.5 dB before re-normalisation, adds no click (the largest sample jump is ≤ 1.5× the input's), and is deterministic per seed.
  - `oldmic` puts < 2% of energy below 120 Hz on white noise.
  - `hum` adds a 50 Hz spectral peak.
  - The manifest records `source_character`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement it,** and wire it into `voice_passage` (the character is applied, then loudness is re-normalised).
- [ ] **Step 4: Run** the tests. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(esoterica): source character`.
- [ ] **Step 6: Bulk voicing.** The operator's go at STOP 2 approves it. Run `pipenv run sleepmix esoterica voice --all`, check the estimate fits the budget (ElevenLabs ≤ 265k credits in total, including the audition), then run it with `--yes`. Record the characters spent per provider.
- [ ] **Step 7: Verify.** All 8 recordings have a manifest. Every passage WAV exists with duration > 0 and loudness within spec. Commit any non-audio changes (audio is git-ignored).

---

### Task 5: The engine's file source and `nightctl audition voice`

**Files:**
- Create: `swift/Sources/NightDSP/Sources/FileSource.swift`, `swift/Sources/NightDSP/Primitives/WAVReader.swift`, `swift/Tests/NightDSPTests/FileSourceTests.swift`
- Modify: `swift/Sources/NightDSP/NightFactory.swift`, `swift/Sources/NightCLI/NightCtl.swift`, `swift/Tests/NightCLITests/NightCtlTests.swift`, `swift/Tests/NightDSPTests/NightFactoryTests.swift`

**Interfaces:**
- **`WAVReader`:** `public enum WAVReader { static func read(url: URL) throws -> (samples: [Float], sampleRate: Double) }`. It reads PCM int16/int24/int32 or float32, mono or stereo (stereo is mixed to mono), using Foundation only. It throws `WAVReader.Error` with a message for unsupported formats.
- **`FileSource`:** `public struct FileSource: SoundSource { public init(samples: [Float], fileSampleRate: Double, sampleRate: Double, startSecond: Double) }`.
  - It resamples linearly if the rates differ.
  - It plays from `startSecond`, so seeking is exact.
  - After the end of the file it outputs silence, preceded by a 50 ms raised-cosine fade over the file's last 50 ms, so it never stops on a click.
- **`AuditionRequest`:** gains `public var voiceFile: URL? = nil`. When it is set, `NightFactory.audition` builds `FileSource → Fragmenter → Distance → AMChannel? → guard`, with the same seeds and lead-in rules as scenes, and `scene` is ignored.
- **CLI:** `nightctl audition voice --file <path>` maps to `voiceFile`. `voice` is accepted only with `--file`. `--slowness`, `--ring`, `--softness` and `--vibrato` above 0 are rejected for voice with a message containing "must be 0 for voice".

- [ ] **Step 1: Write the failing tests.**
  - WAV round trip with `WAVWriter`, plus int16 and stereo fixtures written by the test.
  - A 48 kHz file at sampleRate 44100 keeps its duration within one frame.
  - `startSecond` seek equals a slice of a continuous render.
  - A file shorter than the render ends with a fade: the last 50 ms of the file are tapered, and the maximum sample jump at the end is ≤ the maximum jump inside the file.
  - Factory: `voiceFile` through the channel is finite, peak ≤ 0.95, and `seekingMatchesALongerRender` passes for voice.
  - CLI:
    - `["voice","--file",x]` parses to a request with `voiceFile`;
    - `["voice"]` without `--file` throws;
    - `["voice","--file",x,"--slowness","0.5"]` throws with "must be 0 for voice";
    - an unsupported WAV gives a clear error and writes no output.
- [ ] **Step 2: Run** `cd swift && swift test -c release`. Expected: FAIL.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS (Plan 7b's 104 plus the new tests).
- [ ] **Step 5: Commit** `feat(swift): file source and nightctl audition voice`.

---

### Task 6: The listening set and the docs

**Files:**
- Create: `esoterica/listening.sh`
- Modify: `docs/project-state.md`, `docs/architecture.md`, `README.md`, `swift/README.md`, `esoterica/README.md`

- [ ] **Step 1: Write `esoterica/listening.sh`.** For one passage per recording, it renders the raw passage plus `nightctl audition voice` versions at `--distance 0` and at `--distance 0.6 --fragmentation 0.3` (both with the channel), into the git-ignored `esoterica/listening/`. It also prints RMS, peak and centroid. Run it.
- [ ] **Step 2: Update `docs/project-state.md`.** Add a "Plan 8a: the Esoterica starter set" section covering:
  - what shipped;
  - the provider facts found in the docs;
  - the voices chosen and why;
  - characters and credits spent;
  - every placeholder by name and value (loudness targets, chunk gap, shuffle gaps, character recipes, audition excerpt length, the fade);
  - that the chimes should sit quieter under a voice, which is the planner's mixing job;
  - that the link-import door is open (a manifest for any audio);
  - that the listening judgement is outstanding.

  Also update the top "Where the project is heading" section: the voice layer is now Esoterica.
- [ ] **Step 3: Update the rest of the docs.**
  - `architecture.md`: the esoterica pipeline (script → voice → character → manifest → engine file source), and the test isolation from network and credits.
  - The READMEs: the commands.
- [ ] **Step 4: Run** `pipenv run pytest -q -m "not slow"` and `cd swift && swift test -c release`. Record the counts.
- [ ] **Step 5: Commit** `docs: Plan 8a — esoterica starter set`.
- [ ] **Step 6: Hand the listening set to the operator,** with the paths.
