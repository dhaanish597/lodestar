# backend/app/ingestion/coverage.py
"""Per-box AIS coverage state tracking.

AISStream is a terrestrial volunteer-receiver network (~15-20 nm line-of-sight).
Some subscribed boxes — empirically, the Strait of Hormuz / Persian Gulf as of
2026-07-05, see docs/03 "AIS coverage reality" — have NO receiving stations at
all. A vessel-density feature that silently reads ~0 in that situation is a
defensibility bug: absence of receivers is not absence of ships.

This module tracks, per subscribed bounding box, when the subscription started
and when the last AIS frame geolocated inside that box arrived, and derives an
explicit coverage state:

- ``WARMING_UP``               subscription younger than the window, no frames yet
- ``COVERED``                  at least one frame inside the box within the window
- ``NO_TERRESTRIAL_COVERAGE``  subscribed for a full window, zero frames inside

The risk engine consumes this state: a feature backed by an uncovered box is
excluded from the risk sum with the remaining weights renormalized (same
pattern as ``STUB`` features), and the UI badge says so out loud.
"""
from datetime import datetime, timedelta, timezone

# ASSUMPTION -> docs/04 §A: empirical floor. In the 2026-07-05 diagnostic matrix
# (scripts/diag_aisstream.py), every box with any coverage produced its first
# frame in <1s; Hormuz produced zero frames in 5+ minutes across repeated runs.
# 10 minutes of silence is therefore a conservative "no receivers here" signal.
COVERAGE_WINDOW_SECONDS = 600

COVERED = "COVERED"
WARMING_UP = "WARMING_UP"
NO_TERRESTRIAL_COVERAGE = "NO_TERRESTRIAL_COVERAGE"


class CoverageMonitor:
    """Tracks last-frame-received time per subscribed AIS bounding box."""

    def __init__(self, box_names: list[str], window_seconds: int = COVERAGE_WINDOW_SECONDS):
        self._window = timedelta(seconds=window_seconds)
        self._subscribed_at: dict[str, datetime | None] = {name: None for name in box_names}
        self._last_frame_at: dict[str, datetime | None] = {name: None for name in box_names}
        self.frame_counts: dict[str, int] = {name: 0 for name in box_names}

    def mark_subscribed(self, now: datetime | None = None) -> None:
        """Call on every (re)subscription; restarts the warm-up clock for boxes
        that have never produced a frame, without erasing frame history."""
        now = now or datetime.now(timezone.utc)
        for name in self._subscribed_at:
            self._subscribed_at[name] = now

    def mark_frame(self, box_name: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._last_frame_at[box_name] = now
        self.frame_counts[box_name] = self.frame_counts.get(box_name, 0) + 1

    def state(self, box_name: str, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        last_frame = self._last_frame_at.get(box_name)
        if last_frame is not None and now - last_frame <= self._window:
            return COVERED
        subscribed = self._subscribed_at.get(box_name)
        if subscribed is None or now - subscribed < self._window:
            # Not yet subscribed, or subscribed less than a full window ago —
            # too early to declare a coverage void.
            return WARMING_UP
        return NO_TERRESTRIAL_COVERAGE

    def snapshot(self, now: datetime | None = None) -> dict[str, dict]:
        now = now or datetime.now(timezone.utc)
        return {
            name: {
                "state": self.state(name, now),
                "frames": self.frame_counts.get(name, 0),
                "last_frame_utc": lf.isoformat() if (lf := self._last_frame_at.get(name)) else None,
            }
            for name in self._subscribed_at
        }
