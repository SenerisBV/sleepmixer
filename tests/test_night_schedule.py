"""Who holds the stage, and for how long.

Concurrent voices drawn from different songs would be mud — different keys,
different rooms, different tape — so one source holds the stage at a time.
The handover would be an event, except that the ghosts of the outgoing source
outlive it and cover the seam; that half lives in the planner, and this file
only has to guarantee the schedule it works from is sane and reproducible.
"""
import signal

import pytest

from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    STAGE_MAX_S, STAGE_MIN_S, Stage, schedule_sources, stage_at,
)
from sleepmix.night.sources import SourceProfile

SR = 22050
NIGHT_S = 8 * 3600.0


def _profile(name, pitches):
    return SourceProfile(source_id=name, source_path=f"/songs/{name}.flac",
                         loop_paths=(f"/{name}.wav",), loop_frames=(100000,),
                         pitch_set=tuple(pitches), sr=44100)


def _context(sources=(), seed=1):
    return NightContext(
        seed=seed, night_length_s=NIGHT_S,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0, sources=tuple(sources))


def _schedule(sources, seed=1):
    ctx = _context(sources, seed)
    return schedule_sources(ctx, SR, int(NIGHT_S * SR)), ctx


def test_no_sources_is_an_empty_schedule():
    schedule, _ = _schedule([])
    assert schedule == ()


def test_one_source_holds_the_whole_night():
    schedule, _ = _schedule([_profile("a", (55.0,))])
    assert all(s.source_index == 0 for s in schedule)


def test_the_schedule_covers_the_night_without_gaps_or_overlaps():
    schedule, _ = _schedule([_profile(n, (55.0 + i,))
                             for i, n in enumerate("abcd")])
    assert schedule[0].start_frame == 0
    for earlier, later in zip(schedule, schedule[1:]):
        assert earlier.end_frame == later.start_frame
    assert schedule[-1].end_frame >= int(NIGHT_S * SR)


def test_every_stage_lasts_a_plausible_stretch():
    schedule, _ = _schedule([_profile(n, (55.0 + i,))
                             for i, n in enumerate("abcd")])
    for stage in schedule[:-1]:
        seconds = (stage.end_frame - stage.start_frame) / SR
        assert STAGE_MIN_S <= seconds <= STAGE_MAX_S


def test_consecutive_stages_do_not_repeat_a_source_when_others_exist():
    schedule, _ = _schedule([_profile(n, (55.0 + i * 3,))
                             for i, n in enumerate("abcd")])
    for earlier, later in zip(schedule, schedule[1:]):
        assert earlier.source_index != later.source_index


def test_the_next_source_is_the_nearest_in_pitch():
    """The overlap during a handover should be consonant rather than a
    collision, and the planner has the numbers to arrange that.

    ``start``'s pitches are roughly a semitone from ``near``'s and several
    hundred cents from ``far``'s in either argument order of
    ``pitch_distance`` (verified by hand while writing this test), so
    ``near`` is unambiguously the nearer neighbour regardless of which side
    of the (documented non-symmetric) comparison ``current`` sits on.

    Seed 1 is asserted to put ``start`` first — that precondition is what
    makes the second assertion load-bearing rather than vacuous. The
    original brief's version used ``... or schedule[0].source_index != 0``,
    which made the whole assertion pass regardless of what the code did
    whenever the precondition failed to hold; asserting the precondition
    directly instead means the test can actually fail.
    """
    near = _profile("near", (56.0, 84.0))
    far = _profile("far", (78.0, 104.0))
    start = _profile("start", (55.0, 82.5))
    schedule, _ = _schedule([start, near, far])

    assert schedule[0].source_index == 0, (
        "precondition: seed 1 must start on 'start' for this test to mean "
        "anything")
    assert schedule[1].source_index == [start, near, far].index(near)


def test_the_schedule_is_reproducible_from_the_seed():
    sources = [_profile(n, (55.0 + i,)) for i, n in enumerate("abc")]
    assert _schedule(sources, seed=7)[0] == _schedule(sources, seed=7)[0]


def test_a_different_seed_gives_a_different_schedule():
    sources = [_profile(n, (55.0 + i * 4,)) for i, n in enumerate("abcde")]
    assert _schedule(sources, seed=1)[0] != _schedule(sources, seed=2)[0]


def test_stage_at_finds_the_stage_covering_a_frame():
    schedule, _ = _schedule([_profile(n, (55.0 + i,))
                             for i, n in enumerate("abc")])
    for stage in schedule:
        middle = (stage.start_frame + stage.end_frame) // 2
        assert stage_at(schedule, middle) == stage


def test_stage_at_before_the_night_and_after_it():
    schedule, _ = _schedule([_profile("a", (55.0,))])
    assert stage_at(schedule, -1) is None
    assert stage_at((), 0) is None
    # Past the end clamps to the last stage rather than falling off, so a
    # stream that outlives its own arc keeps its material.
    assert stage_at(schedule, schedule[-1].end_frame + SR) == schedule[-1]


def test_a_source_with_no_pitches_is_still_scheduled():
    """A pitchless source has no ghost, but its loops are still material."""
    schedule, _ = _schedule([_profile("a", ()), _profile("b", (55.0,))])
    assert schedule


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"),
                    reason="needs SIGALRM to bound a possible infinite loop")
def test_schedule_sources_terminates_at_a_degenerate_sample_rate():
    """A zero sample rate must not draw a zero-length stage forever.

    ``length`` is ``int(seconds * sr)``; at ``sr = 0`` that is always 0,
    which — without a floor of one frame — leaves ``cursor`` unmoved and the
    scheduling loop never reaches ``night_frames``. ``plan_voices``' own
    birth-gap draw already guards the equivalent case with
    ``max(..., 1)``; ``schedule_sources`` did not, until this test's fix.
    Bounded with ``SIGALRM`` rather than a background thread, so a
    regression here fails this one test instead of hanging the whole suite.
    """
    ctx = _context([_profile("a", (55.0,))])

    def _on_alarm(signum, frame):
        raise TimeoutError("schedule_sources did not terminate")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(2)
    try:
        schedule = schedule_sources(ctx, 0, 100)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    assert schedule
    assert all(s.end_frame > s.start_frame for s in schedule)
