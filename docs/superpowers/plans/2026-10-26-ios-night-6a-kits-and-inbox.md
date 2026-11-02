# Plan 6a: kits and the drop folder — Implementation Plan

> **Superseded 2026-11-02, never executed.** The AM-night design
> (`../specs/2026-11-02-am-night-design.md`, Plan 7) drops songs as the
> night's material, so there are no kits and no drop folder. Kept for the
> record only. Do not implement.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dropping an audio file into `Sleepmix/Inbox` in iCloud Drive turns it, with no further action, into a self-contained **kit** in `Sleepmix/Kits/` that the iPhone app (Plan 6b) will read.

**Architecture:** Two new modules under `sleepmix/night/`. `kits.py` defines the kit format (the contract between Python and Swift) and exports a prepared `SourceProfile` into a kit folder atomically. `inbox.py` runs one pass over the drop folder: it waits for files to finish arriving, prepares them with the existing `prepare_source`, exports kits, and files the originals. Three new CLI commands drive it: `sleepmix watch` polls, and `sleepmix install-watcher` / `uninstall-watcher` manage a launchd user agent that runs `watch` at low priority.

**Tech Stack:** Python 3.14, click, pytest, `mutagen` (new; for track titles), launchd/`launchctl` (macOS).

**Spec:** `docs/superpowers/specs/2026-10-25-ios-night-design.md`, sections "1. Adding a track", "2. The kit format", and "Decisions from the builder check". This is the first of three plans: **6a** (this one: the Mac side), **6b** (Swift port and app, without steering), **6c** (steering by movement). The overnight motion spike runs alongside 6a/6b as a throwaway and has no plan.

## Global Constraints

- Baseline: **672 tests pass** on `feat/ios-night` before Task 1 (`pipenv run pytest -q`). Every task ends with the full suite green.
- The Python preparer stays the only preparer. Nothing here re-implements separation, looping or pitch analysis. `inbox.py` calls `prepare.prepare_source`.
- `kits.py` imports no audio (no numpy, scipy, soundfile, pedalboard, `sleepmix.audio`) so the kit format can be reasoned about and tested without decoding anything. It is enforced with `tests/import_guard.py`'s `forbidden_imports`, the same way `test_plan_module_imports_no_audio` does.
- Kit format version is **1**. The layout is exactly:
  ```
  Kits/<kit_id>/kit.json
  Kits/<kit_id>/loop-0.wav, loop-1.wav, …
  ```
  and `kit.json` is exactly these keys: `format_version` (int), `kit_id` (str), `title` (str), `sr` (int), `loops` (list of `{"file": str, "frames": int}`), `pitch_set` (list of float), `prepared_at` (UTC ISO-8601 string ending `Z`). Paths inside a kit are bare filenames, never absolute or containing a separator.
- Folder names under the root, verbatim: `Inbox`, `Kits`, `Originals`, `Couldn't prepare`, `Nights`. (`Nights` is created now and written by 6b.)
- The root defaults to the app's iCloud container Documents folder, `~/Library/Mobile Documents/iCloud~com~moopius~sleepmix/Documents`, overridable by the `SLEEPMIX_ICLOUD_ROOT` env var or `--root`. **Plan 6b must use the bundle ID `com.moopius.sleepmix` and the container `iCloud.com.moopius.sleepmix`** for this path to be right. Record this in both plans.
- A kit's identity is derived from the file's **content**, not its path, so moving a file from `Inbox` to `Originals` (or dropping it twice) can't produce a second kit (spec: "`source_id` must stay stable when a file moves").
- Tests never touch the real iCloud folder or real launchd: every test passes `root=tmp_path/...` and injects the `launchctl` runner. `conftest.py` already isolates `SLEEPMIX_DATA_DIR`.
- Every new tunable number is a named module constant with a comment that marks it as a placeholder, matching `prepare.py`'s style, and it gets listed in `docs/project-state.md` (Task 3).

## Review Focus

