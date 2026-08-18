"""Command-line interface: ``sleepmix render`` / ``sleepmix init-config`` /
``sleepmix ui``.
"""
from __future__ import annotations

import click

from .config import MixConfig
from .pipeline import run_pipeline
from .progress import ProgressReporter, echo_sink


def _is_loopback(host: str) -> bool:
    """True for any spelling of localhost.

    A string set gets this wrong: `::1`, `0:0:0:0:0:0:0:1` and `127.0.0.2` are
    all loopback and all miss a naive allow-list. Binding anywhere else exposes
    an unauthenticated server that will read any audio file the process can
    read (see the `ui` command's guard).

    `""` is deliberately *not* treated as loopback, even though it's the odd
    one out here: passed to uvicorn it means "bind every interface," exactly
    like `0.0.0.0`/`::` — this file's own browser-URL logic below already
    treats it that way. Accepting it here would let `--host ""` skip the
    refusal entirely while still binding a wildcard interface."""
    import ipaddress

    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


@click.group()
@click.version_option()
def main() -> None:
    """Turn a song into an extended, disintegrating ambient sleep mix."""


@main.command()
@click.option("--input", "input_path", required=True, type=click.Path(exists=True),
              help="Source song (wav/flac/mp3/…).")
@click.option("--output", "output_path", default="sleepmix.wav",
              type=click.Path(), help="Output file.")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True),
              help="YAML config (see init-config). Defaults are used if omitted.")
@click.option("--duration", type=float, default=None,
              help="Override output duration in minutes.")
@click.option("--speed", type=float, default=None,
              help="Override playback speed (0.7 = 70%).")
@click.option("--seed", type=int, default=None, help="Override random seed.")
@click.option("--soundbed/--no-soundbed", default=None,
              help="Force the binaural/noise sound bed on or off.")
def render(input_path, output_path, config_path, duration, speed, seed, soundbed):
    """Render a sleep mix from INPUT."""
    cfg = MixConfig.from_yaml(config_path) if config_path else MixConfig()
    if duration is not None:
        cfg.output.duration_min = duration
    if speed is not None:
        cfg.tempo.speed = speed
    if seed is not None:
        cfg.seed = seed
    if soundbed is not None:
        cfg.soundbed.enabled = soundbed
    run_pipeline(input_path, cfg, output_path,
                 reporter=ProgressReporter(echo_sink(click.echo)))


@main.command("init-config")
@click.option("--output", "output_path", default="sleepmix.yaml", type=click.Path())
def init_config(output_path):
    """Write a fully-commented example config to OUTPUT."""
    import importlib.resources as res

    text = res.files("sleepmix").joinpath("config.example.yaml").read_text()
    with open(output_path, "w") as fh:
        fh.write(text)
    click.echo(f"Wrote {output_path}")


@main.command()
@click.option("--host", default="127.0.0.1",
              help="Interface to bind. Localhost only unless --allow-remote.")
@click.option("--port", default=8765, type=int, help="Port to bind.")
@click.option("--open/--no-open", "open_browser", default=True,
              help="Open a browser tab on start.")
@click.option("--allow-remote", is_flag=True, default=False,
              help="Permit binding a non-loopback interface. Read the warning "
                   "--host prints before using this.")
def ui(host, port, open_browser, allow_remote):
    """Start the local web UI."""
    # Checked before anything is imported or bound: refusing has to happen
    # while there is still nothing listening.
    if not _is_loopback(host) and not allow_remote:
        raise SystemExit(
            f"Refusing to bind {host}: that is not a loopback address.\n"
            "\n"
            "This server has no authentication, and importing a song takes an\n"
            "arbitrary filesystem path — so anyone who can reach the port can\n"
            "ask it to read any audio file this process can read, and pull a\n"
            "detailed waveform of it back out. On loopback that is just you.\n"
            "On a shared network it is everyone on it.\n"
            "\n"
            "Use --host 127.0.0.1 (the default), or pass --allow-remote if you\n"
            "genuinely mean it and the network is one you trust."
        )
    try:
        import uvicorn
    except ImportError:
        # `from None`: the ImportError traceback is noise here — the whole
        # point of this branch is a clean, actionable message.
        raise SystemExit(
            "The UI needs extra dependencies. Install them with:\n"
            "    pip install \"sleepmix[ui]\""
        ) from None
    from .server.app import DEFAULT_ALLOWED_HOSTS, create_app

    # A `Host` allow-list, so a rebound page cannot drive this API. The bound
    # host joins the loopback defaults because `--allow-remote` binds
    # elsewhere on purpose and would otherwise reject every request it
    # received; a wildcard bind cannot name its own reachable hosts, so it
    # opts out rather than silently allowing one arbitrary spelling.
    allowed = list(DEFAULT_ALLOWED_HOSTS)
    if host in {"0.0.0.0", "::", ""}:
        allowed = ["*"]
    elif host not in allowed:
        allowed.append(host.strip("[]"))

    if open_browser:
        import threading
        import webbrowser

        # A wildcard bind is not a reachable URL. 0.0.0.0 means "every
        # interface"; the browser needs one you can actually connect to.
        browse_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
        if ":" in browse_host:  # bare IPv6 literals need brackets in a URL
            browse_host = f"[{browse_host}]"
        url = f"http://{browse_host}:{port}/"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(allowed_hosts=allowed), host=host, port=port,
                log_level="info")


