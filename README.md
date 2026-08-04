# sleepmix

Turn a song into an extended, slowly **disintegrating** ambient sleep mix.

Inspired by the [Sollos](https://findsollos.com/) sleep remixes (slowed-and-reverb
reworks of popular tracks) crossed with William Basinski's *Disintegration Loops*
— except the decay is applied **per stem**, so you can let the vocal dissolve
into reverb-ghosts while the harmonic bed stays (almost) intact. That selective
control is the whole point of doing it programmatically: you can't erode just the
voice of a finished stereo master, but you can once it's been separated.

```
song.flac ──► separate ──► loop ──► slow + pitch ──► disintegrate ──► reverb ──► sum ──► sound bed ──► master ──► sleepmix.wav
              (Demucs)    (beat-     (Rubber Band)   (per-stem decay)            (pink noise +
                           aligned)                                              binaural beats)
```

## How it works

| Stage | What it does | Engine | Fallback if not installed |
|-------|--------------|--------|---------------------------|
| **Separate** | Split into `vocals / drums / bass / other` | Demucs (`htdemucs_ft`) | whole track as one `mix` stem |
| **Find loop** | Pick a beat-aligned, seam-matched N-bar segment | librosa | fixed-tempo guess |
| **Slow + pitch** | The "slowed" half of slowed-and-reverb | Rubber Band | librosa phase-vocoder → resample |
| **Disintegrate** | Erode each stem a bit more on every repetition | numpy/scipy | *(always available)* |
| **Reverb** | Cavernous space | pedalboard | numpy Schroeder reverb |
| **Sound bed** | Pink/brown noise + binaural beats | numpy | *(always available)* |
| **Master** | Crossfade cycles, fades, peak-normalize | numpy | *(always available)* |

Everything runs on the core deps alone — the heavy ML/CLI stages each degrade
gracefully — so you can develop and audition the creative layers, then add the
high-quality engines when you want a final render.

### The disintegration model

A single seamless loop is repeated to fill the target duration. On each
repetition, `progress` goes 0 → 1 and these are interpolated from their
`*_start` to `*_end` settings:

- **lowpass cutoff** sweeps down — high frequencies erode first, like tape oxide
- **spectral holes** — a fixed random set of frequency bins is removed (reads as
  "missing frequencies", not noise)
- **dropouts** — brief, click-free gaps punched in
- **amplitude** fades
- **noise floor** rises (tape hiss)

A `curve` (`linear` / `exp` ease-in / `log` ease-out) shapes how fast a stem
gives way. Defaults: **vocals** dissolve on an ease-in curve while **bass** holds
steady and **drums** are off — but it's all per-stem config (see below).

## Install

sleepmix is a command-line tool rather than a library, so install it the way
you'd install any tool — in its own environment, with its entry point on your
PATH:

```bash
pipx install "sleepmix[all,ui]"
sleepmix render --input song.flac --output mix.wav
```

`uv tool install "sleepmix[all,ui]"` does the same thing if you prefer uv.
Either way there's no environment to activate and nothing to remember later.

Plain `pip install` into your system Python will likely refuse — most Python
installs are now marked externally-managed (PEP 668) so that pip and your
package manager can't fight over the same directory. That's a good default,
and pipx works with it rather than around it.

### Extras

| Extra | Adds | Cost |
|---|---|---|
| *(none)* | The full pipeline via fallbacks | small |
| `all` | Demucs, librosa, Rubber Band, soxr | ~700 MB — PyTorch and Demucs are large |
| `ui` | FastAPI + uvicorn, for `sleepmix ui` | small |

Everything runs on the base install alone: without `all` you get one `mix`
stem instead of four separated ones, and a rougher loop, but a complete render.
Add it when you want a final one.

Rubber Band is the one piece that isn't pip-installable — it wants the
`rubberband` CLI on your PATH (`brew install rubberband`, `apt install
rubberband-cli`). Without it, time-stretching falls back to librosa's phase
vocoder, which is what most renders have used in practice.

### Working on sleepmix

Contributors want a checkout rather than an installed copy. The repo carries a
`Pipfile`:

```bash
git clone https://github.com/<you>/sleepmixer && cd sleepmixer
pipenv install --dev
pipenv run pytest -q
pipenv run sleepmix ui
```

Plain venv works too, if you'd rather not add pipenv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all,ui,dev]"
```

## Usage

```bash
# Render with defaults (25-min mix, vocals disintegrate, bass holds)
sleepmix render --input song.flac --output mix.wav