1. **A file still being copied or downloaded into `Inbox`.** Finder copies, Files uploads and iCloud downloads all leave a partial file or a `.name.icloud` stub for a while. Expected: it's left alone until it's real and has stopped changing, never prepared half-written or failed for being half-written. Tests: Task 2, `test_a_file_still_arriving_is_left_alone` and `test_an_icloud_placeholder_is_left_alone`.
2. **The same song dropped twice**, or dropped again after it was already prepared, possibly with the same filename. Expected: one kit. The second copy goes to `Originals` without overwriting the first copy there. Tests: Task 2, `test_dropping_the_same_song_twice_makes_one_kit` and `test_a_name_clash_in_originals_never_overwrites`.
3. **The phone reading `Kits/` while a kit is being written.** Expected: it sees either no kit or a whole one, never a folder with a `kit.json` naming loops that aren't there yet. Test: Task 1, `test_export_never_leaves_a_partial_kit_visible`.
4. **Something that isn't a usable song** (a PDF, a corrupt mp3, a two-second clip). Expected: it moves to `Couldn't prepare` with a readable reason beside it, and isn't retried on every pass forever. Test: Task 2, `test_a_file_that_cannot_be_prepared_is_set_aside_with_a_reason`.
5. **One bad file, or one bad pass, killing the watcher.** Expected: an exception while preparing one file fails that file, and the next file is still processed. An exception escaping a whole pass is logged, and `watch` keeps polling. Tests: Task 2, `test_an_exception_while_preparing_fails_only_that_file`, and Task 3, `test_watch_survives_a_pass_that_raises`.

---

### Task 1: The kit format and its exporter

**Files:**
- Create: `sleepmix/night/kits.py`
- Modify: `sleepmix/night/sources.py` (add `slug_for`), `sleepmix/night/prepare.py:98-133` (`source_id_for` uses `slug_for`; no behaviour change)
- Modify: `pyproject.toml` (`dependencies`), `requirements.txt` (core list), `Pipfile` (`[packages]`): add `mutagen>=1.47`
- Test: `tests/test_night_kits.py`

**Interfaces:**
- Consumes: `SourceProfile` (`sleepmix/night/sources.py`): `source_id`, `loop_paths`, `loop_frames`, `pitch_set`, `sr`.
- Produces:
  - `sources.slug_for(path: str) -> str`: the existing slug rule from `source_id_for` (basename without extension, non-alphanumerics → `-`, stripped, lowercased, max 40 chars), moved here.
  - `kits.KIT_FORMAT_VERSION = 1`, `kits.KIT_FILE = "kit.json"`
  - `@dataclass(frozen=True) class Kit: kit_id: str; title: str; sr: int; loop_files: tuple[str, ...]; loop_frames: tuple[int, ...]; pitch_set: tuple[float, ...]; prepared_at: str; format_version: int = KIT_FORMAT_VERSION`
  - `kits.kit_id_for(path: str) -> str`: `f"{slug}-{digest}"` (or bare `digest` if the slug is empty), where `digest` is the first 12 hex chars of SHA-256 over the file's bytes, read in chunks.
  - `kits.title_for(path: str) -> str`: the `title` tag via `mutagen.File(path, easy=True)` when present and non-blank, otherwise the filename stem with `_` replaced by spaces. Never raises.
  - `kits.export_kit(profile: SourceProfile, kits_dir: str, *, kit_id: str, title: str, now: datetime.datetime) -> str`: returns the final kit directory.
  - `kits.read_kit(kit_dir: str) -> Kit | None`
  - `kits.list_kits(kits_dir: str) -> tuple[Kit, ...]`: every readable kit, sorted by `kit_id`. Ignores dot-entries.

- [ ] **Step 1: Write the failing tests** in `tests/test_night_kits.py`. Build a `SourceProfile` from two tiny WAVs written with `soundfile` into `tmp_path` (the test may use soundfile; `kits.py` may not).

```python
def test_kit_ids_follow_content_not_path(tmp_path):
    a = tmp_path / "Inbox" / "My Song.wav"; b = tmp_path / "Originals" / "My Song.wav"
    # same bytes at two paths
    assert kit_id_for(str(a)) == kit_id_for(str(b))
    assert kit_id_for(str(a)).startswith("my-song-")
    assert len(kit_id_for(str(a)).rsplit("-", 1)[1]) == 12

def test_kit_ids_differ_when_content_differs(tmp_path): ...

def test_export_writes_exactly_the_documented_kit(tmp_path):
    kit_dir = export_kit(profile, str(tmp_path / "Kits"), kit_id="song-abc",
                         title="Song", now=datetime(2026, 10, 26, 22, 0, tzinfo=timezone.utc))
    data = json.load(open(os.path.join(kit_dir, "kit.json")))
    assert set(data) == {"format_version", "kit_id", "title", "sr", "loops", "pitch_set", "prepared_at"}
    assert data["format_version"] == 1
    assert data["loops"] == [{"file": "loop-0.wav", "frames": profile.loop_frames[0]},
                             {"file": "loop-1.wav", "frames": profile.loop_frames[1]}]
    assert data["prepared_at"] == "2026-10-26T22:00:00Z"
    assert sorted(os.listdir(kit_dir)) == ["kit.json", "loop-0.wav", "loop-1.wav"]

