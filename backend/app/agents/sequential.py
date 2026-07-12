# backend/app/agents/sequential.py
"""Sequential fallback for the four agent nodes -- calls the exact same
functions graph.py uses, directly, with no LangGraph runtime. AGENT_MODE=
sequential (runner.py) selects this path. This is an accepted fallback per
the build plan's own cut-list (#4: 'keep agents but run sequential if graph
is flaky'), not an emergency patch.
"""
from app.agents.deps import AgentDeps
from app.agents.logistics import run_logistics_node
from app.agents.macro import run_macro_node
from app.agents.market import run_market_node
from app.agents.orchestrator import run_orchestrator_node
from app.agents.state import AgentState


async def run_sequential(
    deps: AgentDeps,
    corridor: str,
    disruption_factor: float,
    substitution_rate: float,
    hormuz_share: float,
) -> AgentState:
    state: AgentState = {
        "corridor": corridor,
        "disruption_factor": disruption_factor,
        "substitution_rate": substitution_rate,
        "hormuz_share": hormuz_share,
    }
    state = await run_market_node(state, deps.http_client, deps.price_service, deps.llm)
    state = await run_logistics_node(
        state, deps.http_client, deps.settings, deps.vessel_store,
        deps.density_tracker, deps.coverage_monitor, deps.weather_service,
        deps.sanctions_service, deps.llm,
    )
    state = await run_macro_node(state, deps.llm)
    state = await run_orchestrator_node(state, deps.http_client, deps.freight_service, deps.llm)
    return state
