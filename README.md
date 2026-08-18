# sleepmix

Turn a song into an extended, slowly **disintegrating** ambient sleep mix.

Inspired by the [Sollos](https://findsollos.com/) sleep remixes (slowed-and-reverb
reworks of popular tracks) crossed with William Basinski's *Disintegration Loops*
— except the decay is applied **per stem**, so you can let the vocal dissolve
into reverb-ghosts while the harmonic bed stays (almost) intact. That selective
control is the whole point of doing it programmatically: you can't erode just the
voice of a finished stereo master, but you can once it's been separated.

*Not affiliated with, endorsed by, or connected to Sollos or any artist named
here — they're cited as influences on the sound, nothing more.*

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

Where those repeats land is its own setting: back to back by default, or with a
gap that grows as the mix goes on, or overlapping so the loop plays over itself.
See "Spacing the repeats" below.

## Music you didn't make

sleepmix takes a recording you already have and produces a derivative of it.
It is built for private listening — your own ears, your own library. Renders of
music you don't hold the rights to aren't yours to publish, sell, or
distribute, and nothing about this tool changes that.

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

### UI

```bash
sleepmix ui
```

Starts a local server on `127.0.0.1:8765`, opens a browser tab, and serves a
small [Elm](https://elm-lang.org/) application — compiled and committed into
the package, so running this needs nothing beyond the `ui` extra. It's a
library browser, a song screen, a mixer you can hear while you shape it, and —
since this branch — a way to actually finish with what you've been shaping:
start a full render, watch it and the rest of the job queue, stop either one
if you need to, and download the result.

What it does today: import a song by filesystem path, and the server decodes
it, registers it in a local SQLite library, and hands back a waveform, drawn
as SVG from the peaks the server computed. Open a song to see that waveform,
its detected loop region and tempo, and its separation status. Kick off stem
separation (vocals/drums/bass/other, via Demucs, with a plain-mix fallback if
you haven't installed it) and watch it progress live over server-sent events,
with the reason shown in place if it fell back or failed rather than just
going quiet. Change your mind partway through and cancel it — Demucs now runs
in a subprocess just so this can be killed cleanly, and cancelling puts the
song back to not-yet-separated with nothing partial left in the cache. Before
you start a separation (or a render) on a source file long enough to matter,
the screen says so: past roughly fifteen minutes of source audio, a line above
the button names the file's length and the fact that everything here runs on
one worker, so whatever you start behind it waits its turn.

Once a song is separated, open the mixer. Every control on it — per-stem
enable, gain, reverb send, and every decay parameter (the lowpass sweep,
spectral holes, dropouts, amplitude fade, rising noise floor, and the curve
shaping the arc between them) — is generated from a schema the config
dataclasses publish about themselves (`GET /api/schema`), so a parameter added
to the config appears here with no frontend change and nothing here can drift
from what the config actually accepts. (The example YAML `sleepmix
init-config` writes is a separate, hand-written artefact and can drift; the
mixer cannot.) Drag the progress scrubber and it plays: a small
JavaScript module fetches a preview of that point in the decay arc, decodes
it, and loops it, swapping to the new buffer at the next loop boundary rather
than cutting mid-cycle. Solo a stem to hear it alone — one at a time, since
"some of them" and "all of them" are one empty list apart in what gets sent.
Switch every stem off and it says so rather than playing something. The very
first preview of a song is slow — building the session behind it means
slicing the loop out of every stem and time-stretching each one — and the
screen says so with an indeterminate progress bar rather than inventing a
percentage it doesn't have. Every preview after that answers in well under a
second, because the built session stays warm for as long as the song stays
open.

The mixer's Render button starts a full mix as a background job — the exact
config you've been previewing, not whatever the soloed stem happens to be —
and takes you to the renders screen, where you watch it the same way
separation reports progress, cancel it if you want to, and download the
finished WAV once it's done, or delete it to reclaim the disk space (both the
database row and the file go together). A queue screen, reached from the
library's own navigation, shows everything the one background worker is
currently doing or about to do — what's running, what's waiting behind it,
what recently finished — with a Cancel button on anything still stoppable.
That screen is the answer to the incident that started this: a seventy-minute
file imported by accident, with nothing to do about it short of killing the
server by hand.

A preset bar sits above the mixer's controls: choose one from a list, Apply it
to the song you have open, name and save your own, save over an existing one,
or delete it. Applying a preset means the controls come to look like the
preset, not that it's merged into whatever you already had — a field the
preset doesn't mention goes back to its default, except the loop region you've
set for this particular song, which stays put, because a preset holds seconds
of some other recording, not this one. A song remembers which preset it last
had applied, and shows it as a line with an Apply button next to it — never
applied by itself. Opening a song's mixer starts from the same values
`sleepmix render` would use, whether or not a preset was ever involved — unless
the server's own defaults can't be fetched, in which case it opens at the
schema's bare defaults instead and says so on screen; editing a preset that
several songs have used should not be able to silently reach into any of them.

What it still doesn't do: there is no screen for browsing or managing presets
outside the mixer that's currently open, no import/export or sharing a preset
between installations, and no *estimate* of how long a render or separation
will take, only the warning above that names the source file's length.

That last one is a choice rather than an absence now. One render has been
measured end to end: a 246.6 s source at the default 20-minute output, with its
stems already separated and cached, finished in **13.6 s** wall-clock,
corroborated by a second run at 11.0 s. So rendering from warm stems is cheap,
and the expensive term is separation — which is why the warning keys on the
source file's length rather than on the length of the mix. But two runs of one
track on one machine is a measurement, not a model: nothing has been timed on a
cold cache, on a long source, or on hardware that is not this one, and a
progress bar that lies about time left is the one lie this interface is built
not to tell. So it still says what's queued and lets you watch it rather than
promising a time. `docs/architecture.md` has the figures and why the gap
between them and the cold-preview number is not a coincidence.

Ask the API directly for a preview — any single point in the decay arc, by a
`progress` value from 0 to 1 and an optional list of stems to solo — and get
raw WAV bytes back in well under a second once a song's session is warm, no
matter how far into a twenty-five-minute mix that point is; that's the same
cheap-preview property described under "The disintegration model" above, now
reachable over HTTP, and it's what the mixer itself calls on every scrubber
drag. (The *first* preview of a song is the exception: building that session
from nothing was measured at well over a minute, which is why the mixer
gates its controls behind that one request instead of pretending everything
is instant.) Start a full render as a background job, watch it the same way
as separation, cancel it if you want to, and download the finished file once
it's done. Save a set of decay settings as a named preset, rename one or save
over it in place, and fetch the server's own defaults as plain values (`GET
/api/config/default`) rather than the field-by-field shapes `/api/schema`
describes.

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

### Spacing the repeats

By default each repeat begins where the last one leaves off, which is what
every mix this program has made so far sounds like: the loop, back to back,
eroding a little more each pass. The `arrangement` block puts space between
them, and lets that space change as the mix goes on:

```yaml
arrangement:
  gap_start_s: 0.0      # space between one repeat and the next, early in the mix
  gap_end_s: 30.0       # ...and late in it
  gap_curve: linear     # linear | exp | log — how it travels between the two
```

A **positive** gap is silence between repeats: the loop breathes, arriving less
often as it dissolves, with the reverb tail of one pass bleeding into the
quiet before the next. A **negative** gap overlaps them instead — a repeat
starts before the one before it has ended, and they play over each other; past
the crossfade width (`output.cycle_crossfade_ms`) that stops being a seam and
becomes two voices deliberately stacked rather than blended into one. Both are
in seconds, bounded to −30…120, and both default to `0.0`, which reproduces the
back-to-back mix exactly.

`gap_curve` is the same `linear` / `exp` / `log` vocabulary the decay curves
use, rather than a second set of names to remember: `exp` holds the early
spacing longer and opens up late, `log` opens up quickly and then settles. It
does nothing while `gap_start_s` and `gap_end_s` are equal.

`gap_end_s` is where the spacing is heading rather than a gap you will find in
the file. The spacing is sized from how far into the mix each repeat starts,
and the last repeat starts before the end, so the widest gap actually laid down
falls a little short — a 20-minute mix off a 6.7-second loop with
`gap_end_s: 30` gets to about 28.9 seconds. How short depends on how many
repeats fit; ask for a wider end gap if you want a specific one.

See `sleepmix/config.example.yaml` for every field with comments.

## The night stream

`sleepmix render` makes a file. `sleepmix night` doesn't — it plays a live
ambient stream that gets quieter and sparser as the night goes on, settles
near silence toward sunrise, and then stops.

```bash
pip install "sleepmix[night]"
sleepmix night
```

There is one button and no config screen, on purpose. The only configuration
that exists is three environment variables:

- `SLEEPMIX_LAT`, `SLEEPMIX_LON` — where you are, so the night can size itself
  against how long it's actually dark (defaults to Amsterdam).
- `SLEEPMIX_RADIO_URL` — a live HTTP audio stream to mix in as a distant,
  intermittent voice, if you want one.

Drop a comfort show — anything you already own, `.wav`/`.flac`/`.mp3`/`.m4a`/
`.ogg`/`.aif`/`.aiff` — into the `room` folder under your data directory (the
path is printed when you start a night) and it plays continuously and
quietly, as if it were on through a wall. Neither source is required; without
them you get music alone.

### Bring your own music

The music itself doesn't have to be synthesized. Drop songs — the same file
types as above — into the `sources` folder next to `room`, then run:

```bash
sleepmix prepare
```

whenever it suits you. `prepare` is the slow part — it separates each song,
finds a short loop in it and analyses what it's made of, and on a laptop that
means the fans spinning up for a few minutes per song. That cost is why it's
its own command: it never runs at bedtime, and `sleepmix night` never
triggers it — the night only ever reads what `prepare` has already produced.
Run it in the afternoon, run it before you leave for work, run it however far
ahead of sleep you like.

What it buys: a prepared song gets loops of itself early in the night, giving
way to drones built from that song's own spectrum as the hours pass, so the
real recording dissolves into its own double rather than a generic pad. A
sources folder with nothing prepared in it is not an error — `sleepmix night`
says so on the screen and plays a night of pure synthesis instead, exactly as
if the folder were never there.

`sleepmix night` takes no other arguments. It ends by ending: the length of
the night is worked out from your coordinates when you press start, the stream
descends across exactly that long, and then playback stops. There's no alarm
and no wake-up ramp, because there's no config to tell it when you're getting
up — and a system that guesses when you're getting up and is wrong is worse
than one that doesn't try. Ctrl-C still stops it sooner. `--seconds N` exists
so you can hear what it sounds like without staying up for it, and overrides
the night's own length.

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