def test_export_then_read_round_trips(tmp_path):
    assert read_kit(kit_dir) == Kit(kit_id="song-abc", title="Song", sr=profile.sr,
        loop_files=("loop-0.wav", "loop-1.wav"), loop_frames=profile.loop_frames,
        pitch_set=profile.pitch_set, prepared_at="2026-10-26T22:00:00Z")

def test_export_never_leaves_a_partial_kit_visible(tmp_path, monkeypatch):
    # make the second loop copy raise mid-export
    with pytest.raises(OSError):
        export_kit(...)
    assert list_kits(str(tmp_path / "Kits")) == ()
    assert [n for n in os.listdir(tmp_path / "Kits") if not n.startswith(".")] == []

def test_export_replaces_an_existing_kit_with_the_same_id(tmp_path): ...

def test_read_kit_skips_what_it_cannot_trust(tmp_path):
    # each of these → None: missing kit.json; invalid JSON; format_version 2;
    # a loop "file" of "../x.wav" or "/abs.wav"; a named loop file that is absent;
    # len(loops) == 0
    ...

def test_title_prefers_the_tag_then_the_filename(tmp_path):
    assert title_for(str(tmp_path / "rainy_sunday_take2.wav")) == "rainy sunday take2"  # untagged
    assert title_for(str(tmp_path / "missing.mp3")) == "missing"                        # unreadable

def test_kits_module_imports_no_audio():
    assert forbidden_imports("sleepmix/night/kits.py", AUDIO_MODULES) == []
```

(Reuse the forbidden list that `tests/test_night_plan.py::test_plan_module_imports_no_audio` uses, minus the `night.*` siblings that aren't relevant. Import it or copy the tuple, whichever that test file allows.)

- [ ] **Step 2: Run them to verify they fail**

Run: `pipenv run pytest tests/test_night_kits.py -q`
Expected: FAIL with `ModuleNotFoundError: sleepmix.night.kits`

- [ ] **Step 3: Add `mutagen>=1.47`** to the three dependency lists and run `pipenv install`.

- [ ] **Step 4: Move the slug rule into `sources.slug_for`** and make `prepare.source_id_for` call it. The existing `tests/test_night_prepare.py` id tests are the check that nothing changed.

- [ ] **Step 5: Implement `sleepmix/night/kits.py`.** Atomic export: copy loops (`shutil.copyfile`) to `loop-{i}.wav` and write `kit.json` inside a staging directory `kits_dir/.staging-<kit_id>` (dot-prefixed, so `list_kits` and the phone ignore it). Remove any stale staging dir for this id first. If the final dir exists, rename it aside to `.old-<kit_id>`, `os.replace` the staging dir into place, then delete the aside. On any exception, remove the staging dir and re-raise. `read_kit` follows `sources._read_profile`'s rule: every problem is a skip (`None`), never a raise. Validate `kit_id` the way `write_profile` validates `source_id` (raise `ValueError` on an unsafe id; that's a programming error).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pipenv run pytest tests/test_night_kits.py tests/test_night_prepare.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite** with `pipenv run pytest -q`. Expected: all pass (672 plus the new ones).

- [ ] **Step 8: Commit**

```bash
git add sleepmix/night/kits.py sleepmix/night/sources.py sleepmix/night/prepare.py tests/test_night_kits.py pyproject.toml requirements.txt Pipfile Pipfile.lock
git commit -m "feat: a kit is a prepared song the phone can carry"
```

---

### Task 2: One pass over the drop folder

**Files:**
- Create: `sleepmix/night/inbox.py`
- Test: `tests/test_night_inbox.py`

**Interfaces:**
- Consumes: `kits.kit_id_for`, `kits.title_for`, `kits.export_kit`, and `Kit` from Task 1; `prepare.prepare_source(path, sr=44100, *, source_id=None) -> SourceProfile | None`, plus `prepare._MEDIA_SUFFIXES` (promote it to the public `MEDIA_SUFFIXES` and update its one existing use).
- Produces:
  - Constants: `INBOX = "Inbox"`, `KITS = "Kits"`, `ORIGINALS = "Originals"`, `FAILED = "Couldn't prepare"`, `NIGHTS = "Nights"`; `STABLE_AGE_S = 30.0` (placeholder: how long a file must go unmodified before it counts as arrived).
  - `default_root() -> str`: `SLEEPMIX_ICLOUD_ROOT` if set, otherwise `~/Library/Mobile Documents/iCloud~com~moopius~sleepmix/Documents` (expanded).
  - `ensure_layout(root: str) -> None`: creates the five folders and nothing above `root`. `root` itself must already exist; raises `FileNotFoundError` if not. (The iCloud container is created by the app, and the Mac must not fabricate it.)
  - `Prepare = Callable[[str, str], SourceProfile | None]` taking `(path, kit_id)`. The default is `lambda path, kit_id: prepare_source(path, source_id=kit_id)`.
  - `@dataclass(frozen=True) class InboxOutcome: name: str; status: str  # "prepared" | "duplicate" | "failed"; kit_id: str | None; reason: str | None`
  - `process_inbox(root: str, *, prepare: Prepare = <default>, now: Callable[[], float] = time.time, clock: Callable[[], datetime.datetime] = <utc now>) -> list[InboxOutcome]`

