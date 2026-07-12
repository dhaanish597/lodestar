# backend/app/ingestion/logistics_reading.py
"""Shared corridor logistics-feature resolution -- AIS density/coverage
state, Open-Meteo sea state, OpenSanctions screening. Used by both the
/risk/{corridor} route (app/api/routes.py) and the agents' Logistics &
Maritime node (app/agents/logistics.py) so the coverage-exclusion rule
lives in exactly one place.

Sanctions inherits the AIS coverage state when there's no observed fleet to
screen (docs/04 §A) -- never a silent LIVE 0.0.
"""
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService
from app.models import Vessel

EXCLUDED_COVERAGE_STATES = {"NO_TERRESTRIAL_COVERAGE", "WARMING_UP"}


@dataclass
class LogisticsReading:
    x_density: float
    density_state: str
    x_sanctions: float
    sanctions_state: str
    x_weather: float
    vessels_in_corridor: list[Vessel]


async def compute_logistics_reading(
    corridor: str,
    http_client: httpx.AsyncClient,
    settings: Settings,
    vessel_store: VesselStore,
    density_tracker: DensityTracker,
    coverage_monitor: CoverageMonitor,
    weather_service: WeatherService,
    sanctions_service: SanctionsService,
) -> LogisticsReading:
    corridor_bbox = settings.corridors[corridor].bbox

    density_state = "LIVE"
    for box_name, box in settings.ais_boxes.items():
        if box.corridor == corridor:
            box_state = coverage_monitor.state(box_name)
            if box_state != "COVERED":
                density_state = box_state
            break

    vessels_in_corridor = vessel_store.snapshot_in_bbox(corridor_bbox)
    if density_state == "LIVE":
        density_tracker.sample(len(vessels_in_corridor))
    x_density = density_tracker.x_density()

    x_weather = await weather_service.get_x_weather(http_client, corridor=corridor, bbox=corridor_bbox)

    if density_state in EXCLUDED_COVERAGE_STATES:
        sanctions_state = density_state
        x_sanctions = 0.0
    elif not sanctions_service.has_key:
        sanctions_state = "STUB"
        x_sanctions = 0.0
    else:
        x_sanctions = await sanctions_service.get_x_sanctions(http_client, vessels_in_corridor)
        sanctions_state = "LIVE"

    return LogisticsReading(
        x_density=x_density,
        density_state=density_state,
        x_sanctions=x_sanctions,
        sanctions_state=sanctions_state,
        x_weather=x_weather,
        vessels_in_corridor=vessels_in_corridor,
    )
