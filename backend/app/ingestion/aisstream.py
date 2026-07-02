# backend/app/ingestion/aisstream.py
import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from app.config import Corridor
from app.ingestion.dead_reckoning import apply_dead_reckoning
from app.models import Vessel

logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
MAX_BACKOFF_SECONDS = 30


class VesselStore:
    def __init__(self) -> None:
        self._vessels: dict[int, Vessel] = {}

    def upsert(self, vessel: Vessel) -> None:
        self._vessels[vessel.mmsi] = vessel

    def snapshot(self, now: datetime | None = None) -> list[Vessel]:
        now = now or datetime.now(timezone.utc)
        return [apply_dead_reckoning(v, now) for v in self._vessels.values()]


def _parse_position_report(raw: dict) -> Vessel | None:
    if raw.get("MessageType") != "PositionReport":
        return None
    report = raw["Message"]["PositionReport"]
    meta = raw.get("MetaData", {})
    ts_raw = meta.get("time_utc")
    timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.now(timezone.utc)
    return Vessel(
        mmsi=report["UserID"],
        lat=report["Latitude"],
        lon=report["Longitude"],
        sog=report.get("Sog", 0.0),
        cog=report.get("Cog"),
        true_heading=report.get("TrueHeading"),
        nav_status=report.get("NavigationalStatus"),
        timestamp=timestamp,
        valid=raw.get("Valid", True),
    )


class AISStreamClient:
    def __init__(self, api_key: str, corridor: Corridor, store: VesselStore, connector=None):
        self.api_key = api_key
        self.corridor = corridor
        self.store = store
        self._connector = connector or websockets.connect

    def _subscribe_payload(self) -> str:
        lat_min, lon_min, lat_max, lon_max = self.corridor.bbox
        return json.dumps(
            {
                "APIKey": self.api_key,
                "BoundingBoxes": [[[lat_min, lon_min], [lat_max, lon_max]]],
                "FilterMessageTypes": ["PositionReport"],
            }
        )

    async def _consume(self, ws) -> None:
        await ws.send(self._subscribe_payload())
        async for raw_message in ws:
            try:
                data = json.loads(raw_message)
                vessel = _parse_position_report(data)
                if vessel is not None:
                    self.store.upsert(vessel)
            except Exception:
                logger.exception("Failed to process AIS message")

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                async with self._connector(AISSTREAM_URL) as ws:
                    backoff = 1
                    await self._consume(ws)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AISStream connection lost, reconnecting in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
