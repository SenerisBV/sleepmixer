"""A room heard through a wall.

The thing being built here is not "quiet dialogue" — it is the sound of a TV
on in the living room while you fall asleep on the couch. The tests below
mostly check that the treatment removes what makes speech followable, because
that is the property the whole design turns on: intelligible speech at 3 AM is
the failure mode of the project.
"""
import time

import numpy as np
import pytest
import soundfile as sf

from sleepmix.audio import AudioBuffer
from sleepmix.night import speech as speech_mod
from sleepmix.night.speech import (
    RoomSource, SilentSource, room_sources_from, through_a_wall,
)

SR = 22050


def _wait_for_prefetch(source: RoomSource, timeout: float = 5.0) -> bool:
    """Let the background decoder land before reading across a file boundary.

    Decoding moved off the playback path, so which file comes next is now a
    question of whether the prefetch thread has finished — which in a test,
    where the files are half a second long, it will not have when ``read`` is
    called microseconds after construction. Waiting here is not a weaker
    assertion; it is the same assertion made of a source that prefetches.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if source._next is not None:
            return True
        time.sleep(0.01)
    return False


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
    assert _wait_for_prefetch(source)
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


def test_a_room_splice_is_crossfaded_rather_than_butt_joined(tmp_path):
    """A step at an arbitrary sample is a click, and a click wakes people.

    Two files spliced end to end land on whatever sample values they happen
    to end and begin on. Here they are chosen to be maximally hostile — the
    outgoing file ends near +0.5 and the incoming one begins near -0.5 — so
    an uncrossfaded join would show a step around 1.0 in a signal whose own
    sample-to-sample motion is tiny.
    """
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    # A 2 Hz sine over half a second ends at its peak; its negative begins at
    # its own trough. Slow, so neighbouring samples barely differ.
    a = (0.5 * np.sin(2 * np.pi * 0.5 * t)).astype(np.float32)
    sf.write(str(tmp_path / "a.wav"), np.stack([a, a], axis=1), SR)
    sf.write(str(tmp_path / "b.wav"), np.stack([-a, -a], axis=1), SR)

    source = RoomSource([str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], SR)
    assert _wait_for_prefetch(source)
    mono = source.read(int(SR * 1.0)).data.mean(axis=1)

    # Butt-joined, the seam would be a single-sample jump of about 1.0: a
    # ends near +0.5 and -a begins near -0.5. Crossfaded, the whole
    # transition is spread over _ROOM_XFADE_S, so no one sample moves more
    # than a small fraction of that.
    butt_joined_step = abs(float(a[-1]) - float(-a[0]))
    assert butt_joined_step > 0.4  # the join really is hostile
    assert np.abs(np.diff(mono)).max() < butt_joined_step * 0.02


def test_a_room_loop_is_crossfaded_too(tmp_path):
    """The same argument applies to one file played round and round."""
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    a = (0.5 * np.sin(2 * np.pi * 0.5 * t)).astype(np.float32)
    sf.write(str(tmp_path / "a.wav"), np.stack([a, a], axis=1), SR)

    source = RoomSource([str(tmp_path / "a.wav")], SR)
    mono = source.read(int(SR * 2.0)).data.mean(axis=1)
    butt_joined_step = abs(float(a[-1]) - float(a[0]))
    assert butt_joined_step > 0.4
    assert np.abs(np.diff(mono)).max() < butt_joined_step * 0.02


def test_reading_a_room_never_decodes_on_the_playback_path(tmp_path,
                                                           monkeypatch):
    """``load_audio`` is a whole-file read plus a resample. It used to happen
    inside ``read``, which is inside the block the sound device is waiting
    for. Construction may decode; ``read`` may not — and if the prefetch has
    not landed, ``read`` loops what it already holds rather than reaching for
    the disk."""
    _write_tone(tmp_path / "a.wav", seconds=0.5)
    _write_tone(tmp_path / "b.wav", seconds=0.5)
    source = RoomSource([str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], SR)

    # Stop the prefetch thread so nothing but ``read`` itself can decode.
    source._stop.set()
    source._thread.join(timeout=5.0)

    def forbidden(*args, **kwargs):
        raise AssertionError("read() decoded a file on the playback path")

    monkeypatch.setattr(speech_mod, "load_audio", forbidden)
    # Long enough to cross several file boundaries.
    buf = source.read(int(SR * 3.0))
    assert buf.n_frames == int(SR * 3.0)
    # It kept going, by looping what it already had.
    assert np.abs(buf.data[-1000:]).max() > 0.01


def test_a_room_source_stops_its_thread_when_closed(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=0.5)
    _write_tone(tmp_path / "b.wav", seconds=0.5)
    source = RoomSource([str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], SR)
    thread = source._thread
    assert thread is not None and thread.daemon
    source.close()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    # And it still answers, silently, after being closed.
    assert np.all(source.read(1000).data == 0.0)


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


def test_through_a_wall_leaves_no_silence_at_the_head_of_a_block():
    """The pre-delay is trimmed, so frame 0 is still frame 0.

    ``apply_reverb``'s pedalboard backend shifts the whole buffer — dry
    included — by ``predelay_ms``, which is 12 ms for the wall. Truncating
    back to length without trimming left 12 ms of exact digital zeros at the
    head of every treated block, and the player concatenates consecutive
    treated blocks, so that was a gap repeating at 0.1 Hz all night.
    """
    out = through_a_wall(_broadband(), intelligibility=0.8)
    head = out.data[:int(0.012 * SR) + 1]
    assert np.abs(head).max() > 0.0


def test_consecutive_treated_blocks_join_without_a_step():
    """What ``player._speech`` actually does: treat block after block and
    concatenate. The seam between two of them must not be a bigger step than
    the signal's own motion inside one."""
    dry = _broadband(n=SR * 2)
    half = dry.n_frames // 2
    first = through_a_wall(AudioBuffer(dry.data[:half], SR), 0.8)
    second = through_a_wall(AudioBuffer(dry.data[half:], SR), 0.8)
    step = np.abs(second.data[0] - first.data[-1]).max()
    within = np.abs(np.diff(first.data, axis=0)).max()
    assert step <= within * 4.0


