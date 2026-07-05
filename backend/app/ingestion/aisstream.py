# backend/app/ingestion/aisstream.py
import asyncio
import json
import logging
import re
import traceback
from datetime import datetime, timezone

import websockets

from app.config import AisBox
from app.ingestion.coverage import CoverageMonitor
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

    def snapshot_in_bbox(
        self, bbox: tuple[float, float, float, float], now: datetime | None = None
    ) -> list[Vessel]:
        """Snapshot restricted to one box — with multi-box subscriptions the
        store holds vessels from every box, so per-corridor features (e.g.
        X_density for Hormuz) must filter, not count the whole store."""
        lat_min, lon_min, lat_max, lon_max = bbox
        return [
            v
            for v in self.snapshot(now)
            if lat_min <= v.lat <= lat_max and lon_min <= v.lon <= lon_max
        ]


_GO_TIME_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d+))? \+0000 UTC"
)


def _parse_time_utc(ts_raw: str | None) -> datetime:
    """AISStream's real MetaData.time_utc is Go's time.String() format —
    '2026-07-05 13:20:44.646943103 +0000 UTC' (nanosecond precision, ' +0000
    UTC' suffix) — which fromisoformat rejects. Verified live 2026-07-05;
    ISO 8601 is also accepted in case the feed ever normalizes."""
    if not ts_raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    m = _GO_TIME_RE.match(ts_raw)
    if m:
        micros = (m.group(3) or "")[:6].ljust(6, "0")
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}.{micros}+00:00")
    logger.warning("[AIS] Unparseable time_utc %r — falling back to now()", ts_raw)
    return datetime.now(timezone.utc)


def _parse_position_report(raw: dict) -> Vessel | None:
    if raw.get("MessageType") != "PositionReport":
        return None
    report = raw["Message"]["PositionReport"]
    meta = raw.get("MetaData", {})
    timestamp = _parse_time_utc(meta.get("time_utc"))
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
    def __init__(
        self,
        api_key: str,
        boxes: dict[str, AisBox],
        store: VesselStore,
        coverage: CoverageMonitor | None = None,
        connector=None,
    ):
        self.api_key = api_key
        self.boxes = boxes
        self.store = store
        self.coverage = coverage or CoverageMonitor(list(boxes))
        self._connector = connector or websockets.connect
        self._msg_count = 0
        self._vessel_count = 0

    def _subscribe_payload(self) -> str:
        # One subscription, N boxes — AISStream's BoundingBoxes field accepts a
        # list of boxes, each a list of exactly two [lat, lon] points.
        # Coordinate order [lat, lon] was verified empirically on 2026-07-05
        # (scripts/diag_aisstream.py case B: Dover in lat-lon → frames at t=0).
        bounding_boxes = [
            [[box.bbox[0], box.bbox[1]], [box.bbox[2], box.bbox[3]]]
            for box in self.boxes.values()
        ]

        # --- Guard: AISStream silently ignores malformed shapes, so fail
        #     loudly here instead. Each box must be exactly two [lat, lon]
        #     points, and there must be at least one box. ---
        if (
            not isinstance(bounding_boxes, list)
            or len(bounding_boxes) < 1
            or any(
                not isinstance(box, list)
                or len(box) != 2
                or any(not isinstance(point, list) or len(point) != 2 for point in box)
                for box in bounding_boxes
            )
        ):
            logger.error(
                "[AIS hop-b-raw] ✗ BoundingBoxes shape is WRONG, refusing to send: %r",
                bounding_boxes,
            )
            raise ValueError(
                f"BoundingBoxes must be [[[lat_min, lon_min], [lat_max, lon_max]], ...], got {bounding_boxes!r}"
            )

        return json.dumps(
            {
                "APIKey": self.api_key,
                "BoundingBoxes": bounding_boxes,
                "FilterMessageTypes": ["PositionReport"],
            }
        )

    def _attribute_to_boxes(self, vessel: Vessel) -> None:
        for name, box in self.boxes.items():
            if box.contains(vessel.lat, vessel.lon):
                self.coverage.mark_frame(name)

    async def _consume(self, ws) -> None:
        payload = self._subscribe_payload()
        # --- HOP (b): subscription sent ---
        masked_key = self.api_key[:8] + "…" if len(self.api_key) > 8 else "(empty!)"
        # SENTINEL-MULTIBOX-20260705c: image-freshness marker — if this line is
        # absent from `docker compose logs api`, the container runs a stale image.
        # (b = bytes-frame decode fix; c = Go-format time_utc parse fix)
        logger.info(
            "[AIS hop-b] SENTINEL-MULTIBOX-20260705c Subscription SENT  key=%s  boxes=%s",
            masked_key,
            {name: box.bbox for name, box in self.boxes.items()},
        )
        await ws.send(payload)
        self.coverage.mark_subscribed()

        # --- HOP (b-raw): log the exact string that was sent, in full ---
        logger.info("[AIS hop-b-raw] Subscribe message sent: %s", payload)

        self._msg_count = 0
        self._vessel_count = 0

        async for raw_message in ws:
            self._msg_count += 1

            # --- RAW FRAME LOG: fires unconditionally for the first 20
            #     messages after connect, and for any message whose
            #     MessageType is not "PositionReport" for the life of the
            #     connection. Runs BEFORE any MessageType filtering. ---
            # AISStream delivers BINARY WebSocket frames — raw_message is
            # bytes, and str(bytes) yields "b'{...}'" which json.loads
            # rejects. Decode, never str().
            if isinstance(raw_message, (bytes, bytearray)):
                raw_str = raw_message.decode("utf-8", errors="replace")
            else:
                raw_str = raw_message
            try:
                peek = json.loads(raw_str)
                peek_type = peek.get("MessageType", "MISSING") if isinstance(peek, dict) else "MISSING"
            except Exception:
                peek_type = "MISSING"

            if self._msg_count <= 20 or peek_type != "PositionReport":
                logger.info(
                    "[AIS hop-c-raw] msg #%d  type=%s  preview=%.500s",
                    self._msg_count, peek_type, raw_str[:500],
                )

            # --- Per-message processing wrapped in try/except so one bad
            #     message cannot kill the entire receive loop ---
            try:
                data = json.loads(raw_str)
                vessel = _parse_position_report(data)
                if vessel is not None:
                    self._vessel_count += 1
                    self.store.upsert(vessel)
                    self._attribute_to_boxes(vessel)
                    # --- HOP (c): position message received ---
                    if self._vessel_count == 1:
                        logger.info(
                            "[AIS hop-c] ✓ FIRST vessel received  mmsi=%s  lat=%.4f  lon=%.4f  sog=%.1f",
                            vessel.mmsi, vessel.lat, vessel.lon, vessel.sog,
                        )
                    elif self._vessel_count % 50 == 0:
                        logger.info(
                            "[AIS hop-c] %d vessels ingested (%d msgs total), store size=%d, per-box=%s, coverage=%s",
                            self._vessel_count, self._msg_count, len(self.store._vessels),
                            self.coverage.frame_counts,
                            {name: self.coverage.state(name) for name in self.boxes},
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
            except Exception as e:
                logger.error(
                    "[AIS hop-c-error] ✗ Exception processing message #%d (loop continues): %s\npreview=%.500s\n%s",
                    self._msg_count, e, raw_str[:500], traceback.format_exc(),
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
