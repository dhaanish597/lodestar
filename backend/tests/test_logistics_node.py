# backend/tests/test_logistics_node.py
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.agents.llm_client import LLMClient
from app.agents.logistics import run_logistics_node
from app.agents.state import AgentState
from app.config import get_settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.logistics_reading import compute_logistics_reading
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService
from app.models import Vessel

FLAGGED_MMSI = {111}


def _vessel(mmsi: int) -> Vessel:
    return Vessel(mmsi=mmsi, lat=26.0, lon=56.0, sog=10.0, timestamp=datetime.now(timezone.utc))


def _covered_coverage_monitor() -> CoverageMonitor:
    """Mirrors test_logistics_reading.py's covered_monitor pattern: subscribed
    and a frame seen inside the hormuz box just now -> state() == COVERED."""
    monitor = CoverageMonitor(list(get_settings().ais_boxes))
    now = datetime.now(timezone.utc)
    monitor.mark_subscribed(now=now)
    monitor.mark_frame("hormuz", now=now)
    return monitor


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "marine-api.open-meteo.com" in url:
        return httpx.Response(200, json={"hourly": {"wave_height": [1.0, 4.5, 2.0]}})
    if "api.opensanctions.org" in url:
        payload = json.loads(request.read())
        responses = {}
        for key, q in payload["queries"].items():
            mmsi = int(q["properties"]["mmsi"][0])
            topics = ["sanction"] if mmsi in FLAGGED_MMSI else []
            results = [{"properties": {"topics": topics}}] if topics else []
            responses[key] = {"status": 200, "results": results}
        return httpx.Response(200, json={"responses": responses})
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_run_logistics_node_matches_compute_logistics_reading_and_is_stub_narration():
    settings = get_settings()
    vessel_store = VesselStore()
    vessel_store.upsert(_vessel(111))
    density_tracker = DensityTracker(min_samples=1)
    coverage_monitor = _covered_coverage_monitor()
    weather_service = WeatherService()
    sanctions_service = SanctionsService(api_key="")  # no key -> STUB sanctions state
    llm = LLMClient(api_key="", model="x")  # no key -> STUB narration
    state: AgentState = {"corridor": "hormuz"}

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await run_logistics_node(
            state,
            client,
            settings,
            vessel_store,
            density_tracker,
            coverage_monitor,
            weather_service,
            sanctions_service,
            llm,
        )

    # Independent cross-check: call compute_logistics_reading directly with a
    # freshly-constructed, identically-configured set of mocked inputs and
    # assert the node's engine-derived fields equal that call's result exactly
    # (not a re-implementation of the logic under test).
    check_vessel_store = VesselStore()
    check_vessel_store.upsert(_vessel(111))
    check_density_tracker = DensityTracker(min_samples=1)
    check_coverage_monitor = _covered_coverage_monitor()
    check_weather_service = WeatherService()
    check_sanctions_service = SanctionsService(api_key="")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as check_client:
        expected = await compute_logistics_reading(
            corridor="hormuz",
            http_client=check_client,
            settings=settings,
            vessel_store=check_vessel_store,
            density_tracker=check_density_tracker,
            coverage_monitor=check_coverage_monitor,
            weather_service=check_weather_service,
            sanctions_service=check_sanctions_service,
        )

    assert result["x_density"] == expected.x_density
    assert result["density_state"] == expected.density_state
    assert result["x_sanctions"] == expected.x_sanctions
    assert result["sanctions_state"] == expected.sanctions_state
    assert result["x_weather"] == expected.x_weather
    assert result["logistics_narration"].startswith("STUB —")
    # Pre-existing state fields must be preserved (state is threaded, not replaced).
    assert result["corridor"] == "hormuz"


@pytest.mark.asyncio
async def test_run_logistics_node_live_sanctions_matches_reading_and_uses_llm_narration(monkeypatch):
    async def fake_narrate(self, system_prompt, user_prompt):
        return "narrated logistics text"

    monkeypatch.setattr(LLMClient, "narrate", fake_narrate)

    settings = get_settings()
    vessel_store = VesselStore()
    vessel_store.upsert(_vessel(111))  # flagged
    vessel_store.upsert(_vessel(222))  # clean
    density_tracker = DensityTracker(min_samples=1)
    coverage_monitor = _covered_coverage_monitor()
    weather_service = WeatherService()
    sanctions_service = SanctionsService(api_key="test-key")  # keyed -> LIVE sanctions state
    llm = LLMClient(api_key="fake-key", model="x")
    state: AgentState = {"corridor": "hormuz"}

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await run_logistics_node(
            state,
            client,
            settings,
            vessel_store,
            density_tracker,
            coverage_monitor,
            weather_service,
            sanctions_service,
            llm,
        )

    check_vessel_store = VesselStore()
    check_vessel_store.upsert(_vessel(111))
    check_vessel_store.upsert(_vessel(222))
    check_density_tracker = DensityTracker(min_samples=1)
    check_coverage_monitor = _covered_coverage_monitor()
    check_weather_service = WeatherService()
    check_sanctions_service = SanctionsService(api_key="test-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as check_client:
        expected = await compute_logistics_reading(
            corridor="hormuz",
            http_client=check_client,
            settings=settings,
            vessel_store=check_vessel_store,
            density_tracker=check_density_tracker,
            coverage_monitor=check_coverage_monitor,
            weather_service=check_weather_service,
            sanctions_service=check_sanctions_service,
        )

    assert result["sanctions_state"] == expected.sanctions_state == "LIVE"
    assert result["x_sanctions"] == expected.x_sanctions == pytest.approx(0.5)
    assert result["logistics_narration"] == "narrated logistics text"
