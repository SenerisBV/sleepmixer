"""A room heard through a wall.

The thing being built here is not "quiet dialogue" — it is the sound of a TV
on in the living room while you fall asleep on the couch. The tests below
mostly check that the treatment removes what makes speech followable, because
that is the property the whole design turns on: intelligible speech at 3 AM is
the failure mode of the project.
"""
import numpy as np
import pytest
import soundfile as sf

from sleepmix.audio import AudioBuffer
from sleepmix.night.speech import (
    RoomSource, SilentSource, room_sources_from, through_a_wall,
)

SR = 22050


def _write_tone(path, seconds=2.0, freq=440.0, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return path


def _broadband(n=SR * 2, sr=SR):
    rng = np.random.default_rng(0)
    x = rng.standard_normal((n, 2)).astype(np.float32) * 0.3
    return AudioBuffer(x, sr)


def test_a_silent_source_returns_exactly_what_was_asked_for():
    source = SilentSource(SR)
    buf = source.read(1234)
    assert buf.n_frames == 1234
    assert buf.n_channels == 2
    assert np.all(buf.data == 0.0)


def test_a_room_source_returns_the_requested_length(tmp_path):
    _write_tone(tmp_path / "a.wav")
    source = RoomSource([str(tmp_path / "a.wav")], SR)
    assert source.read(5000).n_frames == 5000


def test_a_room_source_keeps_going_past_the_end_of_its_file(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=0.5)
    source = RoomSource([str(tmp_path / "a.wav")], SR)
    buf = source.read(int(SR * 3))
    assert buf.n_frames == int(SR * 3)
    # It looped rather than trailing off into silence.
    assert np.abs(buf.data[-1000:]).max() > 0.01


def test_a_room_source_advances_rather_than_repeating_the_same_window(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=4.0)
    source = RoomSource([str(tmp_path / "a.wav")], SR)
    first, second = source.read(2000), source.read(2000)
    assert not np.array_equal(first.data, second.data)


def test_a_room_source_moves_on_to_the_next_file(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=0.5, freq=200.0)
    _write_tone(tmp_path / "b.wav", seconds=0.5, freq=900.0)
    source = RoomSource([str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], SR)
    buf = source.read(int(SR * 1.0))
    spectrum = np.abs(np.fft.rfft(buf.data.mean(axis=1)))
    freqs = np.fft.rfftfreq(buf.n_frames, 1.0 / SR)
    # Both files contributed, so both tones are present.
    assert spectrum[np.argmin(np.abs(freqs - 200.0))] > spectrum.mean() * 5
    assert spectrum[np.argmin(np.abs(freqs - 900.0))] > spectrum.mean() * 5


def test_a_missing_file_does_not_stop_the_night(tmp_path):
    _write_tone(tmp_path / "a.wav")
    source = RoomSource([str(tmp_path / "gone.wav"), str(tmp_path / "a.wav")],
                        SR)
    assert source.read(4000).n_frames == 4000


def test_a_source_with_nothing_readable_goes_silent(tmp_path):
    source = RoomSource([str(tmp_path / "nope.wav")], SR)
    buf = source.read(4000)
    assert buf.n_frames == 4000
    assert np.all(buf.data == 0.0)


def test_a_zero_length_file_does_not_hang_the_room(tmp_path):
    # A truncated or empty download decodes without error but has nothing in
    # it. Treating that as a successful load would leave the cursor stuck at
    # n_frames == 0 forever, so read() must not hang on it.
    sf.write(str(tmp_path / "empty.wav"), np.zeros((0, 2), dtype=np.float32),
              SR)
    source = RoomSource([str(tmp_path / "empty.wav")], SR)
    buf = source.read(4000)
    assert buf.n_frames == 4000
    assert np.all(buf.data == 0.0)


def test_a_zero_length_file_is_skipped_in_favour_of_a_real_one(tmp_path):
    sf.write(str(tmp_path / "empty.wav"), np.zeros((0, 2), dtype=np.float32),
              SR)
    _write_tone(tmp_path / "a.wav")
    source = RoomSource(
        [str(tmp_path / "empty.wav"), str(tmp_path / "a.wav")], SR)
    buf = source.read(4000)
    assert buf.n_frames == 4000
    assert np.abs(buf.data).max() > 0.01


def test_room_sources_from_an_empty_directory_is_silent(tmp_path):
    source = room_sources_from(str(tmp_path), SR)
    assert isinstance(source, SilentSource)


def test_room_sources_from_a_missing_directory_is_silent(tmp_path):
    source = room_sources_from(str(tmp_path / "nothing-here"), SR)
    assert isinstance(source, SilentSource)


def test_room_sources_from_a_populated_directory_reads_it(tmp_path):
    _write_tone(tmp_path / "a.wav")
    source = room_sources_from(str(tmp_path), SR)
    assert isinstance(source, RoomSource)


def _high_frequency_share(buf: AudioBuffer) -> float:
    mono = buf.data.mean(axis=1)
    spectrum = np.abs(np.fft.rfft(mono)) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1.0 / buf.sr)
    above = spectrum[freqs > 1500.0].sum()
    return float(above / max(spectrum.sum(), 1e-12))


def test_through_a_wall_removes_the_frequencies_speech_is_carried_on():
    dry = _broadband()
    muffled = through_a_wall(dry, intelligibility=0.8)
    assert _high_frequency_share(muffled) < _high_frequency_share(dry) / 10.0


def test_lower_intelligibility_is_more_muffled():
    dry = _broadband()
    clearer = through_a_wall(dry, intelligibility=0.8)
    murkier = through_a_wall(dry, intelligibility=0.05)
    assert _high_frequency_share(murkier) <= _high_frequency_share(clearer)


def test_lower_intelligibility_is_quieter():
    dry = _broadband()
    clearer = through_a_wall(dry, intelligibility=0.8)
    murkier = through_a_wall(dry, intelligibility=0.05)
    assert np.abs(murkier.data).max() < np.abs(clearer.data).max()


def test_through_a_wall_preserves_length_and_shape():
    dry = _broadband()
    out = through_a_wall(dry, 0.5)
    assert out.n_frames == dry.n_frames
    assert out.n_channels == 2


def test_through_a_wall_survives_silence():
    quiet = AudioBuffer(np.zeros((1000, 2), dtype=np.float32), SR)
    out = through_a_wall(quiet, 0.5)
    assert np.all(np.isfinite(out.data))


def test_through_a_wall_survives_a_zero_length_request():
    empty = AudioBuffer(np.zeros((0, 2), dtype=np.float32), SR)
    out = through_a_wall(empty, 0.5)
    assert out.n_frames == 0
    assert out.n_channels == 2
