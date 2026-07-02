from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.ingestion.aisstream import VesselStore
from app.main import app
from app.models import Vessel


def test_ws_vessels_streams_current_snapshot():
    store = VesselStore()
    store.upsert(Vessel(mmsi=9, lat=26.5, lon=56.1, sog=10.0, timestamp=datetime.now(timezone.utc)))
    app.state.vessel_store = store

    with TestClient(app) as client:
        with client.websocket_connect("/ws/vessels") as ws:
            payload = ws.receive_json()

    assert isinstance(payload, list)
    assert payload[0]["mmsi"] == 9