Behaviour of `process_inbox`, one file at a time in sorted name order:

| What's in `Inbox` | What happens | Outcome |
|---|---|---|
| A name starting with `.` (including `.Song.wav.icloud` stubs, `.DS_Store`) | Ignored. For `.icloud` stubs, best-effort `brctl download <path>` (errors swallowed) so it arrives by a later pass. | none |
| A directory | Ignored. | none |
| Modified less than `STABLE_AGE_S` ago (`now() - st_mtime`) | Left for a later pass. | none |
| Suffix not in `MEDIA_SUFFIXES` | Moved to `FAILED`, with `<name>.txt` beside it saying `Not an audio file sleepmix can read (expected one of: …).` | `failed` |
| `Kits/<kit_id>` already holds a readable kit | Moved to `ORIGINALS`. | `duplicate` |
| `prepare` returns `None` | Moved to `FAILED`, with `<name>.txt`: `Couldn't prepare this file: it may not be decodable audio, or it may be too short to find a loop in.` | `failed` |
| `prepare` raises | Same as `None`, but the reason ends with the exception's one-line `repr`, and it's logged with traceback. | `failed` |
| `prepare` returns a profile | `export_kit(profile, Kits, kit_id=…, title=title_for(path), now=clock())`, then the file moves to `ORIGINALS`. If `export_kit` raises `OSError`, the file **stays in `Inbox`** to be retried next pass (an environmental failure, not a fact about the song) and no outcome is recorded. | `prepared` |

Moves into `ORIGINALS` or `FAILED` never overwrite: on a name clash, use `Name (2).ext`, `Name (3).ext`, and so on, with the matching `.txt` for failures.

- [ ] **Step 1: Write the failing tests** in `tests/test_night_inbox.py`. Use a `fake_prepare(path, kit_id)` that writes two short WAVs into `tmp_path/loops` and returns a `SourceProfile`, and a `now` fixed 60 s after the files' mtime (set with `os.utime`).

```python
def test_a_dropped_song_becomes_a_kit_and_the_original_is_filed(tmp_path):
    out = process_inbox(root, prepare=fake_prepare, now=lambda: T + 60)
    assert [(o.name, o.status) for o in out] == [("Song.wav", "prepared")]
    assert read_kit(os.path.join(root, "Kits", out[0].kit_id)) is not None
    assert os.listdir(os.path.join(root, "Inbox")) == []
    assert os.listdir(os.path.join(root, "Originals")) == ["Song.wav"]

def test_a_file_still_arriving_is_left_alone(tmp_path):
    assert process_inbox(root, prepare=boom, now=lambda: T + 5) == []   # boom fails the test if called
    assert os.listdir(os.path.join(root, "Inbox")) == ["Song.wav"]

def test_an_icloud_placeholder_is_left_alone(tmp_path, monkeypatch):
    # ".Song.wav.icloud" in Inbox; monkeypatch subprocess.run to record the call
    assert process_inbox(root, prepare=boom, now=...) == []
    assert recorded == [["brctl", "download", <stub path>]]

def test_dropping_the_same_song_twice_makes_one_kit(tmp_path):
    # pass 1: "Song.wav"; pass 2: same bytes as "Song copy.wav"
    assert [o.status for o in second] == ["duplicate"]
    assert len(list_kits(os.path.join(root, "Kits"))) == 1

def test_a_name_clash_in_originals_never_overwrites(tmp_path):
    # Originals already has "Song.wav" (different bytes) → new one lands as "Song (2).wav"

def test_a_file_that_cannot_be_prepared_is_set_aside_with_a_reason(tmp_path):
    # notes.pdf → failed, "Couldn't prepare/notes.pdf" + "notes.pdf.txt" mentioning "Not an audio file"
    # clip.wav with prepare returning None → failed, its .txt mentions "too short"
    # a second pass returns [] (nothing retried)

def test_an_exception_while_preparing_fails_only_that_file(tmp_path):
    # a.wav raises RuntimeError("kaboom"), b.wav prepares
    assert [(o.name, o.status) for o in out] == [("a.wav", "failed"), ("b.wav", "prepared")]
    assert "kaboom" in open(<a.wav.txt>).read()

def test_a_kit_that_fails_to_write_leaves_the_song_in_the_inbox(tmp_path, monkeypatch):
    # monkeypatch inbox.export_kit to raise OSError → out == [], Inbox still has the file

def test_ensure_layout_makes_the_folders_but_not_the_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_layout(str(tmp_path / "absent"))
    ensure_layout(str(tmp_path)); assert {"Inbox", "Kits", "Originals", "Couldn't prepare", "Nights"} <= set(os.listdir(tmp_path))

def test_default_root_honours_the_env_var(monkeypatch): ...
def test_default_root_is_the_apps_icloud_container(monkeypatch):
    assert default_root().endswith("Library/Mobile Documents/iCloud~com~moopius~sleepmix/Documents")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipenv run pytest tests/test_night_inbox.py -q`
