# backend/app/api/routes.py
from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.engine.reroute import rank_reroutes
from app.engine.risk import compute_risk
from app.engine.scenario import compute_scenario
from app.ingestion.gdelt import fetch_kinetic_volume
from app.models import RerouteOption, RiskScore, Scenario

router = APIRouter()

SUPPORTED_CORRIDORS = {"hormuz"}  # bab_el_mandeb, malacca: code path exists via corridors.json, not wired yet


@router.get("/risk/{corridor}", response_model=RiskScore)
async def get_risk(corridor: str, request: Request) -> RiskScore:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    store = request.app.state.vessel_store
    density_tracker = request.app.state.density_tracker
    http_client = request.app.state.http_client

    vessel_count = len(store.snapshot())
    density_tracker.sample(vessel_count)

    x_kinetic = await fetch_kinetic_volume(http_client)
    x_density = density_tracker.x_density()

    return compute_risk(corridor=corridor, x_kinetic=x_kinetic, x_density=x_density)


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
