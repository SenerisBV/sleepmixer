"""End-to-end render: song file -> extended, disintegrating sleep mix.

Stages: separate -> find a shared beat-aligned loop -> per stem (seamless loop,
slow/pitch, disintegrate, reverb) -> sum -> sound bed -> master. Loop points are
found once on the full mix and applied to every stem so they stay phase-aligned.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .analysis import find_loop, slice_loop
from .audio import AudioBuffer, normalize_peak, resample, save_audio, silence
from .config import MixConfig, StemConfig
from .disintegration import build_disintegrating_stream
from .effects import apply_reverb
from .looping import make_seamless
from .paths import cache_dir
from .separation import separate
from .soundbed import build_soundbed
from .timestretch import slow_and_pitch
from .util import db_to_amp

Progress = Callable[[str], None]


def run_pipeline(
    input_path: str,
    config: MixConfig,
    output_path: str,
    progress: Progress = print,
) -> AudioBuffer:
    rng = np.random.default_rng(config.seed)

    progress("Separating stems…")
    stems = separate(input_path, config.separation_model, cache_dir=str(cache_dir()))
    work_sr = next(iter(stems.values())).sr

    progress("Finding loop points…")
    reference = _sum_buffers(list(stems.values()))
    loop_point = find_loop(reference, config.loop)
    progress(f"  tempo≈{loop_point.tempo:.0f} BPM, "
             f"loop={ (loop_point.end-loop_point.start)/work_sr:.1f}s")

    target_frames = int(config.output.duration_min * 60 * work_sr)
    jobs = _plan_jobs(stems, config)

    mix = silence(target_frames, config.output.channels, work_sr)
    for buf, sc in jobs:
        progress(f"Processing stem '{sc.name}'…")
        stream = _process_stem(buf, sc, loop_point, config, target_frames)
        mix = _add(mix, stream)

    if config.soundbed.enabled:
        progress("Adding sound bed…")
        bed = build_soundbed(target_frames / work_sr, work_sr, config.soundbed, rng)
        mix = _add(mix, bed.with_channels(config.output.channels))

    progress("Mastering…")
    if mix.sr != config.output.sample_rate:
        mix = resample(mix, config.output.sample_rate)
    mix = _apply_fades(mix, config.output.fade_in_s, config.output.fade_out_s)
    mix = normalize_peak(mix, config.output.peak_db)

    save_audio(mix, output_path)
    progress(f"Wrote {output_path} ({mix.duration/60:.1f} min)")
    return mix


def _process_stem(
    buf: AudioBuffer,
    sc: StemConfig,
    loop_point,
    config: MixConfig,
    target_frames: int,
) -> AudioBuffer:
    loop = slice_loop(buf, loop_point)
    loop = make_seamless(loop, config.loop.crossfade_ms)
    loop = slow_and_pitch(loop, config.tempo.speed, config.tempo.pitch_semitones)
    stream = build_disintegrating_stream(
        loop, target_frames, sc.decay, config.output.cycle_crossfade_ms,
        config.seed, sc.name)
    stream = apply_reverb(stream, config.reverb, wet_scale=sc.reverb_send)
    if abs(sc.gain_db) > 1e-6:
        stream = AudioBuffer(stream.data * db_to_amp(sc.gain_db), stream.sr)
    return stream.with_channels(config.output.channels)


def _plan_jobs(stems: dict[str, AudioBuffer], config: MixConfig) -> list[tuple[AudioBuffer, StemConfig]]:
    """Match configured stems to the stems we actually have.

    Falls back to processing whatever stems exist (e.g. a single 'mix' stem when
    Demucs is unavailable) with default decay settings."""
    jobs = [
        (stems[sc.name], sc)
        for sc in config.stems
        if sc.enabled and sc.name in stems
    ]
    if not jobs:
        jobs = [(buf, StemConfig(name=name)) for name, buf in stems.items()]
    return jobs


# -- buffer math --------------------------------------------------------
def _sum_buffers(buffers: list[AudioBuffer]) -> AudioBuffer:
    n = max(b.n_frames for b in buffers)
    ch = max(b.n_channels for b in buffers)
    sr = buffers[0].sr
    acc = np.zeros((n, ch), dtype=np.float32)
    for b in buffers:
        acc = _accumulate(acc, b.with_channels(ch).data)
    return AudioBuffer(acc, sr)


def _add(base: AudioBuffer, other: AudioBuffer) -> AudioBuffer:
    ch = base.n_channels
    return AudioBuffer(_accumulate(base.data.copy(), other.with_channels(ch).data), base.sr)


def _accumulate(acc: np.ndarray, x: np.ndarray) -> np.ndarray:
    m = min(acc.shape[0], x.shape[0])
    acc[:m] += x[:m]
    return acc


def _apply_fades(buf: AudioBuffer, fade_in_s: float, fade_out_s: float) -> AudioBuffer:
    x = buf.data.copy()
    sr = buf.sr
    fi = min(int(fade_in_s * sr), x.shape[0])
    fo = min(int(fade_out_s * sr), x.shape[0])
    if fi > 0:
        x[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)[:, None]
    if fo > 0:
        x[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)[:, None]
    return AudioBuffer(x, sr)