@main.command()
@click.option("--seconds", type=int, default=None,
              help="Stop after this many seconds instead of at the end of the "
                   "night. For trying it out; a real night takes no arguments "
                   "at all.")
def night(seconds: int | None) -> None:
    """Play a self-quieting ambient stream until the night it was built for
    runs out.

    Deliberately takes no configuration. Location comes from SLEEPMIX_LAT and
    SLEEPMIX_LON (defaulting to Amsterdam), a comfort show comes from whatever
    is in the `room` folder under the data directory, and a radio feed comes
    from SLEEPMIX_RADIO_URL if one is set. Everything else is derived from the
    sky, the weather, and a seed.
    """
    import datetime as dt
    import math
    import os
    import random

    # The device check goes first, before anything is printed. Printing "Night
    # 12345: 9.2 h until light." and where the room folder is and *then*
    # refusing to start reads as encouragement followed by a slap; a user
    # without the extra should see only the one line that tells them what to
    # install.
    try:
        import sounddevice as sd
    except Exception:
        raise click.ClickException(
            'sounddevice is not installed — run: pip install "sleepmix[night]"')

    from .config import SoundbedConfig
    from .night.context import build_context
    from .night.player import NightPlayer, room_directory
    from .night.sources import load_profiles, sources_directory
    from .night.speech import radio_source_from, room_sources_from
    from .night.stream import BLOCK_S, NightStream

    lat = float(os.environ.get("SLEEPMIX_LAT", "52.3676"))
    lon = float(os.environ.get("SLEEPMIX_LON", "4.9041"))
    seed = int(os.environ.get("SLEEPMIX_SEED", random.randrange(2 ** 31)))
    sr = 44100

    profiles = load_profiles()
    ctx = build_context(dt.datetime.now(dt.timezone.utc), lat, lon, seed,
                        sources=profiles)
    # The bed is on for a night, and only for a night — ``SoundbedConfig``'s
    # own default stays off, because every other caller (render, preview) has
    # a mix underneath it and this one does not. A night is mostly gaps: at
    # 6.5 h in, voice coverage measured 26 of 30 consecutive blocks as exact
    # digital silence, with gaps up to 694 s. The bed is what is *there*
    # between voices, and it is also the only thing the "cloud and rain → the
    # noise bed's level and character" steering row has to act on.
    stream = NightStream(ctx, sr=sr, bed=SoundbedConfig(enabled=True))
    player = NightPlayer(
        stream,
        room_sources_from(room_directory(), sr),
        radio_source_from(os.environ.get("SLEEPMIX_RADIO_URL"), sr),
    )

    click.echo(f"Night {seed}: {ctx.night_length_s / 3600:.1f} h until light.")
    click.echo(f"Room audio: {room_directory()}")
    click.echo("Ends on its own at first light. Ctrl-C to stop it sooner.")
    if profiles:
        loops = sum(len(p.loop_paths) for p in profiles)
        click.echo(f"Material: {len(profiles)} source(s), {loops} loop(s).")
    else:
        click.echo(f"Material: synthesis only — nothing prepared yet. "
                   f"Drop audio in {sources_directory()} and run "
                   f"`sleepmix prepare`.")

    # **The night ends by ending.** The design spec is plain about it — "Phase
    # 1 descends toward near-silence over an assumed night and stops" — and it
    # argues the case: with no configuration there is no alarm time, so "a
    # system that guesses when you are getting up and is wrong is worse than
    # one that does not try". What shipped did neither: with no ``--seconds``
    # the loop ran forever and the only way out was Ctrl-C, which is a third
    # behaviour nobody chose. The night's own length is the one number that
    # says when it is over, so that is what bounds it.
    #
    # This is about the stream terminating, not about the sound. ``arc_at``
    # clamps time past the end of the night to the arc's quietest values, so a
    # block or two of overrun degrades nothing — which is why rounding up is
    # safe and rounding down would clip the last of the descent.
    if seconds is not None:
        max_blocks = int(seconds / BLOCK_S)
    else:
        max_blocks = int(math.ceil(ctx.night_length_s / BLOCK_S))
    with sd.OutputStream(samplerate=sr, channels=2, dtype="float32") as out:
        try:
            player.run(max_blocks=max_blocks, sink=lambda b: out.write(b.data))
        except (KeyboardInterrupt, Exception):
            # A night that ends should end silently, not with a stack trace.
            # ``run`` itself already degrades everything degradable; this is
            # the last-resort catch for whatever it could not — Ctrl-C, or a
            # sink failure that outlasted the retry budget inside ``run``.
            pass


@main.command()
def prepare() -> None:
    """Prepare source material for `sleepmix night`.

    Separates, finds loops and analyses everything in the sources folder. This
    is the slow part — minutes per song, with the fans on — and it lives in its
    own command precisely so that it never happens at bedtime.
    """
    from .night.prepare import prepare_all
    from .night.sources import sources_directory

    click.echo(f"Sources: {sources_directory()}")
    profiles = prepare_all(progress=click.echo)
    if not profiles:
        click.echo("Nothing prepared. Drop audio files in the folder above.")
        return
    total = sum(len(p.loop_paths) for p in profiles)
    click.echo(f"Ready: {len(profiles)} source(s), {total} loop(s).")


if __name__ == "__main__":
    main()
