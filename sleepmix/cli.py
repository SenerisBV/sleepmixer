"""Command-line interface: ``sleepmix render`` / ``sleepmix init-config``."""
from __future__ import annotations

import click

from .config import MixConfig
from .pipeline import run_pipeline
from .progress import ProgressReporter, echo_sink


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
@click.option("--host", default="127.0.0.1", help="Interface to bind.")
@click.option("--port", default=8765, type=int, help="Port to bind.")
@click.option("--open/--no-open", "open_browser", default=True,
              help="Open a browser tab on start.")
def ui(host, port, open_browser):
    """Start the local web UI."""
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "The UI needs extra dependencies. Install them with:\n"
            "    pip install \"sleepmix[ui]\""
        )
    from .server.app import create_app

    if open_browser:
        import threading
        import webbrowser

        threading.Timer(
            1.0, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