# Write a fully-commented config, tweak it, render with it
sleepmix init-config --output sleepmix.yaml
sleepmix render --input song.flac --config sleepmix.yaml --output mix.wav

# Quick overrides without a config file
sleepmix render --input song.flac --duration 45 --speed 0.6 --soundbed
```

### UI (early)

```bash
sleepmix ui
```

Starts a local server on `127.0.0.1:8765` and opens a browser tab. That tab
still shows a placeholder page — the interactive interface (library, waveform,
mixer) is a separate, later change (Plan 3, if you're following along in
`docs/project-state.md`). What's already there, and works today, is everything
underneath that interface: the whole workflow, driven by HTTP.

Import a song by path and the server decodes it, registers it in a local
SQLite library, and gives you back a waveform. Kick off stem separation
(vocals/drums/bass/other, via Demucs, with a plain-mix fallback if you haven't
installed it) as a background job and watch it progress over server-sent
events. Ask for a preview — any single point in the decay arc, by a `progress`
value from 0 to 1 — and get raw WAV bytes back in well under a second, no
matter how far into a twenty-five-minute mix that point is; that's the same
cheap-preview property described under "The disintegration model" above, now
reachable over HTTP. Start a full render as another background job, watch it
the same way, cancel it if you want to, and download the finished file once
it's done. Save a set of decay settings as a named preset and reuse it. All of
this already exists, is tested, and works from a shell with `curl` — there
just isn't a page wrapping it in a mixer yet. That page is the entire content
of the next piece of work; nothing about the API is expected to change to make
room for it.

**Keep it on localhost.** There is no authentication, and importing a song
takes a filesystem path — so anything that can reach the port can ask the
server to read any audio file your user account can read, and get a detailed
waveform of it back. That's fine when the only thing that can reach it is you.
It is not fine on a shared network, so `sleepmix ui` refuses a non-loopback
`--host` unless you pass `--allow-remote`.

Or from Python:

```python
from sleepmix import MixConfig, run_pipeline

cfg = MixConfig()
cfg.output.duration_min = 30
cfg.soundbed.enabled = True
run_pipeline("song.flac", cfg, "mix.wav")
```

## Configuring the decay

Each stem has its own `decay` block. To make the **vocal** the thing that
haunts and fades while everything else sustains:

```yaml
stems:
  - name: vocals
    decay:
      curve: exp            # stays present, then dissolves late
      lowpass_end_hz: 2200
      amp_end_db: -16
      spectral_hole_end: 0.45
  - name: other            # pads/synths/guitars — the harmonic bed
    decay:
      curve: linear
      amp_end_db: -4
  - name: bass
    decay: { enabled: false }   # rock-steady low end
  - name: drums
    enabled: false              # usually too rhythmic for sleep
```

See `sleepmix/config.example.yaml` for every field with comments.

## Notes & caveats

- **Binaural beats need headphones** (each ear gets a different carrier; the
  brain perceives the difference). The wellness claims around them are weak —
  treat the sound bed as an aesthetic layer, not therapy.
- **mp3 decoding** depends on your libsndfile build; WAV/FLAC always work.
- Separation results are cached under your platform's app-data directory
  (`~/Library/Application Support/sleepmix` on macOS, `~/.local/share/sleepmix`
  on Linux), keyed by file + model, so re-rendering with different creative
  settings skips the slow ML step. Set `SLEEPMIX_DATA_DIR` to move it. Older
  versions cached into a `.sleepmix_cache/` beside wherever you happened to be
  standing; if you have one of those, it's orphaned and safe to delete.
- For **copyrighted music**, keep renders personal — this is a tool for your own
  listening, not redistribution.

## Development

See [Working on sleepmix](#working-on-sleepmix) above for getting set up.

The test suite covers the DSP core (disintegration, sound bed, looping, config)
and a full end-to-end render. It needs no ML dependencies installed, and it
does not use them when they are: separation is replaced by a synthetic stub
(`tests/conftest.py`), except in `test_full_render_fallback`, which forces
Demucs to fail so it genuinely exercises the single-`mix`-stem fallback path.
`tests/conftest.py` also points every test at an isolated, throwaway
`SLEEPMIX_DATA_DIR` (see `docs/architecture.md`), so a test run never touches
your real separation cache.

## License

MIT
