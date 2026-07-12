# backend/tests/test_recommendation_route.py
"""Full-pipeline test for GET /recommendation/{corridor}: exercises the real
agent pipeline (real graph execution, real node functions, real engine calls)
through the HTTP layer. Only the network boundary is mocked, reusing
test_agent_parity.py's _mock_handler shape (GDELT, AlphaVantage/EIA,
Open-Meteo), with STUB LLM (api_key="") and STUB sanctions (api_key="") so
results are deterministic and require no real network/API keys.
"""
import httpx
from fastapi.testclient import TestClient

from app.agents.llm_client import LLMClient
from app.agents.runner import AGENT_MODE
from app.config import get_settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.freight import FreightService
from app.ingestion.prices import PriceService
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService
from app.main import app

GDELT_RESPONSE = {"timeline": [{"data": [{"date": "20260701", "value": 3}, {"date": "20260702", "value": 6}]}]}


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "gdeltproject.org" in url:
        return httpx.Response(200, json=GDELT_RESPONSE)
    if "alphavantage.co" in url:
        return httpx.Response(200, json={"data": [{"date": "2026-07-01", "value": "76.20"}]})
    if "api.eia.gov" in url:
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}})
    if "marine-api.open-meteo.com" in url:
        return httpx.Response(200, json={"hourly": {"wave_height": [1.0, 2.0, 3.0]}})
    return httpx.Response(404)


def _app_with_agent_mocks() -> None:
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = CoverageMonitor(list(get_settings().ais_boxes))
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))
    app.state.freight_service = FreightService(fred_api_key="")
    app.state.price_service = PriceService(eia_api_key="k", alphavantage_api_key="k")
    app.state.sanctions_service = SanctionsService(api_key="")
    app.state.llm_client = LLMClient(api_key="", model="test-model")
    # Fresh instance: app.state.weather_service is a corridor-keyed cache with
    # a real 30-minute TTL, created once by main.py's lifespan guard and never
    # reset between tests. Using a dedicated instance here (instead of
    # whatever a previous test left behind) keeps this test deterministic.
    app.state.weather_service = WeatherService()


def test_recommendation_hormuz_returns_full_agent_pipeline():
    _app_with_agent_mocks()

    with TestClient(app) as client:
        resp = client.get("/recommendation/hormuz")

    # This test's mock returns a below-threshold wave height for "hormuz",
    # which would otherwise sit cached in app.state.weather_service (shared,
    # TTL'd, never auto-reset) and leak a stale non-live reading into a later
    # test file that expects a fresh live-threshold read for the same
    # corridor (test_routes.py::test_risk_hormuz_weather_and_freight_are_live_not_stub).
    # Reset so the next test's lifespan guard builds an unpolluted instance.
    app.state.weather_service = None

    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_mode"] == AGENT_MODE == "graph"
    assert body["corridor"] == "hormuz"
    assert body["risk"]["corridor"] == "hormuz"
    assert len(body["reroutes"]) == 6
    for field in (
        "market_narration", "logistics_narration", "macro_narration", "recommendation_narration",
    ):
        assert body[field].startswith("STUB —")


def test_recommendation_unknown_corridor_is_404():
    _app_with_agent_mocks()

    with TestClient(app) as client:
        resp = client.get("/recommendation/malacca")

    assert resp.status_code == 404
