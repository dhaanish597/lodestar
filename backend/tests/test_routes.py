# backend/tests/test_routes.py
import httpx
import pytest
from fastapi.testclient import TestClient

from app.ingestion.aisstream import VesselStore
from app.ingestion.density import DensityTracker
from app.main import app

GDELT_RESPONSE = {"timeline": [{"data": [{"date": "20260701", "value": 3}, {"date": "20260702", "value": 6}]}]}


def test_risk_hormuz_returns_full_breakdown(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=GDELT_RESPONSE)

    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["corridor"] == "hormuz"
    assert set(body["contributions"]) == {"kinetic", "density", "sanctions", "weather", "freight"}


def test_risk_unknown_corridor_is_404():
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.http_client = httpx.AsyncClient()

    with TestClient(app) as client:
        resp = client.get("/risk/malacca")

    assert resp.status_code == 404
