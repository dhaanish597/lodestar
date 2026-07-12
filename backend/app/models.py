# backend/app/models.py
from datetime import datetime

from pydantic import BaseModel


class Vessel(BaseModel):
    mmsi: int
    lat: float
    lon: float
    sog: float  # speed over ground, knots
    cog: float | None = None
    true_heading: float | None = None
    nav_status: int | None = None
    timestamp: datetime
    valid: bool = True
    signal_lost: bool = False
    extrapolated: bool = False


class RiskScore(BaseModel):
    corridor: str
    timestamp: datetime
    probability: float
    beta0: float
    weights: dict[str, float]
    features: dict[str, float]
    contributions: dict[str, float]
    # Per-feature provenance: LIVE | STUB | WARMING_UP | NO_TERRESTRIAL_COVERAGE.
    # Excluded states mean the feature was dropped from the sum (weights
    # renormalized) — never rendered as a genuine zero reading.
    feature_states: dict[str, str] = {}


class Scenario(BaseModel):
    corridor: str
    disruption_factor: float
    substitution_rate: float
    hormuz_share: float
    india_imports_mbd: float
    supply_gap_mbd: float
    utilization_drop_pct: float
    spr_fill_pct: float
    days_cover_remaining: float
    cpi_sensitivity: float
    cpi_delta_pp: float
    gdp_drag_bps: float
    cad_sensitivity: float
    cad_widening_pct_gdp: float
    crude_price_rise_pct: float
    price_sensitivity: float
    brent_baseline_usd_bbl: float


class RerouteOption(BaseModel):
    source_grade: str
    origin: str
    api_gravity: float
    sulfur_pct: float
    landed_cost_usd_bbl: float
    voyage_days: float
    grade_match: float
    congestion_penalty: float
    score: float
    best_fit_refineries: list[str]


class AgentRecommendation(BaseModel):
    corridor: str
    risk: RiskScore
    scenario: Scenario
    reroutes: list[RerouteOption]
    market_volatility_label: str
    price_spike_detected: bool
    market_narration: str
    density_state: str
    sanctions_state: str
    logistics_narration: str
    macro_narration: str
    recommendation_narration: str
    agent_mode: str  # "graph" | "sequential" -- whichever actually ran
