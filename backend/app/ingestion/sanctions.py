# backend/app/ingestion/sanctions.py
"""OpenSanctions vessel screening connector, docs/02 §4. Screens every MMSI
observed in a corridor's AIS snapshot in one batched match-by-example
request: X_sanctions = flagged_vessels / observed_fleet.

Verified live 2026-07-12: /match/default accepts `properties.mmsi` directly
on the Vessel schema (not just imo), so AIS-observed MMSIs can be screened
without needing an IMO lookup.
"""
import asyncio
import logging
import time

import httpx

from app.models import Vessel

logger = logging.getLogger(__name__)

OPENSANCTIONS_URL = "https://api.opensanctions.org/match/default"

# ASSUMPTION -> mirrors weather.py's single-value TTL cache pattern (not a
# per-vessel cache -- corridor vessel sets are small and change every AIS
# frame, so caching the corridor-level ratio is simpler and sufficient).
# OpenSanctions publishes no documented rate cap for the free/non-commercial
# tier (docs/02 §4); this TTL exists to be a good API citizen against the
# frontend's 10s /risk/{corridor} poll, not because of a stated hard limit.
SANCTIONS_CACHE_TTL_SECONDS = 1800.0


class SanctionsCache:
    def __init__(self, api_key: str, ttl: float = SANCTIONS_CACHE_TTL_SECONDS):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0
        self._last_mmsi_set: frozenset[int] = frozenset()
        self._lock = asyncio.Lock()

    async def get(self, client: httpx.AsyncClient, vessels: list[Vessel]) -> float:
        if not self.api_key or not vessels:
            return 0.0

        mmsi_set = frozenset(v.mmsi for v in vessels)
        now = time.monotonic()
        if mmsi_set == self._last_mmsi_set and now - self._last_fetch < self.ttl:
            return self._value

        async with self._lock:
            # Re-check inside the lock: another coroutine may have already
            # refreshed the cache while this one was waiting.
            now = time.monotonic()
            if mmsi_set == self._last_mmsi_set and now - self._last_fetch < self.ttl:
                return self._value

            try:
                queries = {
                    f"q{i}": {"schema": "Vessel", "properties": {"mmsi": [str(v.mmsi)]}}
                    for i, v in enumerate(vessels)
                }
                response = await client.post(
                    OPENSANCTIONS_URL,
                    headers={"Authorization": f"ApiKey {self.api_key}"},
                    json={"queries": queries},
                )
                response.raise_for_status()
                responses = response.json().get("responses", {})
                flagged = 0
                for reply in responses.values():
                    results = reply.get("results", [])
                    if any("sanction" in r.get("properties", {}).get("topics", []) for r in results):
                        flagged += 1

                self._value = flagged / len(vessels)
                self._last_fetch = now
                self._last_mmsi_set = mmsi_set
                logger.info(
                    "[OpenSanctions] %d/%d observed vessels flagged -> X_sanctions=%.3f",
                    flagged, len(vessels), self._value,
                )
                return self._value
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[OpenSanctions] HTTP %d — serving cached %.3f", exc.response.status_code, self._value
                )
                return self._value
            except Exception as exc:
                logger.warning(
                    "[OpenSanctions] Fetch failed: %s — serving cached %.3f", type(exc).__name__, self._value
                )
                return self._value


class SanctionsService:
    """Thin wrapper mirroring FreightService/WeatherService's shape."""

    def __init__(self, api_key: str, ttl: float = SANCTIONS_CACHE_TTL_SECONDS):
        self._cache = SanctionsCache(api_key=api_key, ttl=ttl)

    async def get_x_sanctions(self, client: httpx.AsyncClient, vessels: list[Vessel]) -> float:
        return await self._cache.get(client, vessels)

    @property
    def has_key(self) -> bool:
        return bool(self._cache.api_key)
