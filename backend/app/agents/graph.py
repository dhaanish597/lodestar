# backend/app/agents/graph.py
"""LangGraph StateGraph wiring the four Phase 3 agent nodes into one
pipeline: Market Intelligence -> Logistics & Maritime -> Macroeconomic
Strategist -> Executive Orchestrator. AGENT_MODE=graph (default, runner.py)
runs this. sequential.py runs the identical four node functions directly,
with no LangGraph runtime, as the build plan's cut-list #4 fallback.
"""
from langgraph.graph import END, StateGraph

from app.agents.deps import AgentDeps
from app.agents.logistics import run_logistics_node
from app.agents.macro import run_macro_node
from app.agents.market import run_market_node
from app.agents.orchestrator import run_orchestrator_node
from app.agents.state import AgentState


def build_graph(deps: AgentDeps):
    graph = StateGraph(AgentState)

    async def market_step(state: AgentState) -> AgentState:
        return await run_market_node(state, deps.http_client, deps.price_service, deps.llm)

    async def logistics_step(state: AgentState) -> AgentState:
        return await run_logistics_node(
            state, deps.http_client, deps.settings, deps.vessel_store,
            deps.density_tracker, deps.coverage_monitor, deps.weather_service,
            deps.sanctions_service, deps.llm,
        )

    async def macro_step(state: AgentState) -> AgentState:
        return await run_macro_node(state, deps.llm)

    async def orchestrator_step(state: AgentState) -> AgentState:
        return await run_orchestrator_node(state, deps.http_client, deps.freight_service, deps.llm)

    graph.add_node("market", market_step)
    graph.add_node("logistics", logistics_step)
    graph.add_node("macro", macro_step)
    graph.add_node("orchestrator", orchestrator_step)

    graph.set_entry_point("market")
    graph.add_edge("market", "logistics")
    graph.add_edge("logistics", "macro")
    graph.add_edge("macro", "orchestrator")
    graph.add_edge("orchestrator", END)

    return graph.compile()


async def run_graph(
    deps: AgentDeps,
    corridor: str,
    disruption_factor: float,
    substitution_rate: float,
    hormuz_share: float,
) -> AgentState:
    compiled = build_graph(deps)
    initial_state: AgentState = {
        "corridor": corridor,
        "disruption_factor": disruption_factor,
        "substitution_rate": substitution_rate,
        "hormuz_share": hormuz_share,
    }
    return await compiled.ainvoke(initial_state)
