"""`sleepmix esoterica`: estimate, audition and voice (the cost-guarded commands).

Every command that could call a voicing API first prints the characters and
estimated cost per provider, and spends only with `--yes`. Without it, it makes
no synthesize call, reads no key, and exits 0.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import click
import requests

from .env import api_key
from .providers import Cartesia, ElevenLabs, ProviderError
from .script import SHOWS, Passage, Script, load_all
from .voicing import (
    MissingRawError, StaleTakesError, Voice, VoiceMismatchError, VoicesConfig, billed_chars,
    check_distinct_voices, check_resume_voice, check_takes, load_voices,
    raw_passage_file, raw_takes, recording_pieces, revoice_files,
    render_recording, shuffle_billed_chars, shuffle_lines, shuffle_rng, split_sentences,
    uncached_chars, voice_passage, voice_recording, voice_shuffle, voice_slot, write_backfill,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "esoterica" / "scripts"
VOICES = REPO / "esoterica" / "voices.yaml"
LIBRARY = REPO / "esoterica" / "library"
AUDITION = REPO / "esoterica" / "audition"
ENV = REPO / ".env"

PROVIDERS = {"elevenlabs": ElevenLabs, "cartesia": Cartesia}
KEYS = {"elevenlabs": "ELEVENLABS_API_KEY", "cartesia": "CARTESIA_API_KEY"}

AUDITION_WORDS = 120          # PLACEHOLDER: ~45-60 s at a slow pace
AUDITION_SHUFFLE_LINES = 16   # PLACEHOLDER: ~16 images x (1 s + 2.5 s gap) ~ 55 s
_CUE = re.compile(r"\[[^\]\n]*\]")


def make_provider(name: str, cfg: dict, env_path: Path):
    """Build a real provider. Reads the key only now, i.e. only with --yes."""
    try:
        key = api_key(KEYS[name], env_path)
    except KeyError:
        raise click.ClickException(
            f"{KEYS[name]} is not set (environment or {env_path})") from None
    p = PROVIDERS[name](key, requests.Session(), settings=cfg.get("settings"))
    p.max_chars = int(cfg["max_chars"])
    return p


def _build_providers(names, cfg: VoicesConfig, env_path: Path) -> dict:
    """Every provider a run needs, built (keys resolved) before the first
    request, so a missing second key fails while nothing has been spent."""
    return {n: make_provider(n, cfg.providers[n], env_path) for n in sorted(set(names))}


# --- billed characters (what each provider is actually sent; no key needed) ----
# The one estimator: the exact pieces voicing sends (chunked to the provider's
# max_chars, `[long pause]` never sent), each counted after cue translation.

def _max_chars(cfg: VoicesConfig, provider: str) -> int:
    return int(cfg.providers[provider]["max_chars"])


def passage_chars(script: Script, p: Passage, provider: str, cfg: VoicesConfig) -> int:
    t = PROVIDERS[provider].translate_cues
    return sum(len(t(pc.text))
               for pc in recording_pieces(script, p, _max_chars(cfg, provider), t))


def excerpt_chars(excerpt, provider: str, cfg: VoicesConfig) -> int:
    t = PROVIDERS[provider].translate_cues
    if isinstance(excerpt, list):
        return shuffle_billed_chars(excerpt, t)
    return billed_chars(excerpt, t, _max_chars(cfg, provider))


def _common(f):
    f = click.option("--env", "env_path", type=click.Path(path_type=Path), default=ENV,
                     show_default=True, help="The .env holding the API keys.")(f)
    f = click.option("--voices", "voices_path", type=click.Path(path_type=Path),
                     default=VOICES, show_default=True)(f)
    f = click.option("--scripts", "scripts_root", type=click.Path(path_type=Path),
                     default=SCRIPTS, show_default=True)(f)
    return f


def _load(scripts_root: Path, voices_path: Path) -> tuple[list[Script], VoicesConfig]:
    try:
        scripts = load_all(scripts_root)
        cfg = load_voices(voices_path)
        check_distinct_voices(cfg.chosen, scripts)
    except (ValueError, OSError) as e:
        raise click.ClickException(str(e)) from None
    return scripts, cfg


def _cost_lines(chars: dict[str, int], cfg: VoicesConfig) -> list[str]:
    lines = []
    for name in chars:
        p = cfg.providers[name]
        n = chars[name]
        credits = n * float(p.get("credits_per_char", 1.0))
        usd = n * float(p["price_per_char"])
        note = "" if name != "cartesia" else "  (USD rate unverified; docs give credits only)"
        lines.append(f"  {name:<11} {p['model']:<11} {n:>9,} characters  "
                     f"~{credits:,.0f} credits  ~${usd:,.2f}{note}")
    return lines


def _no_spend_note() -> None:
    click.echo("\nNothing was voiced and nothing was spent: re-run with --yes to spend.")


@click.group("esoterica")
def esoterica() -> None:
    """Voice the Esoterica scripts (ElevenLabs / Cartesia), cost-guarded."""


@esoterica.command()
@_common
def estimate(scripts_root, voices_path, env_path):
    """Characters and estimated cost of voicing every script, per provider."""
    scripts, cfg = _load(scripts_root, voices_path)
    names = list(cfg.providers)
    click.echo(f"{len(scripts)} scripts (characters sent, after cue translation):")
    click.echo(f"  {'':<24} " + " ".join(f"{n:>11}" for n in names))
    chars = {n: 0 for n in names}
    for s in scripts:
        row = {n: sum(passage_chars(s, p, n, cfg) for p in s.passages) for n in names}
        for n in names:
            chars[n] += row[n]
        click.echo(f"  {s.id:<24} " + " ".join(f"{row[n]:>11,}" for n in names))
    click.echo("\nAll scripts, per provider:")
    for line in _cost_lines(chars, cfg):
        click.echo(line)


# --- voice ----------------------------------------------------------------------

def _remaining(script: Script, library: Path, voice: Voice, cfg: VoicesConfig,
               revoice: frozenset[int] = frozenset()) -> int:
    """Characters still to pay for: passages with no raw take (or named by
    --revoice), minus any of their pieces already cached for the current text
    by an earlier, interrupted run."""
    d = Path(library) / script.id
    t = PROVIDERS[voice.provider].translate_cues
    mc = _max_chars(cfg, voice.provider)
    return sum(uncached_chars(recording_pieces(script, p, mc, t),
                              d / raw_passage_file(p.index), voice, t,
                              redo=p.index in revoice)
               for p in script.passages)


_PNN = re.compile(r"^p?(\d{1,3})$")


def _parse_revoice(values: tuple[str, ...]) -> list[str]:
    """('p02', '3', 'p04,p05') -> ['p02', 'p03', 'p04', 'p05']."""
    out = []
    for v in values:
        for item in filter(None, (x.strip() for x in v.split(","))):
            m = _PNN.match(item.lower())
            if not m or int(m[1]) < 1:
                raise click.UsageError(f"--revoice takes passage names like p02, not '{item}'")
            out.append(f"p{int(m[1]):02d}")
    return sorted(set(out))


@esoterica.command()
@click.argument("script_id", required=False)
@click.option("--all", "all_", is_flag=True, help="Every script.")
@click.option("--revoice", "revoice_", multiple=True, metavar="pNN",
              help="Re-voice a stale passage (repeatable, or comma-separated). Its raw "
                   "take is deleted only with --yes, after the estimate. One script id only.")
@click.option("--yes", is_flag=True, help="Actually call the provider and spend.")
@click.option("--library", type=click.Path(path_type=Path), default=LIBRARY,
              show_default=True)
@_common
def voice(script_id, all_, revoice_, yes, library, scripts_root, voices_path, env_path):
    """Voice SCRIPT_ID (or --all) with the slot's chosen voice from voices.yaml."""
    if bool(script_id) == bool(all_):
        raise click.UsageError("give one script id or --all")
    if revoice_ and not script_id:
        raise click.UsageError("--revoice needs one script id, not --all")
    named = _parse_revoice(revoice_)
    scripts, cfg = _load(scripts_root, voices_path)
    if script_id:
        scripts = [s for s in scripts if s.id == script_id]
        if not scripts:
            raise click.ClickException(f"no script with id '{script_id}'")
    missing = sorted({voice_slot(s) for s in scripts if cfg.voice_for(voice_slot(s)) is None})
    if missing:
        raise click.ClickException(
            "no chosen voice in voices.yaml `chosen:` for slot(s): " + ", ".join(missing)
            + " (pick them at STOP 2 first)")
    try:
        for s in scripts:
            check_resume_voice(s, cfg.voice_for(voice_slot(s)), library)
    except (VoiceMismatchError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    # stale-script guard: nothing is spent (or deleted) while a take no longer
    # matches its script, unless every stale take is named with --revoice
    for s in scripts:
        stale, _ = check_takes(s, library)
        if named:
            not_stale = [n for n in named if n not in stale]
            if not_stale:
                raise click.ClickException(
                    f"{s.id}: {', '.join(not_stale)} not stale (its take matches the "
                    "script); --revoice only replaces stale takes. To re-voice a good "
                    "take anyway, delete its pNN.raw.wav and pNN.raw.json yourself.")
            stale = {n: w for n, w in stale.items() if n not in named}
        if stale:
            raise click.ClickException(str(StaleTakesError(s.id, stale)))
    redo = frozenset(int(n[1:]) - 1 for n in named)
    doomed = [f for n in named for f in revoice_files(library / scripts[0].id, n)] \
        if named else []
    chars: dict[str, int] = {}
    for s in scripts:
        v = cfg.voice_for(voice_slot(s))
        chars[v.provider] = chars.get(v.provider, 0) + _remaining(s, library, v, cfg, redo)
    click.echo(f"Voicing {len(scripts)} recording(s) into {library} "
               "(passages and pieces already on disk are skipped and not counted):")
    for line in _cost_lines(chars, cfg):
        click.echo(line)
    if doomed:
        click.echo("--revoice deletes (with --yes): "
                   + ", ".join(f.name for f in doomed))
    if not yes:
        _no_spend_note()
        return
    providers = _build_providers((cfg.voice_for(voice_slot(s)).provider for s in scripts),
                                 cfg, env_path)
    if named:
        s = scripts[0]
        d = library / s.id
        # the takes that stay keep their proof of text: backfill their sidecars
        # from the manifest before the manifest (which describes the old takes) goes
        try:
            write_backfill(s, library, check_takes(s, library)[1])
        except StaleTakesError as e:
            raise click.ClickException(str(e)) from None
        for f in doomed:
            f.unlink(missing_ok=True)
        (d / "recording.json").unlink(missing_ok=True)  # describes the old takes
        click.echo(f"  {s.id}: deleted {', '.join(f.name for f in doomed)}")
    failed = []
    for s in scripts:
        v = cfg.voice_for(voice_slot(s))
        try:
            m = voice_recording(s, providers[v.provider], v, library,
                                on_error=lambda msg: click.echo(f"  failed: {msg}", err=True))
        except (StaleTakesError, VoiceMismatchError) as e:
            raise click.ClickException(str(e)) from None
        if m is None:
            failed.append(s.id)
        else:
            total = sum(e.duration_s for e in m.passages)
            click.echo(f"  {s.id}: {len(m.passages)} passages, {total / 60:.1f} min")
    if failed:
        click.echo(f"{len(failed)} recording(s) incomplete: {', '.join(failed)}. "
                   "Re-run to finish; finished passages and paid pieces are kept.", err=True)
        raise SystemExit(1)


# --- render (free) --------------------------------------------------------------

@esoterica.command()
@click.argument("script_id", required=False)
@click.option("--all", "all_", is_flag=True, help="Every script.")
@click.option("--library", type=click.Path(path_type=Path), default=LIBRARY,
              show_default=True)
@click.option("--scripts", "scripts_root", type=click.Path(path_type=Path),
              default=SCRIPTS, show_default=True)
def render(script_id, all_, library, scripts_root):
    """Re-render source character from the raw takes. Free: no provider, no key.

    With --all, recordings with no raw takes, or only some, are skipped; one
    whose script changed since voicing is refused (exit 1 at the end)."""
    if bool(script_id) == bool(all_):
        raise click.UsageError("give one script id or --all")
    try:
        scripts = load_all(scripts_root)
    except (ValueError, OSError) as e:
        raise click.ClickException(str(e)) from None
    if script_id:
        scripts = [s for s in scripts if s.id == script_id]
        if not scripts:
            raise click.ClickException(f"no script with id '{script_id}'")
    refused = []
    for s in scripts:
        if all_ and not raw_takes(Path(library) / s.id):
            click.echo(f"  {s.id}: skipped, not voiced")  # --all only; a named id still fails
            continue
        try:
            m = render_recording(s, library)
        except MissingRawError as e:
            if not all_:
                raise click.ClickException(str(e)) from None
            click.echo(f"  {s.id}: skipped, partially voiced (missing {', '.join(e.missing)})")
            continue
        except StaleTakesError as e:
            if not all_:
                raise click.ClickException(str(e)) from None
            click.echo(f"  refused: {e}", err=True)
            refused.append(s.id)
            continue
        except (FileNotFoundError, ValueError) as e:
            raise click.ClickException(str(e)) from None
        click.echo(f"  {s.id}: {len(m.passages)} passages rendered ({m.source_character})")
    if refused:
        click.echo(f"{len(refused)} recording(s) not rendered, their script changed since "
                   f"voicing: {', '.join(refused)}", err=True)
        raise SystemExit(1)


# --- audition -------------------------------------------------------------------

def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def audition_excerpt(script: Script) -> str | list[str]:
    """About AUDITION_WORDS spoken words from the first passage, cut at a
    sentence end (shuffles: the first AUDITION_SHUFFLE_LINES images)."""
    first = script.passages[0]
    if script.show == "shuffles":
        return shuffle_lines(first.text)[:AUDITION_SHUFFLE_LINES]
    taken, words = [], 0
    for sent in split_sentences(first.text):
        if not sent.strip():
            continue
        taken.append(sent.strip())
        words += len(_CUE.sub("", sent).split())
        if words >= AUDITION_WORDS:
            break
    return " ".join(taken)


def _slots(scripts: list[Script]) -> dict[str, Script]:
    """Slot -> the first script (by id) in it."""
    out: dict[str, Script] = {}
    for s in sorted(scripts, key=lambda s: s.id):
        out.setdefault(voice_slot(s), s)
    return dict(sorted(out.items()))


def _write_index(out_dir: Path, every: dict[str, Script], cfg: VoicesConfig) -> Path:
    """List every slot that has audition files on disk (not just this run's)."""
    import soundfile as sf

    lines = ["# Esoterica audition", "",
             "One excerpt per voice slot (the first script in the slot, first passage), "
             "voiced by each candidate. Files are mono float32 44.1 kHz, normalised to "
             "-24 dBFS RMS over speech, peaks at most -3 dBFS.", ""]
    for slot, s in every.items():
        if not (out_dir / slot).is_dir() or not any((out_dir / slot).glob("*.wav")):
            continue
        lines += [f"## {slot}", "",
                  f"- Script: `{s.show}/{s.id}.md`",
                  f"- Voice profile: {s.voice_profile or '(none)'}", ""]
        lines += ["| Provider | Voice | File | Duration | Why |", "|---|---|---|---|---|"]
        for prov, cands in cfg.candidates.get(slot, {}).items():
            for c in cands:
                f = out_dir / slot / f"{prov}-{slug(c['name'])}.wav"
                dur = (f"{sf.info(str(f)).duration:.1f} s" if f.exists() else "missing")
                lines.append(f"| {prov} | {c['name']} | `{slot}/{f.name}` | {dur} | "
                             f"{c['why']} |")
        lines.append("")
    path = out_dir / "index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@esoterica.command()
@click.option("--slot", help="One voice slot (a show, or a testimony/address id).")
@click.option("--show", type=click.Choice(sorted(SHOWS)), help="Every slot of a show.")
@click.option("--all", "all_", is_flag=True, help="Every slot.")
@click.option("--yes", is_flag=True, help="Actually call the providers and spend.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=AUDITION,
              show_default=True)
@_common
def audition(slot, show, all_, yes, out_dir, scripts_root, voices_path, env_path):
    """Voice a ~120-word excerpt per slot with every candidate voice."""
    if sum(map(bool, (slot, show, all_))) != 1:
        raise click.UsageError("give exactly one of --slot, --show or --all")
    scripts, cfg = _load(scripts_root, voices_path)
    every = _slots(scripts)
    if slot:
        if slot not in every:
            raise click.ClickException(f"unknown slot '{slot}' (slots: {', '.join(every)})")
        chosen = {slot: every[slot]}
    elif show:
        chosen = {k: s for k, s in every.items() if s.show == show}
    else:
        chosen = every
    missing = [k for k in chosen if k not in cfg.candidates]
    if missing:
        raise click.ClickException(f"no candidates in voices.yaml for: {', '.join(missing)}")

    jobs = []  # (slot, script, provider, candidate, out, excerpt)
    chars: dict[str, int] = {n: 0 for n in cfg.providers}
    click.echo(f"Audition into {out_dir} (files already on disk are skipped and not counted):")
    for k, s in chosen.items():
        excerpt = audition_excerpt(s)
        per = {prov: excerpt_chars(excerpt, prov, cfg) for prov in cfg.candidates[k]}
        for prov, cands in cfg.candidates[k].items():
            for c in cands:
                out = out_dir / k / f"{prov}-{slug(c['name'])}.wav"
                if not out.exists():
                    chars[prov] += per[prov]
                    jobs.append((k, s, prov, c, out, excerpt))
        click.echo(f"  {k:<20} {s.id:<24} "
                   + ", ".join(f"{prov} {n:,} x {len(cfg.candidates[k][prov])}"
                               for prov, n in per.items()) + " characters")
    click.echo("\nPer provider:")
    for line in _cost_lines(chars, cfg):
        click.echo(line)
    if not yes:
        _no_spend_note()
        return

    providers = _build_providers((j[2] for j in jobs), cfg, env_path)
    failed = []
    try:
        for k, s, prov, c, out, excerpt in jobs:
            v = Voice(prov, cfg.providers[prov]["model"], c["voice_id"])
            try:
                if isinstance(excerpt, list):
                    voice_shuffle(providers[prov], excerpt, v, s.language, out,
                                  shuffle_rng(s.id, 0))
                else:
                    voice_passage(providers[prov], excerpt, v, s.language, out)
                click.echo(f"  wrote {out.relative_to(out_dir)}")
            except ProviderError as e:
                failed.append(f"{k}/{prov}-{slug(c['name'])}")
                click.echo(f"  failed: {k} {prov} {c['name']}: {e}", err=True)
    finally:
        # Whatever happened, list what is on disk now.
        if out_dir.is_dir():
            click.echo(f"Index: {_write_index(out_dir, every, cfg)}")
    if failed:
        click.echo(f"{len(failed)} audition file(s) failed: {', '.join(failed)}. "
                   "Re-run to retry; finished files are kept.", err=True)
        raise SystemExit(1)
