# backend/tests/test_agent_parity.py
"""Graph vs sequential parity: Step 4 of the Phase 3 prompt requires proof
that both execution paths produce identical engine-derived numeric output
for the same input. Narration text may differ in wording; every other
field must match exactly. Uses STUB LLM (api_key="") and STUB sanctions
(api_key="") so both runs are fully deterministic -- no real network calls.

`compute_risk()` (app/engine/risk.py) stamps `RiskScore.timestamp` with
`datetime.now(timezone.utc)` when the orchestrator node doesn't pass `now=`
(it doesn't). Two independent full-pipeline runs -- one via run_graph, one
via run_sequential -- land at genuinely different wall-clock instants, so
without freezing time the `risk` dict's `timestamp` field would differ
between the two runs even though every other field is identical. Freeze
app.engine.risk's `datetime` name the same way test_orchestrator_node.py
does, so both runs' compute_risk() calls stamp the same instant.
"""
from datetime import datetime, timezone

import httpx
import pytest

import app.engine.risk as risk_module
from app.agents.deps import AgentDeps
from app.agents.graph import run_graph
from app.agents.llm_client import LLMClient
from app.agents.sequential import run_sequential
from app.config import get_settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.freight import FreightService
from app.ingestion.prices import PriceService
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService

GDELT_RESPONSE = {"timeline": [{"data": [{"date": "20260701", "value": 3}, {"date": "20260702", "value": 6}]}]}

FIXED_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


NUMERIC_FIELDS = [
    "x_kinetic", "brent_price_usd_bbl", "market_volatility_label", "price_spike_detected",
    "x_density", "density_state", "x_sanctions", "sanctions_state", "x_weather",
    "scenario", "risk", "reroutes",
]


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


def _build_deps() -> AgentDeps:
    return AgentDeps(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler)),
        settings=get_settings(),
        vessel_store=VesselStore(),
        density_tracker=DensityTracker(min_samples=1),
        coverage_monitor=CoverageMonitor(list(get_settings().ais_boxes)),
        weather_service=WeatherService(),
        sanctions_service=SanctionsService(api_key=""),
        freight_service=FreightService(fred_api_key=""),
        price_service=PriceService(eia_api_key="k", alphavantage_api_key="k"),
        llm=LLMClient(api_key="", model="test-model"),
    )


@pytest.mark.asyncio
async def test_graph_and_sequential_produce_identical_engine_output(monkeypatch):
    monkeypatch.setattr(risk_module, "datetime", _FixedDatetime)

    graph_result = await run_graph(_build_deps(), "hormuz", 0.5, 0.2, 0.45)
    sequential_result = await run_sequential(_build_deps(), "hormuz", 0.5, 0.2, 0.45)

    for field in NUMERIC_FIELDS:
        assert graph_result[field] == sequential_result[field], f"{field} mismatch"

    for key in ("market_narration", "logistics_narration", "macro_narration", "recommendation_narration"):
        assert key in graph_result and key in sequential_result
