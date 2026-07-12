# backend/app/agents/macro.py
"""Macroeconomic Strategist node: feeds disruption_factor/substitution_rate/
hormuz_share and the live Brent price (from the Market node) into the
existing 5-step scenario cascade (engine/scenario.py). compute_scenario()
output is passed through verbatim -- the LLM only narrates.
"""
from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.engine.scenario import BRENT_BASELINE_USD_BBL, compute_scenario

MACRO_SYSTEM_PROMPT = (
    "You are a macroeconomic strategist for a crude oil-importing economy's "
    "procurement desk. You are given the output of a deterministic 5-step "
    "supply-shock cascade (supply gap, refinery utilization drop, SPR buffer "
    "days remaining, CPI, GDP, and CAD impact). Narrate the macroeconomic "
    "shock vector in 3-4 sentences for a policy briefing. Cite the actual "
    "numbers given -- never invent or round them yourself."
)


async def run_macro_node(state: AgentState, llm: LLMClient) -> AgentState:
    scenario = compute_scenario(
        corridor=state["corridor"],
        disruption_factor=state["disruption_factor"],
        substitution_rate=state["substitution_rate"],
        hormuz_share=state["hormuz_share"],
        brent_baseline_usd_bbl=state.get("brent_price_usd_bbl", BRENT_BASELINE_USD_BBL),
    )

    narration = await llm.narrate(
        MACRO_SYSTEM_PROMPT,
        f"Supply gap: {scenario.supply_gap_mbd:.3f} mb/d\n"
        f"Refinery utilization drop: {scenario.utilization_drop_pct:.1%}\n"
        f"SPR+OMC buffer days remaining: {scenario.days_cover_remaining:.1f}\n"
        f"CPI delta: +{scenario.cpi_delta_pp:.2f}pp\n"
        f"GDP drag: {scenario.gdp_drag_bps:.1f}bps\n"
        f"CAD widening: {scenario.cad_widening_pct_gdp:.2f}% of GDP",
    )

    return {**state, "scenario": scenario.model_dump(), "macro_narration": narration}
