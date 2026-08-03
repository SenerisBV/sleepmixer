import pytest

from sleepmix.progress import (
    CancelToken, Cancelled, ProgressEvent, ProgressReporter, echo_sink)


def test_reporter_emits_events_to_sink():
    seen = []
    r = ProgressReporter(seen.append)
    r.emit("separate", "Separating stems…", 0.0)
    r.emit("master", "Mastering…", 1.0)
    assert [e.stage for e in seen] == ["separate", "master"]
    assert seen[0].message == "Separating stems…"


def test_fraction_is_clamped_and_monotonic():
    seen = []
    r = ProgressReporter(seen.append)
    r.emit("a", "x", 0.5)
    r.emit("b", "y", 0.2)      # regression is clamped up to the previous value
    r.emit("c", "z", 5.0)      # over-range is clamped down to 1.0
    fractions = [e.fraction for e in seen]
    assert fractions == [0.5, 0.5, 1.0]


def test_stage_range_maps_local_progress_into_a_slice():
    seen = []
    r = ProgressReporter(seen.append)
    with r.stage_range(0.4, 0.8):
        r.emit("stem", "half way through this stage", 0.5)
    assert seen[0].fraction == pytest.approx(0.6)


def test_reporter_with_no_sink_is_a_noop():
    r = ProgressReporter(None)
    r.emit("a", "x", 0.5)      # must not raise


def test_cancel_token_starts_uncancelled():
    t = CancelToken()
    assert not t.cancelled
    t.check()                  # must not raise


def test_cancel_token_raises_after_cancel():
    t = CancelToken()
    t.cancel()
    assert t.cancelled
    with pytest.raises(Cancelled):
        t.check()


def test_echo_sink_renders_events_as_strings():
    lines = []
    sink = echo_sink(lines.append)
    sink(ProgressEvent(stage="separate", stem=None, fraction=0.0,
                       message="Separating stems…"))
    assert lines == ["Separating stems…"]
