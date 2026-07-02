# backend/app/api/routes.py
from fastapi import APIRouter, HTTPException, Request

from app.engine.risk import compute_risk
from app.ingestion.gdelt import fetch_kinetic_volume
from app.models import RiskScore

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
