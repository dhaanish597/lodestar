# backend/app/agents/logistics.py
"""Logistics & Maritime node: AIS density/coverage state, Open-Meteo sea
state, OpenSanctions vessel screening -- all resolved by the shared
app/ingestion/logistics_reading.py (also used by GET /risk/{corridor}, so
the two never disagree on sanctions/coverage state). The LLM only narrates.
"""
import httpx

from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.config import Settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.logistics_reading import compute_logistics_reading
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService

LOGISTICS_SYSTEM_PROMPT = (
    "You are a maritime logistics analyst for a crude oil procurement desk. "
    "You are given AIS vessel-density state, sea-state (wave height threshold) "
    "flag, and vessel sanctions-screening state and rate for a shipping corridor. "
    "Narrate the physical/logistics risk read in 2-3 sentences, in plain "
    "language a non-technical stakeholder can follow. If a reading's state is "
    "STUB, WARMING_UP, or NO_TERRESTRIAL_COVERAGE, say so explicitly and never "
    "claim a real value for that reading -- e.g. say 'sanctions screening is "
    "unavailable' rather than 'no vessels are sanctioned'. Never invent a "
    "number different from the ones given."
)


async def run_logistics_node(
    state: AgentState,
    http_client: httpx.AsyncClient,
    settings: Settings,
    vessel_store: VesselStore,
    density_tracker: DensityTracker,
    coverage_monitor: CoverageMonitor,
    weather_service: WeatherService,
    sanctions_service: SanctionsService,
    llm: LLMClient,
) -> AgentState:
    corridor = state["corridor"]
    reading = await compute_logistics_reading(
        corridor=corridor,
        http_client=http_client,
        settings=settings,
        vessel_store=vessel_store,
        density_tracker=density_tracker,
        coverage_monitor=coverage_monitor,
        weather_service=weather_service,
        sanctions_service=sanctions_service,
    )

    narration = await llm.narrate(
        LOGISTICS_SYSTEM_PROMPT,
        f"Corridor: {corridor}\n"
        f"AIS density state: {reading.density_state} (X_density={reading.x_density:.3f})\n"
        f"Sea state flag (Open-Meteo): X_weather={reading.x_weather:.0f} (1=rough seas above threshold)\n"
        f"Sanctions screening state: {reading.sanctions_state} (X_sanctions={reading.x_sanctions:.3f}, "
        f"{len(reading.vessels_in_corridor)} vessels observed)",
    )

    return {
        **state,
        "x_density": reading.x_density,
        "density_state": reading.density_state,
        "x_sanctions": reading.x_sanctions,
        "sanctions_state": reading.sanctions_state,
        "x_weather": reading.x_weather,
        "logistics_narration": narration,
    }
