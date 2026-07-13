# backend/app/agents/graph.py
"""LangGraph StateGraph wiring the four Phase 3 agent nodes with a real
parallel fan-out: START -> {market, logistics} run concurrently (neither
reads the other's output), both fan in to Macroeconomic Strategist (which
needs market's brent_price_usd_bbl but joining on both branches keeps the
graph simple), then macro -> Executive Orchestrator -> END. AGENT_MODE=graph
(default, runner.py) runs this. sequential.py runs the identical four node
functions directly, one at a time, with no LangGraph runtime, as the build
plan's cut-list #4 fallback.

Market and Logistics genuinely run as concurrent LangGraph branches, so
their step closures below return *partial* state updates -- only the keys
each node actually adds -- instead of the full `{**state, ...}` dict the
node functions themselves return. If both closures returned the full
spread, LangGraph would see both branches writing the same shared base
keys (corridor, disruption_factor, substitution_rate, hormuz_share) in the
same superstep with no reducer defined on those channels, which raises
InvalidUpdateError even though the values are identical. Macro and
Orchestrator never run concurrently with a sibling branch in this design,
so their closures can safely keep returning the full node output.
"""
from langgraph.graph import END, START, StateGraph

from app.agents.deps import AgentDeps
from app.agents.logistics import run_logistics_node
from app.agents.macro import run_macro_node
from app.agents.market import run_market_node
from app.agents.orchestrator import run_orchestrator_node
from app.agents.state import AgentState

# Keys each concurrently-running node adds (see state.py's field comments).
# The two sets are disjoint from each other and from the input state's own
# keys, so slicing a node's full-state-spread return down to just these is
# a safe, complete partial update -- and avoids the same-superstep,
# same-key write collision described above.
_MARKET_KEYS = (
    "x_kinetic",
    "brent_price_usd_bbl",
    "market_volatility_label",
    "price_spike_detected",
    "market_narration",
)
_LOGISTICS_KEYS = (
    "x_density",
    "density_state",
    "x_sanctions",
    "sanctions_state",
    "x_weather",
    "logistics_narration",
)


def build_graph(deps: AgentDeps):
    graph = StateGraph(AgentState)

    async def market_step(state: AgentState) -> AgentState:
        result = await run_market_node(state, deps.http_client, deps.price_service, deps.llm)
        return {key: result[key] for key in _MARKET_KEYS}

    async def logistics_step(state: AgentState) -> AgentState:
        result = await run_logistics_node(
            state, deps.http_client, deps.settings, deps.vessel_store,
            deps.density_tracker, deps.coverage_monitor, deps.weather_service,
            deps.sanctions_service, deps.llm,
        )
        return {key: result[key] for key in _LOGISTICS_KEYS}

    async def macro_step(state: AgentState) -> AgentState:
        return await run_macro_node(state, deps.llm)

    async def orchestrator_step(state: AgentState) -> AgentState:
        return await run_orchestrator_node(state, deps.http_client, deps.freight_service, deps.llm)

    graph.add_node("market", market_step)
    graph.add_node("logistics", logistics_step)
    graph.add_node("macro", macro_step)
    graph.add_node("orchestrator", orchestrator_step)

    # Fan out: market and logistics both start from START and run
    # concurrently (same superstep). Fan in: macro has incoming edges from
    # both, so LangGraph runs it once, only after both branches complete.
    graph.add_edge(START, "market")
    graph.add_edge(START, "logistics")
    graph.add_edge("market", "macro")
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
