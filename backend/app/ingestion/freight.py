"""FRED freight-stress connector, in-memory TTL cache.

docs/02 §7 specifies BCTI/BDI as the target series. Verified live 2026-07-10
via FRED's series-search API that neither exists as a FRED series -- the
Baltic Exchange does not license them to FRED. The nearest live substitute,
also verified reachable with current data (through 2026-05):
  WPU301301 "Producer Price Index by Commodity: Transportation Services:
  Deep Sea Water Transportation of Freight" (monthly, BLS via FRED).
This is a LIVE connector on a real substitute series, not the static-stub
fallback docs/02 §7 sanctions for a genuinely unreachable feed -- flagged
here because it substitutes the specifically-named series.
"""
import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

# STUB -> BCTI/BDI unavailable on FRED (verified 2026-07-10); substitute a
# live series. ASSUMPTION: PPI for deep-sea freight transport is a defensible
# systemic ocean-freight-cost proxy, though not a tanker spot index like BCTI.
FREIGHT_SERIES_ID = "WPU301301"

# The series is monthly, not daily, so docs/02 §7's literal "90-day baseline"
# becomes "the ~3 monthly prints preceding the latest one". ASSUMPTION.
N_BASELINE_MONTHS = 3

# ASSUMPTION -> maps pct deviation from baseline onto the risk engine's [0,1]
# feature convention: a deviation at/beyond this magnitude reads as full
# freight stress (X_freight=1.0).
FREIGHT_STRESS_SCALE_PCT = 15.0

# ASSUMPTION -> cache TTL, not a modeling constant. The underlying FRED
# series is monthly, so an hour of staleness is immaterial; this just
# bounds how often the risk endpoint's 10s frontend poll triggers a real
# FRED request.
FREIGHT_CACHE_TTL_SECONDS = 3600.0


class FreightCache:
    def __init__(self, api_key: str, ttl: float = FREIGHT_CACHE_TTL_SECONDS):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self, client: httpx.AsyncClient) -> float:
        if not self.api_key:
            return 0.0

        now = time.monotonic()
        if self._last_fetch > 0 and now - self._last_fetch < self.ttl:
            return self._value

        async with self._lock:
            # Re-check inside the lock: another coroutine may have already
            # refreshed the cache while this one was waiting.
            now = time.monotonic()
            if self._last_fetch > 0 and now - self._last_fetch < self.ttl:
                return self._value

            try:
                response = await client.get(
                    FRED_URL,
                    params={
                        "series_id": FREIGHT_SERIES_ID,
                        "api_key": self.api_key,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": N_BASELINE_MONTHS + 1,
                    },
                )
                response.raise_for_status()
                observations = response.json().get("observations", [])
                values = [float(o["value"]) for o in observations if o.get("value") not in (None, ".")]
                if len(values) < 2:
                    logger.debug("[FRED] Not enough observations, serving cached %.3f", self._value)
                    return self._value

                latest, baseline_points = values[0], values[1:]
                baseline = sum(baseline_points) / len(baseline_points)
                pct_deviation = ((latest - baseline) / baseline) * 100 if baseline else 0.0

                self._value = max(0.0, min(1.0, abs(pct_deviation) / FREIGHT_STRESS_SCALE_PCT))
                self._last_fetch = now
                logger.info(
                    "[FRED] %s latest=%.2f baseline=%.2f deviation=%.1f%% -> X_freight=%.3f",
                    FREIGHT_SERIES_ID, latest, baseline, pct_deviation, self._value,
                )
                return self._value
            except httpx.HTTPStatusError as exc:
                # Don't interpolate the raw exception -- its str() embeds the
                # full request URL, which includes api_key=<the real FRED key>.
                logger.warning("[FRED] HTTP %d — serving cached %.3f", exc.response.status_code, self._value)
                return self._value
            except Exception as exc:
                logger.warning("[FRED] Fetch failed: %s — serving cached %.3f", type(exc).__name__, self._value)
                return self._value


class FreightService:
    """Thin wrapper so main.py/routes.py mirror WeatherService/PriceService shape."""

    def __init__(self, fred_api_key: str, ttl: float = FREIGHT_CACHE_TTL_SECONDS):
        self._cache = FreightCache(api_key=fred_api_key, ttl=ttl)

    async def get_x_freight(self, client: httpx.AsyncClient) -> float:
        return await self._cache.get(client)

    @property
    def has_key(self) -> bool:
        """Whether this instance actually has a FRED API key -- used by the
        route layer to label feature_states LIVE vs STUB without touching
        Settings directly (tests inject FreightService with an explicit key,
        bypassing Settings entirely; see docs/03 Task 3 / commit 20ca6d5)."""
        return bool(self._cache.api_key)