Expected: FAIL with `ModuleNotFoundError: sleepmix.night.inbox`

- [ ] **Step 3: Implement `sleepmix/night/inbox.py`** according to the table above. Import `prepare_source` lazily inside the default `Prepare` so importing `inbox` stays cheap.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pipenv run pytest tests/test_night_inbox.py tests/test_night_prepare.py -q`
Expected: PASS

- [ ] **Step 5: Run the full suite** with `pipenv run pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add sleepmix/night/inbox.py sleepmix/night/prepare.py tests/test_night_inbox.py
git commit -m "feat: a song dropped in the inbox is prepared and filed"
```

---

### Task 3: `watch`, the launchd agent, and the record

**Files:**
- Create: `sleepmix/night/agent.py` (plist and launchctl; no audio)
- Modify: `sleepmix/cli.py` (three commands, next to `prepare`)
- Modify: `docs/architecture.md` (new section), `docs/project-state.md` (new Plan 6a section and placeholders), `README.md` (a short "On your iPhone" usage section)
- Test: `tests/test_night_agent.py`, `tests/test_cli.py` (additions)

**Interfaces:**
- Consumes: `inbox.default_root`, `inbox.ensure_layout`, `inbox.process_inbox`, `InboxOutcome` (Task 2).
- Produces:
  - `agent.LABEL = "com.moopius.sleepmix.watcher"`
  - `agent.plist_path() -> str`: `~/Library/LaunchAgents/com.moopius.sleepmix.watcher.plist`
  - `agent.build_plist(executable: str, root: str | None, log_path: str) -> dict`: a dict for `plistlib.dumps` with `Label`, `ProgramArguments = [executable, "-m", "sleepmix.cli", "watch"]` plus `["--root", root]` when given, `RunAtLoad: True`, `KeepAlive: True`, `ProcessType: "Background"`, `LowPriorityIO: True`, `Nice: 10`, and `StandardOutPath` / `StandardErrorPath` = `log_path`. Log path: `<data_dir>/watcher.log`.
  - `agent.install(runner: Callable[[list[str]], int] = <subprocess>, executable: str = sys.executable, root: str | None = None) -> str`: writes the plist, runs `launchctl bootout gui/<uid>/<LABEL>` (non-zero ignored, so reinstalling works), then `launchctl bootstrap gui/<uid> <plist>`. Returns the plist path and raises `RuntimeError` if bootstrap fails.
  - `agent.uninstall(runner=…) -> bool`: bootout, then delete the plist. Returns whether a plist existed.
  - CLI `sleepmix watch [--root PATH] [--interval SECONDS=60] [--once]`. Before the first pass it calls `os.nice(10)` (best effort) and `ensure_layout`. A missing root exits with code 1 and the message `The Sleepmix iCloud folder doesn't exist yet: <root>\nOpen the sleepmix app on your iPhone once to create it, or pass --root.` It echoes one line per outcome (`prepared: Song.wav`, `already have: Song copy.wav`, `couldn't prepare: notes.pdf — <reason>`). An exception escaping a pass is logged and the loop continues. `--once` runs a single pass and exits 0.
  - CLI `sleepmix install-watcher [--root PATH]` and `sleepmix uninstall-watcher`.
  - `WATCH_INTERVAL_S = 60.0` in `inbox.py` (placeholder).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_night_agent.py
def test_the_plist_runs_watch_quietly_in_the_background():
    p = build_plist("/py", None, "/log")
    assert p["ProgramArguments"] == ["/py", "-m", "sleepmix.cli", "watch"]
    assert p["ProcessType"] == "Background" and p["LowPriorityIO"] is True and p["Nice"] == 10
    assert p["RunAtLoad"] is True and p["KeepAlive"] is True
    plistlib.dumps(p)  # serialisable

def test_the_plist_carries_an_explicit_root():
    assert build_plist("/py", "/r", "/log")["ProgramArguments"][-2:] == ["--root", "/r"]

def test_install_writes_the_plist_and_bootstraps_it(tmp_path, monkeypatch):
    # monkeypatch HOME to tmp_path; runner records argv lists and returns 0
    assert calls[0][:2] == ["launchctl", "bootout"] and calls[1][:2] == ["launchctl", "bootstrap"]
    assert os.path.exists(path)

def test_install_survives_nothing_to_boot_out(...):   # bootout returns 3 → still installs
def test_install_raises_when_bootstrap_fails(...):    # bootstrap returns 5 → RuntimeError
def test_uninstall_removes_the_plist(...); def test_uninstall_with_nothing_installed_is_fine(...)

# tests/test_cli.py additions (click CliRunner)
def test_watch_once_processes_the_inbox(tmp_path, monkeypatch):
    # monkeypatch sleepmix.night.inbox.process_inbox to return one "prepared" outcome
    assert result.exit_code == 0 and "prepared: Song.wav" in result.output

def test_watch_without_the_icloud_folder_says_what_to_do(tmp_path):
    result = runner.invoke(main, ["watch", "--once", "--root", str(tmp_path / "absent")])
    assert result.exit_code == 1 and "Open the sleepmix app on your iPhone" in result.output

def test_watch_survives_a_pass_that_raises(tmp_path, monkeypatch):
    # process_inbox raises on call 1, returns [] on call 2; monkeypatch time.sleep to
    # raise KeyboardInterrupt on its 2nd call to end the loop; assert process_inbox called twice
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipenv run pytest tests/test_night_agent.py tests/test_cli.py -q`
Expected: FAIL (module and commands missing)

