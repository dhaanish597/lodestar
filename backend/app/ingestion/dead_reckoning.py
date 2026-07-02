import math
from datetime import datetime, timedelta

from app.models import Vessel

STALE_THRESHOLD = timedelta(hours=2)
EARTH_RADIUS_NM = 3440.065


def _project(lat_deg: float, lon_deg: float, bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    lat1 = math.radians(lat_deg)
    lon1 = math.radians(lon_deg)
    bearing = math.radians(bearing_deg)
    d_r = distance_nm / EARTH_RADIUS_NM

    lat2 = math.asin(math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(bearing))
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def apply_dead_reckoning(vessel: Vessel, now: datetime) -> Vessel:
    age = now - vessel.timestamp
    if age <= STALE_THRESHOLD:
        return vessel

    heading = vessel.true_heading if vessel.true_heading is not None else vessel.cog
    if heading is None or vessel.sog <= 0:
        return vessel.model_copy(update={"signal_lost": True, "extrapolated": True})

    hours = age.total_seconds() / 3600
    distance_nm = vessel.sog * hours
    new_lat, new_lon = _project(vessel.lat, vessel.lon, heading, distance_nm)
    return vessel.model_copy(update={"lat": new_lat, "lon": new_lon, "signal_lost": True, "extrapolated": True})
