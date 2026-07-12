# backend/tests/test_logistics_reading.py
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import get_settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import COVERAGE_WINDOW_SECONDS, CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.logistics_reading import compute_logistics_reading
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService
from app.models import Vessel

FLAGGED_MMSI = {111}


def _vessel(mmsi: int) -> Vessel:
    return Vessel(mmsi=mmsi, lat=26.0, lon=56.0, sog=10.0, timestamp=datetime.now(timezone.utc))


def _covered_coverage_monitor() -> CoverageMonitor:
    """Mirrors test_routes.py's covered_monitor pattern: subscribed and a
    frame seen inside the hormuz box just now -> state() == COVERED."""
    monitor = CoverageMonitor(list(get_settings().ais_boxes))
    now = datetime.now(timezone.utc)
    monitor.mark_subscribed(now=now)
    monitor.mark_frame("hormuz", now=now)
    return monitor


def _uncovered_coverage_monitor() -> CoverageMonitor:
    """Subscribed a full window ago with zero frames since -> state() ==
    NO_TERRESTRIAL_COVERAGE (see CoverageMonitor.state)."""
    monitor = CoverageMonitor(list(get_settings().ais_boxes))
    stale = datetime.now(timezone.utc) - timedelta(seconds=COVERAGE_WINDOW_SECONDS + 5)
    monitor.mark_subscribed(now=stale)
    return monitor


def _handler(sanctions_call_counter: list[int] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "marine-api.open-meteo.com" in url:
            return httpx.Response(200, json={"hourly": {"wave_height": [1.0, 2.0]}})
        if "api.opensanctions.org" in url:
            if sanctions_call_counter is not None:
                sanctions_call_counter[0] += 1
            payload = json.loads(request.read())
            responses = {}
            for key, q in payload["queries"].items():
                mmsi = int(q["properties"]["mmsi"][0])
                topics = ["sanction"] if mmsi in FLAGGED_MMSI else []
                results = [{"properties": {"topics": topics}}] if topics else []
                responses[key] = {"status": 200, "results": results}
            return httpx.Response(200, json={"responses": responses})
        return httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_covered_ais_without_sanctions_key_is_stub():
    called = [0]
    settings = get_settings()
    vessel_store = VesselStore()
    vessel_store.upsert(_vessel(111))
    density_tracker = DensityTracker(min_samples=1)
    coverage_monitor = _covered_coverage_monitor()
    weather_service = WeatherService()
    sanctions_service = SanctionsService(api_key="")

    transport = httpx.MockTransport(_handler(called))
    async with httpx.AsyncClient(transport=transport) as client:
        reading = await compute_logistics_reading(
            corridor="hormuz",
            http_client=client,
            settings=settings,
            vessel_store=vessel_store,
            density_tracker=density_tracker,
            coverage_monitor=coverage_monitor,
            weather_service=weather_service,
            sanctions_service=sanctions_service,
        )

    assert reading.density_state == "LIVE"
    assert reading.sanctions_state == "STUB"
    assert reading.x_sanctions == 0.0
    assert called[0] == 0


@pytest.mark.asyncio
async def test_covered_ais_with_sanctions_key_and_flagged_vessel_is_live():
    settings = get_settings()
    vessel_store = VesselStore()
    vessel_store.upsert(_vessel(111))  # flagged
    vessel_store.upsert(_vessel(222))  # clean
    density_tracker = DensityTracker(min_samples=1)
    coverage_monitor = _covered_coverage_monitor()
    weather_service = WeatherService()
    sanctions_service = SanctionsService(api_key="test-key")

    transport = httpx.MockTransport(_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        reading = await compute_logistics_reading(
            corridor="hormuz",
            http_client=client,
            settings=settings,
            vessel_store=vessel_store,
            density_tracker=density_tracker,
            coverage_monitor=coverage_monitor,
            weather_service=weather_service,
            sanctions_service=sanctions_service,
        )

    assert reading.density_state == "LIVE"
    assert reading.sanctions_state == "LIVE"
    assert reading.x_sanctions == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_uncovered_ais_voids_sanctions_without_calling_the_api():
    called = [0]
    settings = get_settings()
    vessel_store = VesselStore()
    vessel_store.upsert(_vessel(111))
    density_tracker = DensityTracker(min_samples=1)
    coverage_monitor = _uncovered_coverage_monitor()
    weather_service = WeatherService()
    # Sanctions key IS present -- proves the void is inherited from coverage,
    # not merely a "no key" STUB fallback.
    sanctions_service = SanctionsService(api_key="test-key")

    transport = httpx.MockTransport(_handler(called))
    async with httpx.AsyncClient(transport=transport) as client:
        reading = await compute_logistics_reading(
            corridor="hormuz",
            http_client=client,
            settings=settings,
            vessel_store=vessel_store,
            density_tracker=density_tracker,
            coverage_monitor=coverage_monitor,
            weather_service=weather_service,
            sanctions_service=sanctions_service,
        )

    assert reading.density_state == "NO_TERRESTRIAL_COVERAGE"
    assert reading.sanctions_state == reading.density_state
    assert reading.x_sanctions == 0.0
    assert called[0] == 0
