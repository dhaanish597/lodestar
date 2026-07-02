# backend/tests/test_aisstream.py
import json
from datetime import datetime, timezone

import pytest

from app.config import Corridor
from app.ingestion.aisstream import AISStreamClient, VesselStore


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


@pytest.mark.asyncio
async def test_consume_subscribes_within_first_send_and_parses_position_reports():
    store = VesselStore()
    corridor = Corridor(bbox=(25.2732, 55.1647, 27.3713, 57.3419))
    client = AISStreamClient(api_key="testkey", corridor=corridor, store=store)
    ws = FakeWebSocket([_position_report(111222333), _position_report(444555666)])

    await client._consume(ws)

    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["APIKey"] == "testkey"
    assert payload["BoundingBoxes"] == [[[25.2732, 55.1647], [27.3713, 57.3419]]]
    assert payload["FilterMessageTypes"] == ["PositionReport"]

    snap = store.snapshot()
    assert {v.mmsi for v in snap} == {111222333, 444555666}
