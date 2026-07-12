# backend/tests/test_macro_node.py
import pytest

from app.agents.llm_client import STUB_NARRATION, LLMClient
from app.agents.macro import run_macro_node
from app.agents.state import AgentState
from app.engine.scenario import compute_scenario

BASE_STATE: AgentState = {
    "corridor": "hormuz",
    "disruption_factor": 0.5,
    "substitution_rate": 0.2,
    "hormuz_share": 0.45,
    "brent_price_usd_bbl": 80.0,
}


@pytest.mark.asyncio
async def test_run_macro_node_stub_llm_matches_independent_compute_scenario_call():
    llm = LLMClient(api_key="", model="x")  # no key -> has_key False -> STUB narration
    state: AgentState = {**BASE_STATE}

    result = await run_macro_node(state, llm)

    # Independent cross-check: call the real engine function directly with the
    # same inputs and assert the node's output equals that call's result
    # exactly (not a re-implementation of the cascade under test).
    expected_scenario = compute_scenario(
        corridor="hormuz",
        disruption_factor=0.5,
        substitution_rate=0.2,
        hormuz_share=0.45,
        brent_baseline_usd_bbl=80.0,
    )

    assert result["scenario"] == expected_scenario.model_dump()
    assert result["macro_narration"] == STUB_NARRATION
    # Pre-existing state fields must be preserved (state is threaded, not replaced).
    assert result["corridor"] == "hormuz"
    assert result["disruption_factor"] == 0.5


@pytest.mark.asyncio
async def test_run_macro_node_uses_llm_narration_when_keyed(monkeypatch):
    async def fake_narrate(self, system_prompt, user_prompt):
        return "narrated macro text"

    monkeypatch.setattr(LLMClient, "narrate", fake_narrate)

    llm = LLMClient(api_key="fake-key", model="x")
    state: AgentState = {**BASE_STATE}

    result = await run_macro_node(state, llm)

    expected_scenario = compute_scenario(
        corridor="hormuz",
        disruption_factor=0.5,
        substitution_rate=0.2,
        hormuz_share=0.45,
        brent_baseline_usd_bbl=80.0,
    )

    assert result["scenario"] == expected_scenario.model_dump()
    assert result["macro_narration"] == "narrated macro text"
