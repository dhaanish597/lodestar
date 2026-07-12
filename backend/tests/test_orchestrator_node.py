# backend/tests/test_orchestrator_node.py
from datetime import datetime, timezone

import httpx
import pytest

import app.engine.risk as risk_module
from app.agents.llm_client import LLMClient
from app.agents.orchestrator import run_orchestrator_node
from app.agents.state import AgentState
from app.config import get_settings
from app.engine.reroute import rank_reroutes
from app.engine.risk import compute_risk
from app.ingestion.freight import FreightService

# compute_risk() stamps RiskScore.timestamp with datetime.now(timezone.utc)
# when the caller doesn't supply `now` (the orchestrator node doesn't). Two
# back-to-back real datetime.now() calls frequently land in different
# microseconds, which would make the byte-for-byte dict-equality assertions
# below flaky. Freeze app.engine.risk's `datetime` name so both the node's
# internal compute_risk() call and the test's independent one stamp the same
# instant.
FIXED_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


def _no_requests_expected(request: httpx.Request) -> httpx.Response:
    # FreightService(fred_api_key="") returns 0.0 without any HTTP call (no
    # key -> early return) -- any request reaching this handler is a bug.
    raise AssertionError(f"unexpected HTTP request: {request.url}")


BASE_STATE: AgentState = {
    "corridor": "hormuz",
    "disruption_factor": 0.3,
    "brent_price_usd_bbl": 75.0,
    "x_kinetic": 0.3,
    "x_density": 0.2,
    "density_state": "LIVE",
    "x_sanctions": 0.1,
    "sanctions_state": "LIVE",
    "x_weather": 0.0,
}


def _expected_risk_and_reroutes():
    expected_risk = compute_risk(
        corridor="hormuz",
        x_kinetic=0.3,
        x_density=0.2,
        x_sanctions=0.1,
        x_weather=0.0,
        x_freight=0.0,
        feature_states={
            "density": "LIVE",
            "sanctions": "LIVE",
            "weather": "LIVE",
            "freight": "STUB",
        },
    )
    expected_reroutes = rank_reroutes(
        disruption_factor=0.3,
        brent_price_usd_bbl=75.0,
        grades=get_settings().crude_grades,
    )
    return expected_risk, expected_reroutes


@pytest.mark.asyncio
async def test_run_orchestrator_node_stub_llm_matches_independent_engine_calls(monkeypatch):
    monkeypatch.setattr(risk_module, "datetime", _FixedDatetime)

    freight_service = FreightService(fred_api_key="")  # no key -> STUB, deterministic 0.0
    llm = LLMClient(api_key="", model="x")  # no key -> STUB narration
    state: AgentState = {**BASE_STATE}

    transport = httpx.MockTransport(_no_requests_expected)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await run_orchestrator_node(state, client, freight_service, llm)

    # Independent cross-check: call the real engine functions directly with
    # the same inputs and assert the node's output equals those calls'
    # results exactly (not a re-implementation of risk/reroute logic).
    expected_risk, expected_reroutes = _expected_risk_and_reroutes()

    assert result["risk"] == expected_risk.model_dump()
    assert result["reroutes"] == [r.model_dump() for r in expected_reroutes]
    assert result["recommendation_narration"].startswith("STUB —")
    # Pre-existing state fields must be preserved (state is threaded, not replaced).
    assert result["corridor"] == "hormuz"


@pytest.mark.asyncio
async def test_run_orchestrator_node_uses_llm_narration_when_keyed(monkeypatch):
    monkeypatch.setattr(risk_module, "datetime", _FixedDatetime)

    async def fake_narrate(self, system_prompt, user_prompt):
        return "narrated executive recommendation"

    monkeypatch.setattr(LLMClient, "narrate", fake_narrate)

    freight_service = FreightService(fred_api_key="")
    llm = LLMClient(api_key="fake-key", model="x")
    state: AgentState = {**BASE_STATE}

    transport = httpx.MockTransport(_no_requests_expected)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await run_orchestrator_node(state, client, freight_service, llm)

    expected_risk, expected_reroutes = _expected_risk_and_reroutes()

    assert result["risk"] == expected_risk.model_dump()
    assert result["reroutes"] == [r.model_dump() for r in expected_reroutes]
    assert result["recommendation_narration"] == "narrated executive recommendation"
