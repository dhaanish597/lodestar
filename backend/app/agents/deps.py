"""Bundles the live connectors/services every agent node needs -- constructed
once per request from app.state (mirrors the pattern routes.py already uses)
so both the LangGraph path and the sequential fallback, and their tests,
construct dependencies identically.
"""
from dataclasses import dataclass

import httpx

from app.agents.llm_client import LLMClient
from app.config import Settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.freight import FreightService
from app.ingestion.prices import PriceService
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService


@dataclass
class AgentDeps:
    http_client: httpx.AsyncClient
    settings: Settings
    vessel_store: VesselStore
    density_tracker: DensityTracker
    coverage_monitor: CoverageMonitor
    weather_service: WeatherService
    sanctions_service: SanctionsService
    freight_service: FreightService
    price_service: PriceService
    llm: LLMClient
