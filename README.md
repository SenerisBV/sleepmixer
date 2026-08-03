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

```bash
pip install -e .                 # core: full pipeline via fallbacks
pip install -e ".[all]"          # + Demucs, librosa, Rubber Band, soxr (large)
```

The `[all]` extra pulls in PyTorch + Demucs (multi-GB). Rubber Band also needs
the `rubberband` CLI on your PATH (`brew install rubberband` /
`apt install rubberband-cli`).

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
- Separation results are cached in `.sleepmix_cache/` keyed by file + model, so
  re-rendering with different creative settings skips the slow ML step.
- For **copyrighted music**, keep renders personal — this is a tool for your own
  listening, not redistribution.

## Development

```bash
pipenv install --dev
pipenv run pytest -q
```

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
