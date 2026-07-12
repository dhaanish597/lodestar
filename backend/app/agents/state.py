"""Shared state contract threaded through every agent node, both the
LangGraph path (graph.py) and the sequential fallback (sequential.py).
Every `x_*`/`risk`/`scenario`/`reroutes` field is engine or connector
output, passed through verbatim; every `*_narration` field is LLM text
only, and classification fields (`market_volatility_label`,
`price_spike_detected`) are LLM-produced labels, never derived numbers.
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    corridor: str
    disruption_factor: float
    substitution_rate: float
    hormuz_share: float

    # Market Intelligence node output
    x_kinetic: float
    brent_price_usd_bbl: float
    market_volatility_label: str  # LLM classification: LOW | MEDIUM | HIGH
    price_spike_detected: bool  # LLM classification
    market_narration: str

    # Logistics & Maritime node output
    x_density: float
    density_state: str  # LIVE | WARMING_UP | NO_TERRESTRIAL_COVERAGE
    x_sanctions: float
    sanctions_state: str  # LIVE | STUB | WARMING_UP | NO_TERRESTRIAL_COVERAGE
    x_weather: float
    logistics_narration: str

    # Macroeconomic Strategist node output
    scenario: dict
    macro_narration: str

    # Executive Orchestrator node output
    risk: dict
    reroutes: list
    recommendation_narration: str
