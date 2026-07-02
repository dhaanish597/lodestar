from datetime import datetime, timedelta, timezone

from app.ingestion.dead_reckoning import apply_dead_reckoning
from app.models import Vessel


def _vessel(minutes_old: float, sog: float = 10.0, heading: float = 90.0) -> Vessel:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    return Vessel(mmsi=1, lat=26.0, lon=56.0, sog=sog, true_heading=heading, timestamp=ts)


def test_fresh_position_is_unchanged():
    v = _vessel(minutes_old=10)
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.lat == v.lat
    assert out.lon == v.lon
    assert out.signal_lost is False
    assert out.extrapolated is False


def test_stale_position_is_extrapolated_and_flagged():
    v = _vessel(minutes_old=181)  # > 2h
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.signal_lost is True
    assert out.extrapolated is True
    # heading 90 (due east) at nonzero speed moves lon east, lat ~unchanged
    assert out.lon > v.lon
    assert abs(out.lat - v.lat) < 0.05


def test_stale_but_stationary_vessel_does_not_move():
    v = _vessel(minutes_old=181, sog=0.0)
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.signal_lost is True
    assert out.lat == v.lat
    assert out.lon == v.lon


def test_stale_vessel_with_no_heading_data_does_not_move():
    """Vessel with no heading data (true_heading=None, cog=None) should not be extrapolated.

    Even though sog > 0, the lack of heading prevents dead reckoning.
    The position must remain frozen to avoid nonsensical extrapolation.
    """
    ts = datetime.now(timezone.utc) - timedelta(minutes=181)
    v = Vessel(mmsi=1, lat=26.0, lon=56.0, sog=10.0, true_heading=None, cog=None, timestamp=ts)
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.signal_lost is True
    assert out.extrapolated is True
    assert out.lat == v.lat
    assert out.lon == v.lon