def test_through_a_wall_passes_level_through_rather_than_normalising_it():
    """A pause between two lines of dialogue must stay a pause.

    The treatment used to end in ``data * (target / peak)``, which is an
    automatic gain control: a 60 dB change at the input produced none at the
    output, and because the peak was measured per block the gain stepped at
    every block boundary — a room pumping on a ten-second cycle.
    """
    loud = _broadband()
    quiet = AudioBuffer(loud.data * 0.001, loud.sr)

    loud_out = np.abs(through_a_wall(loud, 0.8).data).max()
    quiet_out = np.abs(through_a_wall(quiet, 0.8).data).max()
    assert quiet_out == pytest.approx(loud_out * 0.001, rel=0.05)


def test_through_a_walls_gain_does_not_depend_on_the_block_it_is_given():
    """Two halves of one signal, treated separately, must be treated the
    same. A per-block peak measurement is exactly what would break this."""
    x = _broadband(n=SR * 2).data
    # Deliberately lopsided: the second half is 20 dB down on the first.
    x[len(x) // 2:] *= 0.1
    first = through_a_wall(AudioBuffer(x[:len(x) // 2], SR), 0.5)
    second = through_a_wall(AudioBuffer(x[len(x) // 2:], SR), 0.5)
    ratio = np.abs(second.data).max() / np.abs(first.data).max()
    assert ratio == pytest.approx(0.1, rel=0.15)


def test_through_a_wall_survives_a_zero_length_request():
    empty = AudioBuffer(np.zeros((0, 2), dtype=np.float32), SR)
    out = through_a_wall(empty, 0.5)
    assert out.n_frames == 0
    assert out.n_channels == 2
