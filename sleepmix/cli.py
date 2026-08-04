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
    read (see the `ui` command's guard)."""
    import ipaddress

    if host in ("localhost", ""):
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
    from .server.app import create_app

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
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
