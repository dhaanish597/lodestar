# backend/app/ingestion/gdelt.py
"""GDELT TimelineVol connector with in-memory TTL cache and 429 handling.

GDELT's API enforces a rate limit of roughly 1 request per 5 seconds and
returns HTTP 429 when exceeded.  The ``GdeltCache`` wrapper ensures:
  - At most one real request per ``ttl`` seconds (default 120).
  - On a 429, any ``Retry-After`` header is respected before the next attempt.
  - The last good cached value is served while rate-limited or on error.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '(Hormuz OR "Red Sea") (attack OR strike OR sanction OR disruption)'
HORMUZ_BBOX = "25.27,55.16,27.37,57.34"


class GdeltCache:
    """In-memory TTL cache for a single GDELT TimelineVol query.

    Thread-/task-safe for a single asyncio event loop (which is the FastAPI
    model).  Not thread-safe across OS threads, but that isn't needed here.
    """

    def __init__(self, ttl: float = 120.0):
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0
        self._retry_after: float = 0.0  # earliest time we're allowed to retry

    async def get(self, client: httpx.AsyncClient) -> float:
        now = time.monotonic()

        # Honour Retry-After from a previous 429
        if now < self._retry_after:
            logger.debug(
                "[GDELT] Rate-limited, serving cached value %.4f (retry in %.1fs)",
                self._value, self._retry_after - now,
            )
            return self._value

        # TTL cache hit
        if now - self._last_fetch < self.ttl:
            return self._value

        # --- Actual fetch ---
        try:
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

            if response.status_code == 429:
                retry_secs = _parse_retry_after(response)
                self._retry_after = now + retry_secs
                logger.warning(
                    "[GDELT] 429 Too Many Requests — backing off %.0fs, serving cached %.4f",
                    retry_secs, self._value,
                )
                return self._value

            response.raise_for_status()

            payload = response.json()
            timelines = payload.get("timeline", [])
            if not timelines:
                logger.debug("[GDELT] Empty timeline array, serving cached %.4f", self._value)
                self._last_fetch = now
                return self._value

            points = timelines[0].get("data", [])
            if not points:
                logger.debug("[GDELT] Empty data array, serving cached %.4f", self._value)
                self._last_fetch = now
                return self._value

            values = [p["value"] for p in points]
            lo, hi = min(values), max(values)
            if hi == lo:
                val = 0.0
            else:
                val = (values[-1] - lo) / (hi - lo)

            self._value = val
            self._last_fetch = now
            logger.info("[GDELT] Fetched kinetic volume: %.4f  (points=%d)", val, len(values))
            return val

        except httpx.HTTPStatusError as exc:
            logger.warning("[GDELT] HTTP %d — serving cached %.4f", exc.response.status_code, self._value)
            return self._value
        except Exception as exc:
            logger.warning("[GDELT] Fetch failed: %s — serving cached %.4f", exc, self._value)
            return self._value


def _parse_retry_after(response: httpx.Response) -> float:
    """Extract seconds from a Retry-After header, defaulting to 10s."""
    raw = response.headers.get("Retry-After", "")
    try:
        return max(float(raw), 5.0)
    except (ValueError, TypeError):
        return 10.0


# ---- Module-level singleton used by the /risk route ----
_gdelt_cache = GdeltCache(ttl=120.0)


async def fetch_kinetic_volume(client: httpx.AsyncClient) -> float:
    """Public API consumed by routes.py — delegates to the singleton cache."""
    return await _gdelt_cache.get(client)
