# backend/app/ingestion/gdelt.py
import httpx

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '(Hormuz OR "Red Sea") (attack OR strike OR sanction OR disruption)'
HORMUZ_BBOX = "25.27,55.16,27.37,57.34"


async def fetch_kinetic_volume(client: httpx.AsyncClient) -> float:
    """Fetch GDELT TimelineVol for the corridor and MinMax-scale the latest point into [0,1].

    STUB -> theme filtering (e.g. theme=CRISISLEX_CRISISLEXREC) noted in docs/02
    as a noise-reduction improvement; not applied in Phase 1 for query simplicity.
    """
    response = await client.get(
        GDELT_URL,
        params={
            "query": QUERY,
            "mode": "TimelineVol",
            "timespan": "72h",
            "format": "json",
            "bbox": HORMUZ_BBOX,
        },
    )
    response.raise_for_status()
    payload = response.json()
    timelines = payload.get("timeline", [])
    if not timelines:
        return 0.0
    points = timelines[0].get("data", [])
    if not points:
        return 0.0

    values = [p["value"] for p in points]
    lo, hi = min(values), max(values)
    if hi == lo:
        return 0.0
    return (values[-1] - lo) / (hi - lo)
