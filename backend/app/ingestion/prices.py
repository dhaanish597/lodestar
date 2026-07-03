"""EIA (weekly baseline) + Alpha Vantage (cached intraday) Brent price connectors.

Alpha Vantage free tier caps at 25 requests/day (docs/02 §5). The
AlphaVantageCache TTL (3600s) guarantees at most one real outbound call per
hour regardless of how often the frontend polls -- 24 calls/day max, safely
under the cap, and never triggered directly by a page load. EIA spot prices
publish weekly (~Tuesdays) per docs/02 §2, so it serves as the fallback
baseline when Alpha Vantage is unset or unreachable.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

EIA_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"

# ASSUMPTION -> served only if both EIA and Alpha Vantage are unset/unreachable
# (e.g. no keys configured in a fresh dev environment). docs/04 §B.
BRENT_FALLBACK_USD_BBL = 75.0


class EiaCache:
    """TTL cache for EIA daily Brent spot price (weekly-cadence data, key required)."""

    def __init__(self, api_key: str, ttl: float = 3600.0):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float | None = None
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float | None:
        if not self.api_key:
            return None

        now = time.monotonic()
        if now - self._last_fetch < self.ttl and self._value is not None:
            return self._value

        try:
            response = await client.get(
                EIA_URL,
                params={
                    "api_key": self.api_key,
                    "frequency": "daily",
                    "data[]": "value",
                    "facets[series][]": "DCOILBRENTEU",
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": 5,
                },
            )
            response.raise_for_status()
            rows = response.json()["response"]["data"]
            if not rows:
                logger.debug("[EIA] Empty data array, serving cached %s", self._value)
                return self._value

            self._value = float(rows[0]["value"])
            self._last_fetch = now
            logger.info("[EIA] Fetched Brent baseline: %.2f", self._value)
            return self._value
        except Exception as exc:
            logger.warning("[EIA] Fetch failed: %s — serving cached %s", exc, self._value)
            return self._value


class AlphaVantageCache:
    """TTL cache for Alpha Vantage Brent quote. Mandatory 1-hour TTL -> 25 req/day cap."""

    def __init__(self, api_key: str, ttl: float = 3600.0):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float | None = None
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float | None:
        if not self.api_key:
            return None

        now = time.monotonic()
        if now - self._last_fetch < self.ttl and self._value is not None:
            return self._value

        try:
            response = await client.get(
                ALPHAVANTAGE_URL,
                params={"function": "BRENT", "interval": "daily", "apikey": self.api_key},
            )
            response.raise_for_status()
            rows = response.json().get("data", [])
            if not rows:
                logger.debug("[AlphaVantage] Empty data array, serving cached %s", self._value)
                return self._value

            self._value = float(rows[0]["value"])
            self._last_fetch = now
            logger.info("[AlphaVantage] Fetched Brent intraday: %.2f", self._value)
            return self._value
        except Exception as exc:
            logger.warning("[AlphaVantage] Fetch failed: %s — serving cached %s", exc, self._value)
            return self._value


class PriceService:
    """Orchestrates Alpha Vantage (preferred, intraday-ish) with EIA (weekly
    baseline) and a static fallback -- never raises, always returns a usable price."""

    def __init__(self, eia_api_key: str, alphavantage_api_key: str):
        self.eia_cache = EiaCache(api_key=eia_api_key)
        self.alphavantage_cache = AlphaVantageCache(api_key=alphavantage_api_key)

    async def get_brent_price(self, client: httpx.AsyncClient) -> float:
        alphavantage_value = await self.alphavantage_cache.get(client)
        if alphavantage_value is not None:
            return alphavantage_value

        eia_value = await self.eia_cache.get(client)
        if eia_value is not None:
            return eia_value

        logger.warning(
            "[PriceService] No live price available, serving fallback %.2f", BRENT_FALLBACK_USD_BBL
        )
        return BRENT_FALLBACK_USD_BBL
