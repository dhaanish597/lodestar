# backend/tests/test_routes.py
import httpx
import pytest
from fastapi.testclient import TestClient

from datetime import datetime, timezone

from app.config import get_settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.prices import PriceService
from app.main import app

GDELT_RESPONSE = {"timeline": [{"data": [{"date": "20260701", "value": 3}, {"date": "20260702", "value": 6}]}]}


def _fresh_coverage_monitor() -> CoverageMonitor:
    return CoverageMonitor(list(get_settings().ais_boxes))


def test_risk_hormuz_returns_full_breakdown(monkeypatch):
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["corridor"] == "hormuz"
    assert set(body["contributions"]) == {"kinetic", "density", "sanctions", "weather", "freight"}
    assert set(body["feature_states"]) == set(body["contributions"])


def test_risk_hormuz_density_state_reflects_coverage(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=GDELT_RESPONSE)

    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # Fresh monitor with no subscription/frames → density must be WARMING_UP,
    # never a silent LIVE zero.
    app.state.coverage_monitor = _fresh_coverage_monitor()
    with TestClient(app) as client:
        warming = client.get("/risk/hormuz").json()
    assert warming["feature_states"]["density"] == "WARMING_UP"
    assert warming["contributions"]["density"] == 0.0

    # Monitor that has seen a Hormuz frame just now → density is LIVE.
    covered_monitor = _fresh_coverage_monitor()
    covered_monitor.mark_subscribed(now=datetime.now(timezone.utc))
    covered_monitor.mark_frame("hormuz", now=datetime.now(timezone.utc))
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = covered_monitor
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        live = client.get("/risk/hormuz").json()
    assert live["feature_states"]["density"] == "LIVE"


def test_coverage_endpoint_reports_every_configured_box():
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient()

    with TestClient(app) as client:
        resp = client.get("/coverage")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == set(get_settings().ais_boxes)
    for box in body.values():
        assert {"state", "frames", "last_frame_utc"} <= set(box)


def test_risk_unknown_corridor_is_404():
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient()

    with TestClient(app) as client:
        resp = client.get("/risk/malacca")

    assert resp.status_code == 404


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "gdeltproject.org" in url:
        return httpx.Response(200, json=GDELT_RESPONSE)
    if "alphavantage.co" in url:
        return httpx.Response(200, json={"data": [{"date": "2026-07-01", "value": "76.20"}]})
    if "api.eia.gov" in url:
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}})
    if "marine-api.open-meteo.com" in url:
        return httpx.Response(200, json={"hourly": {"wave_height": [1.0, 4.5, 2.0]}})
    if "api.stlouisfed.org" in url:
        return httpx.Response(200, json={"observations": [
            {"date": "2026-05-01", "value": "130.0"},
            {"date": "2026-04-01", "value": "100.0"},
            {"date": "2026-03-01", "value": "100.0"},
            {"date": "2026-02-01", "value": "100.0"},
        ]})
    return httpx.Response(404)


def test_risk_hormuz_weather_and_freight_are_live_not_stub():
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    body = resp.json()
    assert body["feature_states"]["weather"] == "LIVE"
    assert body["feature_states"]["freight"] == "LIVE"
    assert body["feature_states"]["sanctions"] == "STUB"  # no OPENSANCTIONS_API_KEY
    # mocked wave_height max 4.5m >= 4.0m threshold -> X_weather=1 -> nonzero contribution
    assert body["features"]["weather"] == 1.0
    assert body["contributions"]["weather"] > 0.0
    # mocked FRED: latest 130 vs baseline avg 100 -> +30% deviation -> clipped to 1.0
    assert body["features"]["freight"] == pytest.approx(1.0)


def _app_with_mocks() -> None:
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))
    app.state.price_service = PriceService(eia_api_key="k", alphavantage_api_key="k")


def test_scenario_hormuz_returns_full_cascade():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/scenario/hormuz", params={"disruption_factor": 0.5})

    assert resp.status_code == 200
    body = resp.json()
    assert body["corridor"] == "hormuz"
    assert body["disruption_factor"] == 0.5
    assert body["supply_gap_mbd"] > 0
    assert "crude_price_rise_pct" in body


def test_scenario_disruption_factor_changes_supply_gap():
    _app_with_mocks()
    with TestClient(app) as client:
        low = client.get("/scenario/hormuz", params={"disruption_factor": 0.1}).json()
        high = client.get("/scenario/hormuz", params={"disruption_factor": 0.8}).json()

    assert high["supply_gap_mbd"] > low["supply_gap_mbd"]


def test_scenario_unknown_corridor_is_404():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/scenario/malacca")

    assert resp.status_code == 404


def test_reroute_hormuz_returns_ranked_options_with_grade_match():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/reroute/hormuz", params={"disruption_factor": 0.3})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 6
    scores = [o["score"] for o in body]
    assert scores == sorted(scores, reverse=True)
    merey = next(o for o in body if o["source_grade"] == "Merey")
    assert merey["grade_match"] == 0.0


def test_reroute_disruption_factor_changes_ranking_live():
    _app_with_mocks()
    with TestClient(app) as client:
        low = client.get("/reroute/hormuz", params={"disruption_factor": 0.0}).json()
        high = client.get("/reroute/hormuz", params={"disruption_factor": 1.0}).json()

    low_scores = {o["source_grade"]: o["score"] for o in low}
    high_scores = {o["source_grade"]: o["score"] for o in high}
    assert low_scores != high_scores


def test_reroute_unknown_corridor_is_404():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/reroute/malacca")

    assert resp.status_code == 404
