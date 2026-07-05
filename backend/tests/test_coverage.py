# backend/tests/test_coverage.py
from datetime import datetime, timedelta, timezone

from app.ingestion.coverage import (
    COVERED,
    NO_TERRESTRIAL_COVERAGE,
    WARMING_UP,
    CoverageMonitor,
)

T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def test_unsubscribed_box_is_warming_up():
    monitor = CoverageMonitor(["hormuz"], window_seconds=600)
    assert monitor.state("hormuz", now=T0) == WARMING_UP


def test_subscribed_box_stays_warming_up_within_window():
    monitor = CoverageMonitor(["hormuz"], window_seconds=600)
    monitor.mark_subscribed(now=T0)
    assert monitor.state("hormuz", now=T0 + timedelta(seconds=599)) == WARMING_UP


def test_zero_frames_after_full_window_is_no_coverage():
    monitor = CoverageMonitor(["hormuz"], window_seconds=600)
    monitor.mark_subscribed(now=T0)
    assert monitor.state("hormuz", now=T0 + timedelta(seconds=601)) == NO_TERRESTRIAL_COVERAGE


def test_frame_inside_window_is_covered():
    monitor = CoverageMonitor(["hormuz", "india_west_coast"], window_seconds=600)
    monitor.mark_subscribed(now=T0)
    monitor.mark_frame("india_west_coast", now=T0 + timedelta(seconds=620))

    # India's last frame is 80s old (inside the window) → COVERED; the quiet
    # box is judged independently and has had a full silent window → void.
    assert monitor.state("india_west_coast", now=T0 + timedelta(seconds=700)) == COVERED
    assert monitor.state("hormuz", now=T0 + timedelta(seconds=700)) == NO_TERRESTRIAL_COVERAGE


def test_coverage_expires_when_frames_stop():
    monitor = CoverageMonitor(["hormuz"], window_seconds=600)
    monitor.mark_subscribed(now=T0)
    monitor.mark_frame("hormuz", now=T0 + timedelta(seconds=10))
    assert monitor.state("hormuz", now=T0 + timedelta(seconds=800)) == NO_TERRESTRIAL_COVERAGE


def test_resubscribe_restarts_warmup_but_keeps_counts():
    monitor = CoverageMonitor(["hormuz"], window_seconds=600)
    monitor.mark_subscribed(now=T0)
    monitor.mark_frame("hormuz", now=T0 + timedelta(seconds=1))
    monitor.mark_subscribed(now=T0 + timedelta(seconds=1000))  # reconnect

    assert monitor.frame_counts["hormuz"] == 1
    # Old frame is outside the window; fresh subscription → warming up again.
    assert monitor.state("hormuz", now=T0 + timedelta(seconds=1001)) == WARMING_UP


def test_snapshot_reports_state_frames_and_last_frame():
    monitor = CoverageMonitor(["hormuz", "india_west_coast"], window_seconds=600)
    monitor.mark_subscribed(now=T0)
    monitor.mark_frame("india_west_coast", now=T0 + timedelta(seconds=620))

    snap = monitor.snapshot(now=T0 + timedelta(seconds=650))
    assert snap["india_west_coast"]["state"] == COVERED
    assert snap["india_west_coast"]["frames"] == 1
    assert snap["india_west_coast"]["last_frame_utc"] is not None
    assert snap["hormuz"]["state"] == NO_TERRESTRIAL_COVERAGE
    assert snap["hormuz"]["frames"] == 0
    assert snap["hormuz"]["last_frame_utc"] is None
