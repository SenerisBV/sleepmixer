"""Command-line interface: ``sleepmix render`` / ``sleepmix init-config``."""
from __future__ import annotations

import click

from .config import MixConfig
from .pipeline import run_pipeline


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
    run_pipeline(input_path, cfg, output_path, progress=click.echo)


@main.command("init-config")
@click.option("--output", "output_path", default="sleepmix.yaml", type=click.Path())
def init_config(output_path):
    """Write a fully-commented example config to OUTPUT."""
    import importlib.resources as res

    text = res.files("sleepmix").joinpath("config.example.yaml").read_text()
    with open(output_path, "w") as fh:
        fh.write(text)
    click.echo(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
