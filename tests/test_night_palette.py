"""The generators, and the one rule they may not break.

No transients. Every voice must arrive and leave over seconds, because an
attack is an event and events wake people up. That is asserted directly here
rather than left to listening, since it is the property most likely to be
broken by an innocent-looking change to either generator.
"""
import numpy as np
import pytest

from sleepmix.config import StemDecayConfig
from sleepmix.night.palette import FADE_S, render_voice
from sleepmix.night.plan import Voice

SR = 22050


def _voice(texture: str = "drone", index: int = 0, seconds: float = 60.0,
           pitch_hz: float = 110.0) -> Voice:
    return Voice(index=index, birth_frame=0, n_frames=int(seconds * SR),
                 pitch_hz=pitch_hz, texture=texture, decay=StemDecayConfig())


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_is_stereo_and_the_length_it_says_it_is(texture):
    voice = _voice(texture)
    buf = render_voice(voice, SR, seed=1)
    assert buf.n_frames == voice.n_frames
    assert buf.n_channels == 2
    assert buf.sr == SR


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_has_no_attack(texture):
    """The first moments must be far quieter than the middle."""
    buf = render_voice(_voice(texture), SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    opening = x[:int(0.05 * SR)].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert opening < middle * 0.05


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_has_no_release_cliff(texture):
    buf = render_voice(_voice(texture), SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    closing = x[-int(0.05 * SR):].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert closing < middle * 0.05


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_is_reproducible(texture):
    a = render_voice(_voice(texture), SR, seed=5)
    b = render_voice(_voice(texture), SR, seed=5)
    assert np.array_equal(a.data, b.data)


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_different_voices_draw_different_noise(texture):
    a = render_voice(_voice(texture, index=0), SR, seed=5)
    b = render_voice(_voice(texture, index=1), SR, seed=5)
    assert not np.array_equal(a.data, b.data)


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_nothing_clips(texture):
    buf = render_voice(_voice(texture), SR, seed=1)
    assert np.abs(buf.data).max() <= 1.0


def test_a_drone_sits_at_the_pitch_it_was_asked_for():
    voice = _voice("drone", pitch_hz=110.0, seconds=20.0)
    buf = render_voice(voice, SR, seed=1)
    mono = buf.data.mean(axis=1)
    # Look at the sustained middle, away from the fades.
    window = mono[5 * SR: 15 * SR]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
    peak_hz = freqs[int(np.argmax(spectrum))]
    assert abs(peak_hz - 110.0) < 3.0


def test_a_noiseband_is_centred_near_its_pitch_and_is_not_a_tone():
    voice = _voice("noiseband", pitch_hz=220.0, seconds=20.0)
    buf = render_voice(voice, SR, seed=1)
    mono = buf.data.mean(axis=1)
    window = mono[5 * SR: 15 * SR]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
    peak_hz = freqs[int(np.argmax(spectrum))]
    assert abs(peak_hz - 220.0) < 60.0
    # A tone puts nearly all its energy in one bin; a band does not.
    assert spectrum.max() / spectrum.sum() < 0.05


def test_a_voice_shorter_than_two_fades_still_fades_both_ends():
    voice = _voice("drone", seconds=FADE_S)
    buf = render_voice(voice, SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    assert x[0] < 1e-4
    assert x[-1] < 1e-4
    assert x.max() > 1e-3


# -- source voices -----------------------------------------------------

def _loop_file(tmp_path, seconds=2.0, freq=220.0, sr=SR):
    import soundfile as sf
    t = np.arange(int(seconds * sr)) / sr
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    path = tmp_path / f"loop-{freq}.wav"
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return str(path), int(seconds * sr)


def _source_voice(profile, seconds=30.0, gain=1.0, index=0, sr=SR):
    # sr defaults to the module SR: a Voice's n_frames is a frame count at
    # whatever rate the night is actually rendering at, not a duration that
    # rescales itself. The brief's draft hardcoded SR here regardless of the
    # sr a caller later renders at, which made
    # test_a_source_voice_is_resampled_when_the_loop_rate_differs assert a
    # frame count the voice could not possibly produce (30s at 44100 while
    # the voice only ever asked for 30s' worth of frames at 22050, i.e. 15s
    # at 44100) — one of the "tests asserting values impossible under
    # constants defined in the same file" the task brief warned about.
    return Voice(index=index, birth_frame=0, n_frames=int(seconds * sr),
                 pitch_hz=0.0, texture="source", decay=StemDecayConfig(),
                 source_id=profile.source_id, loop_index=0, gain=gain)


def _profile(tmp_path, source_id="a", **kw):
    # Drift from the brief: SourceProfile gained a sixth field, source_path,
    # in Task 3. Passed by keyword, along with everything else — a frozen
    # dataclass that grows a field will happily accept the wrong keyword
    # order otherwise.
    from sleepmix.night.sources import SourceProfile
    path, frames = _loop_file(tmp_path, **kw)
    return SourceProfile(source_id=source_id, source_path=path,
                         loop_paths=(path,), loop_frames=(frames,),
                         pitch_set=(55.0,), sr=SR)


def test_a_source_voice_is_the_length_it_says_it_is(tmp_path):
    profile = _profile(tmp_path)
    buf = render_voice(_source_voice(profile), SR, seed=1, profiles=(profile,))
    assert buf.n_frames == int(30.0 * SR)
    assert buf.n_channels == 2


def test_a_source_voice_tiles_a_short_loop_to_fill_its_life(tmp_path):
    profile = _profile(tmp_path, seconds=2.0)
    buf = render_voice(_source_voice(profile, seconds=10.0), SR, seed=1,
                       profiles=(profile,))
    x = np.abs(buf.data).max(axis=1)
    middle = x[3 * SR: 7 * SR]
    assert middle.max() > 1e-3          # still sounding well past one loop


def test_a_source_voice_has_no_attack_or_release(tmp_path):
    profile = _profile(tmp_path)
    buf = render_voice(_source_voice(profile), SR, seed=1, profiles=(profile,))
    x = np.abs(buf.data).max(axis=1)
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert x[:int(0.05 * SR)].max() < middle * 0.05
    assert x[-int(0.05 * SR):].max() < middle * 0.05


def test_gain_actually_scales_a_source_voice(tmp_path):
    profile = _profile(tmp_path)
    loud = render_voice(_source_voice(profile, gain=1.0), SR, 1, (profile,))
    quiet = render_voice(_source_voice(profile, gain=0.25), SR, 1, (profile,))
    assert np.abs(quiet.data).max() < np.abs(loud.data).max() * 0.5


def test_gain_scales_a_synthesized_voice_too(tmp_path):
    loud = _voice("drone")
    quiet = Voice(index=0, birth_frame=0, n_frames=loud.n_frames,
                  pitch_hz=loud.pitch_hz, texture="drone",
                  decay=StemDecayConfig(), gain=0.25)
    assert np.abs(render_voice(quiet, SR, 1).data).max() < \
        np.abs(render_voice(loud, SR, 1).data).max() * 0.5


def test_a_source_voice_with_no_matching_profile_is_silence_not_a_raise(tmp_path):
    profile = _profile(tmp_path)
    orphan = _source_voice(profile)
    buf = render_voice(orphan, SR, seed=1, profiles=())
    assert buf.n_frames == orphan.n_frames
    assert np.all(buf.data == 0.0)


def test_a_source_voice_whose_id_matches_nothing_present_is_silence(tmp_path):
    """Distinct from the empty-``profiles`` case above: here ``profiles`` is
    non-empty but contains no profile with this voice's ``source_id``. The
    brief's ``_source`` uses ``next(... , None)`` to fall through both cases
    the same way, but a version that used a bare ``next(...)`` generator
    expression instead would raise ``StopIteration`` for exactly this case
    while still passing the empty-tuple test above — this is the regression
    test for that branch specifically."""
    profile = _profile(tmp_path)
    other = _profile(tmp_path, source_id="b", freq=440.0)
    orphan = _source_voice(profile)
    buf = render_voice(orphan, SR, seed=1, profiles=(other,))
    assert buf.n_frames == orphan.n_frames
    assert np.all(buf.data == 0.0)


def test_a_source_voice_whose_loop_file_has_gone_is_silence(tmp_path):
    from sleepmix.night.sources import SourceProfile
    profile = SourceProfile(source_id="a", source_path="/nowhere/gone.wav",
                            loop_paths=("/nowhere/gone.wav",),
                            loop_frames=(1000,), pitch_set=(55.0,), sr=SR)
    buf = render_voice(_source_voice(profile), SR, 1, (profile,))
    assert np.all(buf.data == 0.0)


def test_an_out_of_range_loop_index_is_silence_not_a_raise(tmp_path):
    profile = _profile(tmp_path)
    voice = Voice(index=0, birth_frame=0, n_frames=SR, pitch_hz=0.0,
                  texture="source", decay=StemDecayConfig(),
                  source_id="a", loop_index=99, gain=1.0)
    assert np.all(render_voice(voice, SR, 1, (profile,)).data == 0.0)


def test_a_source_voice_is_reproducible(tmp_path):
    profile = _profile(tmp_path)
    a = render_voice(_source_voice(profile), SR, 5, (profile,))
    b = render_voice(_source_voice(profile), SR, 5, (profile,))
    assert np.array_equal(a.data, b.data)


def test_a_source_voice_is_resampled_when_the_loop_rate_differs(tmp_path):
    """Length alone cannot tell resampling apart from its absence: the
    tiling in ``_source`` truncates to exactly ``n`` frames regardless of
    what rate the loop's samples actually represent, so
    ``buf.n_frames == int(30.0 * 44100)`` holds even if ``_loop_for`` quietly
    dropped the ``sr=`` argument to ``load_audio`` and returned the loop at
    its native 22050 Hz. That was the brief's original assertion, and it is
    non-discriminating for the one thing this test is named for. Checking
    the tone's frequency, at the render's actual sample rate, is what
    actually distinguishes "resampled" from "not."""
    profile = _profile(tmp_path)  # loop tone is 220.0 Hz, recorded at SR=22050
    voice = _source_voice(profile, sr=44100)
    buf = render_voice(voice, 44100, 1, (profile,))
    assert buf.sr == 44100
    assert buf.n_frames == int(30.0 * 44100)

    mono = buf.data.mean(axis=1)
    window = mono[10 * 44100: 20 * 44100]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / 44100)
    peak_hz = freqs[int(np.argmax(spectrum))]
    # If the loop were played back unresampled at the render's 44100 Hz
    # instead of its native 22050 Hz, the 220 Hz tone would sound at 440 Hz.
    assert abs(peak_hz - 220.0) < 5.0


def test_the_loop_cache_eviction_does_not_change_what_renders(tmp_path, monkeypatch):
    """Block independence, the way stream.py's voice cache checks it: shrink
    the cache to almost nothing, force an eviction between two renders of the
    same voice, and confirm the second render is byte-identical to the first.
    The cache is documented as an optimisation and never an input — this is
    the regression test for that claim.

    Reviewer-found: the original version of this test asserted only that
    the two renders matched, which is true whether or not a cache exists at
    all — deleting the caching mechanism entirely (no dict, no accounting,
    ``load_audio`` on every call) still passes it, because ``render_voice``
    is a pure function of stable disk content with or without a cache in
    front of it. The assertion below that ``profile_a``'s key is actually
    gone from ``_loop_cache`` after the intervening render is what proves
    there was a cache entry to evict in the first place, so the "renders
    match" assertion that follows is actually exercising eviction and not
    merely restating purity.
    """
    import sleepmix.night.palette as palette_mod

    profile_a = _profile(tmp_path, seconds=1.0, freq=220.0)
    other_path, other_frames = _loop_file(tmp_path, seconds=1.0, freq=330.0)
    from sleepmix.night.sources import SourceProfile
    profile_b = SourceProfile(source_id="b", source_path=other_path,
                              loop_paths=(other_path,),
                              loop_frames=(other_frames,),
                              pitch_set=(55.0,), sr=SR)

    monkeypatch.setattr(palette_mod, "_LOOP_CACHE_BYTES", 1)

    voice = _source_voice(profile_a, seconds=3.0)
    first = render_voice(voice, SR, 1, (profile_a,))

    key_a = (profile_a.loop_paths[0], SR)
    assert key_a in palette_mod._loop_cache  # there is something to evict

    # Render an unrelated source loop, which — with the cache capped at one
    # byte — evicts profile_a's loop out of the module-level cache.
    render_voice(_source_voice(profile_b, seconds=3.0), SR, 1, (profile_b,))

    assert key_a not in palette_mod._loop_cache  # eviction actually happened

    second = render_voice(voice, SR, 1, (profile_a,))
    assert np.array_equal(first.data, second.data)


def test_the_loop_cache_evicts_the_oldest_entry_first(tmp_path, monkeypatch):
    """Direct test of the eviction *policy*, not just its transparency.

    Reviewer-found: reverting ``_loop_cache.popitem(last=False)`` to plain
    ``popitem()`` — LRU to LIFO, a one-keyword slip — left the entire suite
    green, including the test above (which only checks that *something*
    consistent comes out, not that the *right* entry was kept). That is
    exactly the failure mode this project's own plan calls out by name:
    Phase 1's voice cache was specified as 24 entries and held 1.3 GB
    because nothing checked the eviction policy directly.

    Insert two loops under a budget that fits one but not both; the older
    (path_a, inserted first) must be the one evicted, the newer (path_b)
    must survive, and ``_loop_cache_bytes`` must equal what the surviving
    entry actually weighs — not merely be `<= budget`, which a policy that
    evicted the wrong entry would also satisfy.
    """
    import sleepmix.night.palette as palette_mod

    path_a, _ = _loop_file(tmp_path, seconds=1.0, freq=220.0)
    path_b, _ = _loop_file(tmp_path, seconds=1.0, freq=330.0)

    one_entry_bytes = int(1.0 * SR) * 2 * 4  # frames * channels * float32
    monkeypatch.setattr(palette_mod, "_LOOP_CACHE_BYTES",
                        int(one_entry_bytes * 1.5))

    palette_mod._loop_for(path_a, SR)
    palette_mod._loop_for(path_b, SR)

    assert (path_a, SR) not in palette_mod._loop_cache, (
        "the older entry should have been evicted to make room")
    assert (path_b, SR) in palette_mod._loop_cache, (
        "the newer entry should have survived")
    assert palette_mod._loop_cache_bytes == sum(
        buf.data.nbytes for buf in palette_mod._loop_cache.values()), (
        "_loop_cache_bytes has drifted out of sync with the dict")


def test_the_loop_cache_never_evicts_down_to_empty(tmp_path, monkeypatch):
    """The eviction loop keeps at least one entry, even capped absurdly low —
    otherwise a single voice with a loop bigger than the whole budget could
    never populate the cache at all and would refetch from disk every call
    (harmless for correctness, but the invariant is worth pinning directly)."""
    import sleepmix.night.palette as palette_mod

    monkeypatch.setattr(palette_mod, "_LOOP_CACHE_BYTES", 1)
    path, frames = _loop_file(tmp_path, seconds=1.0)
    palette_mod._loop_for(path, SR)
    assert len(palette_mod._loop_cache) == 1


def test_an_unknown_texture_is_refused():
    with pytest.raises(ValueError, match="unknown texture"):
        render_voice(_voice("trumpet"), SR, seed=1)
