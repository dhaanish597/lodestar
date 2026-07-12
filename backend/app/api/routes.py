# backend/app/api/routes.py
from fastapi import APIRouter, HTTPException, Request

from app.agents.deps import AgentDeps
from app.agents.runner import AGENT_MODE, run_agents
from app.config import get_settings
from app.engine.reroute import rank_reroutes
from app.engine.risk import compute_risk
from app.engine.scenario import compute_scenario
from app.ingestion.gdelt import fetch_kinetic_volume
from app.ingestion.logistics_reading import compute_logistics_reading
from app.models import AgentRecommendation, RerouteOption, RiskScore, Scenario

router = APIRouter()

SUPPORTED_CORRIDORS = {"hormuz"}  # bab_el_mandeb, malacca: code path exists via corridors.json, not wired yet


@router.get("/risk/{corridor}", response_model=RiskScore)
async def get_risk(corridor: str, request: Request) -> RiskScore:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    settings = get_settings()
    http_client = request.app.state.http_client

    reading = await compute_logistics_reading(
        corridor=corridor,
        http_client=http_client,
        settings=settings,
        vessel_store=request.app.state.vessel_store,
        density_tracker=request.app.state.density_tracker,
        coverage_monitor=request.app.state.coverage_monitor,
        weather_service=request.app.state.weather_service,
        sanctions_service=request.app.state.sanctions_service,
    )

    freight_service = request.app.state.freight_service
    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    x_freight = await freight_service.get_x_freight(http_client)

    return compute_risk(
        corridor=corridor,
        x_kinetic=x_kinetic,
        x_density=reading.x_density,
        x_sanctions=reading.x_sanctions,
        x_weather=reading.x_weather,
        x_freight=x_freight,
        feature_states={
            "density": reading.density_state,
            "sanctions": reading.sanctions_state,
            "weather": "LIVE",
            "freight": "LIVE" if freight_service.has_key else "STUB",
        },
    )


@router.get("/coverage")
async def get_coverage(request: Request) -> dict:
    """Per-box AIS coverage state — diagnostic surface for the coverage-state
    machinery (and demo-day evidence that a quiet corridor is a receiver gap,
    not a dead pipeline)."""
    return request.app.state.coverage_monitor.snapshot()


@router.get("/scenario/{corridor}", response_model=Scenario)
async def get_scenario(
    corridor: str,
    request: Request,
    disruption_factor: float = 0.30,
    substitution_rate: float = 0.20,
    hormuz_share: float = 0.45,
    spr_fill_pct: float = 0.64,
    cpi_sensitivity: float = 0.35,
    cad_sensitivity: float = 0.35,
) -> Scenario:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    price_service = request.app.state.price_service
    http_client = request.app.state.http_client
    brent_price = await price_service.get_brent_price(http_client)

    return compute_scenario(
        corridor=corridor,
        disruption_factor=disruption_factor,
        substitution_rate=substitution_rate,
        hormuz_share=hormuz_share,
        spr_fill_pct=spr_fill_pct,
        cpi_sensitivity=cpi_sensitivity,
        cad_sensitivity=cad_sensitivity,
        brent_baseline_usd_bbl=brent_price,
    )


@router.get("/reroute/{corridor}", response_model=list[RerouteOption])
async def get_reroute(
    corridor: str,
    request: Request,
    disruption_factor: float = 0.30,
) -> list[RerouteOption]:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    price_service = request.app.state.price_service
    http_client = request.app.state.http_client
    brent_price = await price_service.get_brent_price(http_client)

    grades = get_settings().crude_grades
    return rank_reroutes(disruption_factor=disruption_factor, brent_price_usd_bbl=brent_price, grades=grades)


@router.get("/recommendation/{corridor}", response_model=AgentRecommendation)
async def get_recommendation(
    corridor: str,
    request: Request,
    disruption_factor: float = 0.30,
    substitution_rate: float = 0.20,
    hormuz_share: float = 0.45,
) -> AgentRecommendation:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    settings = get_settings()
    deps = AgentDeps(
        http_client=request.app.state.http_client,
        settings=settings,
        vessel_store=request.app.state.vessel_store,
        density_tracker=request.app.state.density_tracker,
        coverage_monitor=request.app.state.coverage_monitor,
        weather_service=request.app.state.weather_service,
        sanctions_service=request.app.state.sanctions_service,
        freight_service=request.app.state.freight_service,
        price_service=request.app.state.price_service,
        llm=request.app.state.llm_client,
    )
    final_state = await run_agents(deps, corridor, disruption_factor, substitution_rate, hormuz_share)

    return AgentRecommendation(
        corridor=corridor,
        risk=RiskScore(**final_state["risk"]),
        scenario=Scenario(**final_state["scenario"]),
        reroutes=[RerouteOption(**r) for r in final_state["reroutes"]],
        market_volatility_label=final_state["market_volatility_label"],
        price_spike_detected=final_state["price_spike_detected"],
        market_narration=final_state["market_narration"],
        density_state=final_state["density_state"],
        sanctions_state=final_state["sanctions_state"],
        logistics_narration=final_state["logistics_narration"],
        macro_narration=final_state["macro_narration"],
        recommendation_narration=final_state["recommendation_narration"],
        agent_mode=AGENT_MODE,
    )