- [ ] **Step 3: Implement `sleepmix/night/agent.py` and the three CLI commands.** Keep the command bodies thin, the way `prepare` is: lazy imports, `click.echo`. `KeyboardInterrupt` in `watch` exits 0 quietly.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pipenv run pytest tests/test_night_agent.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Smoke-test against a scratch root** (not iCloud): make a temp dir, copy the repo's `nackmandela.mp3` into `<tmp>/Inbox/`, backdate its mtime by 60 s with `touch -t`, and run `pipenv run sleepmix watch --once --root <tmp>`. Expected: `prepared: nackmandela.mp3`, a kit under `<tmp>/Kits/` whose `kit.json` matches the documented shape, and the mp3 in `<tmp>/Originals/`. Do **not** run `install-watcher` during implementation. It changes the operator's login session, and the operator runs it themselves once the app exists.

- [ ] **Step 6: Write the record.**
  - `docs/architecture.md`: a section "Kits and the drop folder", covering the kit format as a two-language contract, content-derived identity and why, the atomic export, the `Inbox` → `Originals`/`Couldn't prepare` lifecycle, and why the Mac never creates the iCloud container.
  - `docs/project-state.md`: a "Plan 6a" section at the top in the existing voice. List the placeholders `STABLE_AGE_S = 30` and `WATCH_INTERVAL_S = 60`, and the bundle ID `com.moopius.sleepmix` that 6b must match. Note that the watcher only becomes useful once 6b's app has created the container. Update the test count.
  - `README.md`: a short "On your iPhone (coming)" note: `sleepmix install-watcher`, and drop files into `Sleepmix/Inbox`.

- [ ] **Step 7: Run the full suite** with `pipenv run pytest -q`. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add sleepmix/night/agent.py sleepmix/night/inbox.py sleepmix/cli.py tests/test_night_agent.py tests/test_cli.py docs/architecture.md docs/project-state.md README.md
git commit -m "feat: the inbox watches itself, and a launch agent keeps it watching"
```
