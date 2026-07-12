# backend/tests/test_market_node.py
import httpx
import pytest

from app.agents.llm_client import LLMClient
from app.agents.market import run_market_node
from app.agents.state import AgentState
from app.ingestion.gdelt import fetch_kinetic_volume
from app.ingestion.prices import PriceService

GDELT_RESPONSE = {"timeline": [{"data": [{"date": "20260701", "value": 3}, {"date": "20260702", "value": 6}]}]}


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "gdeltproject.org" in url:
        return httpx.Response(200, json=GDELT_RESPONSE)
    if "alphavantage.co" in url:
        return httpx.Response(200, json={"data": [{"date": "2026-07-01", "value": "76.20"}]})
    if "api.eia.gov" in url:
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}})
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_run_market_node_stub_llm_passes_through_connector_values_exactly():
    price_service = PriceService(eia_api_key="k", alphavantage_api_key="k")
    llm = LLMClient(api_key="", model="x")  # no key -> has_key False -> STUB narration
    state: AgentState = {"corridor": "hormuz"}

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Independently invoke the real connector with the same mocked
        # transport/corridor to get ground truth, rather than assuming
        # fetch_kinetic_volume's redis-backed value in this environment.
        expected_kinetic = await fetch_kinetic_volume(client, corridor="hormuz")
        result = await run_market_node(state, client, price_service, llm)

    assert result["x_kinetic"] == expected_kinetic
    assert result["brent_price_usd_bbl"] == pytest.approx(76.20)  # mocked Alpha Vantage value, preferred over EIA
    assert result["market_narration"].startswith("STUB —")
    assert result["market_volatility_label"] == "STUB"
    assert result["price_spike_detected"] is False
    # Pre-existing state fields must be preserved (state is threaded, not replaced).
    assert result["corridor"] == "hormuz"


@pytest.mark.asyncio
async def test_run_market_node_parses_llm_classification_when_keyed(monkeypatch):
    async def fake_narrate(self, system_prompt, user_prompt):
        return "CLASSIFICATION: HIGH | true\nNARRATION: test"

    monkeypatch.setattr(LLMClient, "narrate", fake_narrate)

    price_service = PriceService(eia_api_key="k", alphavantage_api_key="k")
    llm = LLMClient(api_key="fake-key", model="x")  # has_key True -> classification is parsed
    state: AgentState = {"corridor": "hormuz"}

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await run_market_node(state, client, price_service, llm)

    assert result["market_narration"] == "CLASSIFICATION: HIGH | true\nNARRATION: test"
    assert result["market_volatility_label"] == "HIGH"
    assert result["price_spike_detected"] is True
