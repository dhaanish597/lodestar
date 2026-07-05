# backend/tests/test_aisstream.py
import json
from datetime import datetime, timezone

import pytest

from app.config import AisBox
from app.ingestion.aisstream import AISStreamClient, VesselStore
from app.ingestion.coverage import CoverageMonitor


class FakeWebSocket:
    def __init__(self, messages: list[str]):
        self._messages = list(messages)
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def _position_report(mmsi: int) -> str:
    return json.dumps(
        {
            "MessageType": "PositionReport",
            "Message": {
                "PositionReport": {
                    "UserID": mmsi,
                    "Latitude": 26.1,
                    "Longitude": 56.2,
                    "Sog": 11.5,
                    "Cog": 91.0,
                    "TrueHeading": 90,
                    "NavigationalStatus": 0,
                }
            },
            "MetaData": {"time_utc": "2026-07-02T10:00:00Z"},
        }
    )


def test_store_upsert_and_snapshot_returns_latest_per_mmsi():
    store = VesselStore()
    from app.models import Vessel

    store.upsert(Vessel(mmsi=1, lat=1.0, lon=1.0, sog=0, timestamp=datetime.now(timezone.utc)))
    store.upsert(Vessel(mmsi=1, lat=2.0, lon=2.0, sog=0, timestamp=datetime.now(timezone.utc)))
    snap = store.snapshot()
    assert len(snap) == 1
    assert snap[0].lat == 2.0


HORMUZ_BOX = AisBox(bbox=(25.2732, 55.1647, 27.3713, 57.3419), corridor="hormuz")
INDIA_BOX = AisBox(bbox=(19.5, 68.5, 23.5, 73.0))


@pytest.mark.asyncio
async def test_consume_subscribes_within_first_send_and_parses_position_reports():
    store = VesselStore()
    client = AISStreamClient(api_key="testkey", boxes={"hormuz": HORMUZ_BOX}, store=store)
    ws = FakeWebSocket([_position_report(111222333), _position_report(444555666)])

    await client._consume(ws)

    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["APIKey"] == "testkey"
    assert payload["BoundingBoxes"] == [[[25.2732, 55.1647], [27.3713, 57.3419]]]
    assert payload["FilterMessageTypes"] == ["PositionReport"]

    snap = store.snapshot()
    assert {v.mmsi for v in snap} == {111222333, 444555666}


def test_multi_box_subscribe_payload_exact_json_shape():
    """AISStream expects BoundingBoxes = [box, box, ...] where each box is
    exactly two [lat, lon] points. Coordinate order verified empirically
    2026-07-05 (scripts/diag_aisstream.py cases B vs C). This asserts the
    exact serialized JSON so a refactor cannot silently break the shape."""
    store = VesselStore()
    client = AISStreamClient(
        api_key="testkey", boxes={"hormuz": HORMUZ_BOX, "india_west_coast": INDIA_BOX}, store=store
    )

    payload = json.loads(client._subscribe_payload())

    assert payload == {
        "APIKey": "testkey",
        "BoundingBoxes": [
            [[25.2732, 55.1647], [27.3713, 57.3419]],
            [[19.5, 68.5], [23.5, 73.0]],
        ],
        "FilterMessageTypes": ["PositionReport"],
    }


@pytest.mark.asyncio
async def test_consume_parses_binary_frames():
    """AISStream sends BINARY WebSocket frames (bytes, not str). str(bytes)
    yields "b'{...}'" which json.loads rejects — the exact bug that silently
    dropped every live vessel on 2026-07-05. Frames must be UTF-8 decoded."""
    store = VesselStore()
    client = AISStreamClient(api_key="testkey", boxes={"hormuz": HORMUZ_BOX}, store=store)
    ws = FakeWebSocket([_position_report(111222333).encode("utf-8")])

    await client._consume(ws)

    assert {v.mmsi for v in store.snapshot()} == {111222333}


def test_parse_time_utc_accepts_real_go_format():
    """Live AISStream time_utc is Go time.String(): nanosecond precision and
    a ' +0000 UTC' suffix — not ISO 8601 (verified 2026-07-05)."""
    from app.ingestion.aisstream import _parse_time_utc

    ts = _parse_time_utc("2026-07-05 13:20:44.646943103 +0000 UTC")
    assert ts == datetime(2026, 7, 5, 13, 20, 44, 646943, tzinfo=timezone.utc)

    # No fractional seconds
    ts = _parse_time_utc("2026-07-05 13:20:44 +0000 UTC")
    assert ts == datetime(2026, 7, 5, 13, 20, 44, tzinfo=timezone.utc)

    # ISO 8601 still accepted
    ts = _parse_time_utc("2026-07-02T10:00:00Z")
    assert ts == datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)

    # Garbage → now(), never a crash that kills the vessel
    assert _parse_time_utc("not a time").tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_consume_parses_real_wire_format_end_to_end():
    """Byte frame + Go timestamp together — the exact live wire format."""
    frame = json.dumps(
        {
            "MessageType": "PositionReport",
            "Message": {
                "PositionReport": {
                    "UserID": 566096000,
                    "Latitude": 1.259495,
                    "Longitude": 103.848015,
                    "Sog": 4.6,
                    "Cog": 287.8,
                    "TrueHeading": 511,
                    "NavigationalStatus": 0,
                }
            },
            "MetaData": {"MMSI": 566096000, "time_utc": "2026-07-05 13:20:44.646943103 +0000 UTC"},
        }
    ).encode("utf-8")
    store = VesselStore()
    client = AISStreamClient(api_key="testkey", boxes={"hormuz": HORMUZ_BOX}, store=store)

    await client._consume(FakeWebSocket([frame]))

    snap = store.snapshot()
    assert len(snap) == 1
    assert snap[0].mmsi == 566096000
    assert snap[0].timestamp == datetime(2026, 7, 5, 13, 20, 44, 646943, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_consume_attributes_frames_to_the_containing_box():
    store = VesselStore()
    coverage = CoverageMonitor(["hormuz", "india_west_coast"])
    client = AISStreamClient(
        api_key="testkey",
        boxes={"hormuz": HORMUZ_BOX, "india_west_coast": INDIA_BOX},
        store=store,
        coverage=coverage,
    )
    # _position_report() places the vessel at 26.1N 56.2E — inside Hormuz only.
    ws = FakeWebSocket([_position_report(111222333)])

    await client._consume(ws)

    assert coverage.frame_counts["hormuz"] == 1
    assert coverage.frame_counts["india_west_coast"] == 0


def test_snapshot_in_bbox_filters_to_one_box():
    from app.models import Vessel

    store = VesselStore()
    now = datetime.now(timezone.utc)
    store.upsert(Vessel(mmsi=1, lat=26.1, lon=56.2, sog=0, timestamp=now))  # Hormuz
    store.upsert(Vessel(mmsi=2, lat=20.0, lon=70.0, sog=0, timestamp=now))  # India west coast

    assert {v.mmsi for v in store.snapshot_in_bbox(HORMUZ_BOX.bbox)} == {1}
    assert {v.mmsi for v in store.snapshot_in_bbox(INDIA_BOX.bbox)} == {2}
    assert len(store.snapshot()) == 2
