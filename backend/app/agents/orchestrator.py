# backend/app/agents/orchestrator.py
"""Executive Orchestrator node: synthesizes Market + Logistics + Macro reads
into the final risk score (engine/risk.py) and ranked reroute plan
(engine/reroute.py), then has the LLM narrate the executive recommendation.
Both compute_risk() and rank_reroutes() output are passed through verbatim.
Freight (FRED) is fetched here, not in an earlier node -- it's not one of
the three agents' documented inputs but is required by compute_risk().
"""
import httpx

from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.config import get_settings
from app.engine.reroute import rank_reroutes
from app.engine.risk import compute_risk
from app.engine.scenario import BRENT_BASELINE_USD_BBL
from app.ingestion.freight import FreightService

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the executive orchestrator synthesizing a crude-procurement "
    "recommendation for a refiner's leadership team. You are given a "
    "corridor's disruption-risk score with per-feature contributions, and a "
    "ranked list of alternative crude sources with landed cost, grade "
    "compatibility, and MCDM score. Write a 3-5 sentence executive "
    "recommendation: state the top-ranked alternative, why it wins (cost, "
    "grade compatibility, or both), and the corridor risk level driving the "
    "urgency. Cite only the numbers given -- never invent a ranking or score."
)


async def run_orchestrator_node(
    state: AgentState,
    http_client: httpx.AsyncClient,
    freight_service: FreightService,
    llm: LLMClient,
) -> AgentState:
    corridor = state["corridor"]
    x_freight = await freight_service.get_x_freight(http_client)
    freight_state = "LIVE" if freight_service.has_key else "STUB"

    risk = compute_risk(
        corridor=corridor,
        x_kinetic=state["x_kinetic"],
        x_density=state["x_density"],
        x_sanctions=state["x_sanctions"],
        x_weather=state["x_weather"],
        x_freight=x_freight,
        feature_states={
            "density": state["density_state"],
            "sanctions": state["sanctions_state"],
            "weather": "LIVE",
            "freight": freight_state,
        },
    )

    grades = get_settings().crude_grades
    reroutes = rank_reroutes(
        disruption_factor=state["disruption_factor"],
        brent_price_usd_bbl=state.get("brent_price_usd_bbl", BRENT_BASELINE_USD_BBL),
        grades=grades,
    )

    top, runner_up = reroutes[0], reroutes[1]
    narration = await llm.narrate(
        ORCHESTRATOR_SYSTEM_PROMPT,
        f"Corridor risk: {risk.probability:.1%} "
        f"(kinetic={risk.contributions['kinetic']:.3f}, density={risk.contributions['density']:.3f}, "
        f"sanctions={risk.contributions['sanctions']:.3f}, weather={risk.contributions['weather']:.3f}, "
        f"freight={risk.contributions['freight']:.3f})\n"
        f"Top-ranked alternative: {top.source_grade} ({top.origin}), score {top.score:.4f}, "
        f"landed cost ${top.landed_cost_usd_bbl:.2f}/bbl, grade_match {top.grade_match}, "
        f"{top.voyage_days}d voyage.\n"
        f"Runner-up: {runner_up.source_grade}, score {runner_up.score:.4f}.",
    )

    return {
        **state,
        "risk": risk.model_dump(),
        "reroutes": [r.model_dump() for r in reroutes],
        "recommendation_narration": narration,
    }
