# backend/app/agents/runner.py
"""Selects the LangGraph path (default) or the sequential fallback based on
the AGENT_MODE env var. AGENT_MODE=graph (default) | AGENT_MODE=sequential.
Read once at import time, matching how app/ingestion/gdelt.py reads
REDIS_URL from the environment directly.
"""
import os

from app.agents.deps import AgentDeps
from app.agents.state import AgentState

AGENT_MODE = os.environ.get("AGENT_MODE", "graph").strip().lower()


async def run_agents(
    deps: AgentDeps,
    corridor: str,
    disruption_factor: float,
    substitution_rate: float,
    hormuz_share: float,
) -> AgentState:
    if AGENT_MODE == "sequential":
        from app.agents.sequential import run_sequential
        return await run_sequential(deps, corridor, disruption_factor, substitution_rate, hormuz_share)
    from app.agents.graph import run_graph
    return await run_graph(deps, corridor, disruption_factor, substitution_rate, hormuz_share)
