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

    settings = get_settings()
    store = request.app.state.vessel_store
    density_tracker = request.app.state.density_tracker
    coverage_monitor = request.app.state.coverage_monitor
    http_client = request.app.state.http_client

    # Density is per-corridor: with multi-box AIS subscriptions the store holds
    # vessels from every box, so count only those inside this corridor's bbox.
    corridor_bbox = settings.corridors[corridor].bbox
    vessel_count = len(store.snapshot_in_bbox(corridor_bbox))

    # Coverage state for the AIS box feeding this corridor. A box with zero
    # frames for a full window means "no terrestrial receivers here" — the
    # density feature is then excluded from the risk sum (weights renormalized)
    # instead of silently reading 0. See docs/03 "AIS coverage reality".
    density_state = "LIVE"
    for box_name, box in settings.ais_boxes.items():
        if box.corridor == corridor:
            box_state = coverage_monitor.state(box_name)
            if box_state != "COVERED":
                density_state = box_state  # WARMING_UP or NO_TERRESTRIAL_COVERAGE
            break

    if density_state == "LIVE":
        # Only feed the rolling baseline real readings — zeros caused by a
        # coverage void would poison the anomaly detector's mean.
        density_tracker.sample(vessel_count)

    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    x_density = density_tracker.x_density()

    return compute_risk(
        corridor=corridor,
        x_kinetic=x_kinetic,
        x_density=x_density,
        feature_states={"density": density_state},
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
