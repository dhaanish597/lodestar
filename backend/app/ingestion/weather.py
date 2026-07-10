"""Open-Meteo Marine sea-state connector, in-memory TTL cache. No API key
required (10k req/day free tier, docs/02 §6).

Verified reachable 2026-07-10 for the Hormuz bbox center (26.32, 56.25):
GET https://marine-api.open-meteo.com/v1/marine?latitude=26.32&longitude=56.25
&hourly=wave_height,... returned real hourly wave_height data.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# ASSUMPTION -> docs/02 §6, docs/04 §F. Forecast max wave height at/above this
# is flagged as disruption-relevant (X_weather=1); below it, X_weather=0.
WAVE_HEIGHT_THRESHOLD_M = 4.0

# The frontend polls /risk/{corridor} every 10s (RiskPanel.tsx). Without a
# TTL that's one real Open-Meteo call per poll. Hourly forecast data doesn't
# change meaningfully faster than this window.
WEATHER_CACHE_TTL_SECONDS = 1800.0


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    lat_min, lon_min, lat_max, lon_max = bbox
    return (lat_min + lat_max) / 2, (lon_min + lon_max) / 2


class WeatherCache:
    """TTL cache for one corridor's forecast max wave height -> X_weather."""

    def __init__(self, latitude: float, longitude: float, ttl: float = WEATHER_CACHE_TTL_SECONDS):
        self.latitude = latitude
        self.longitude = longitude
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float:
        now = time.monotonic()
        if self._last_fetch > 0 and now - self._last_fetch < self.ttl:
            return self._value

        try:
            response = await client.get(
                OPEN_METEO_MARINE_URL,
                params={
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "hourly": "wave_height,wind_wave_direction,swell_wave_period",
                    "forecast_days": 1,
                },
            )
            response.raise_for_status()
            heights = response.json().get("hourly", {}).get("wave_height", [])
            max_height = max(heights) if heights else 0.0

            self._value = 1.0 if max_height >= WAVE_HEIGHT_THRESHOLD_M else 0.0
            self._last_fetch = now
            logger.info("[OpenMeteo] wave_height_max=%.2fm -> X_weather=%.0f", max_height, self._value)
            return self._value
        except Exception as exc:
            logger.warning("[OpenMeteo] Fetch failed: %s — serving cached %.0f", exc, self._value)
            return self._value


class WeatherService:
    """Per-corridor WeatherCache, keyed on bbox center. Never raises."""

    def __init__(self, ttl: float = WEATHER_CACHE_TTL_SECONDS):
        self.ttl = ttl
        self._caches: dict[str, WeatherCache] = {}

    async def get_x_weather(
        self, client: httpx.AsyncClient, corridor: str, bbox: tuple[float, float, float, float]
    ) -> float:
        if corridor not in self._caches:
            lat, lon = _bbox_center(bbox)
            self._caches[corridor] = WeatherCache(latitude=lat, longitude=lon, ttl=self.ttl)
        return await self._caches[corridor].get(client)
