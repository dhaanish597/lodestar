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
        self._msg_count = 0
        self._vessel_count = 0

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
        payload = self._subscribe_payload()
        # --- HOP (b): subscription sent ---
        masked_key = self.api_key[:8] + "…" if len(self.api_key) > 8 else "(empty!)"
        logger.info(
            "[AIS hop-b] Subscription SENT  key=%s  bbox=%s",
            masked_key,
            self.corridor.bbox,
        )
        logger.debug("[AIS hop-b] Full payload: %s", payload)
        await ws.send(payload)

        self._msg_count = 0
        self._vessel_count = 0

        async for raw_message in ws:
            self._msg_count += 1

            # --- RAW MESSAGE LOG: fires on EVERY message before any parsing ---
            raw_str = raw_message if isinstance(raw_message, str) else str(raw_message)
            # Extract MessageType quickly for the log line (without full parse)
            try:
                peek = json.loads(raw_str)
                peek_type = peek.get("MessageType", "(no MessageType field)")
            except Exception:
                peek_type = "(invalid JSON)"
            logger.info(
                "[AIS raw] msg #%d  type=%s  len=%d  preview=%.200s",
                self._msg_count, peek_type, len(raw_str), raw_str[:200],
            )

            # --- Per-message processing wrapped in try/except so one bad
            #     message cannot kill the entire receive loop ---
            try:
                data = json.loads(raw_str)
                vessel = _parse_position_report(data)
                if vessel is not None:
                    self._vessel_count += 1
                    self.store.upsert(vessel)
                    # --- HOP (c): position message received ---
                    if self._vessel_count == 1:
                        logger.info(
                            "[AIS hop-c] ✓ FIRST vessel received  mmsi=%s  lat=%.4f  lon=%.4f  sog=%.1f",
                            vessel.mmsi, vessel.lat, vessel.lon, vessel.sog,
                        )
                    elif self._vessel_count % 50 == 0:
                        logger.info(
                            "[AIS hop-c] %d vessels ingested (%d msgs total), store size=%d",
                            self._vessel_count, self._msg_count, len(self.store._vessels),
                        )
                else:
                    # Non-PositionReport message — log it so we can see acks,
                    # errors, rate-limit notices, etc.
                    logger.info(
                        "[AIS hop-c] Non-position message #%d  type=%s  keys=%s",
                        self._msg_count,
                        data.get("MessageType", "(none)"),
                        list(data.keys())[:10],
                    )
            except Exception:
                logger.exception(
                    "[AIS hop-c] ✗ Exception processing message #%d (loop continues)  preview=%.200s",
                    self._msg_count, raw_str[:200],
                )

        logger.warning(
            "[AIS] WebSocket iterator exhausted after %d messages (%d vessels).  "
            "This means the server closed the connection cleanly.",
            self._msg_count, self._vessel_count,
        )

    async def run(self) -> None:
        # --- Guard: refuse to run with an empty API key ---
        if not self.api_key:
            logger.error(
                "[AIS] ✗ AISSTREAM_API_KEY is EMPTY — cannot connect. "
                "Set it in backend/.env or as an environment variable."
            )
            return

        backoff = 1
        while True:
            try:
                logger.info(
                    "[AIS hop-a] Connecting to %s …", AISSTREAM_URL,
                )
                async with self._connector(AISSTREAM_URL) as ws:
                    # --- HOP (a): socket open ---
                    logger.info("[AIS hop-a] ✓ WebSocket OPEN")
                    backoff = 1
                    await self._consume(ws)
            except asyncio.CancelledError:
                logger.info("[AIS] Task cancelled (shutdown)")
                raise
            except Exception:
                logger.exception(
                    "[AIS hop-a] Connection lost (ingested %d vessels this session), "
                    "reconnecting in %ss",
                    self._vessel_count, backoff,
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
