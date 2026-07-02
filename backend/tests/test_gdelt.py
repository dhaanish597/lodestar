# backend/tests/test_gdelt.py
import httpx
import pytest

from app.ingestion.gdelt import fetch_kinetic_volume

GDELT_RESPONSE = {
    "timeline": [
        {
            "data": [
                {"date": "20260629", "value": 1},
                {"date": "20260630", "value": 4},
                {"date": "20260701", "value": 10},
            ]
        }
    ]
}


@pytest.mark.asyncio
async def test_fetch_kinetic_volume_minmax_scales_latest_point():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "gdeltproject.org" in str(request.url)
        return httpx.Response(200, json=GDELT_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await fetch_kinetic_volume(client)

    assert value == pytest.approx(1.0)  # latest point (10) is the max of the series


@pytest.mark.asyncio
async def test_fetch_kinetic_volume_handles_empty_timeline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"timeline": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await fetch_kinetic_volume(client)

    assert value == 0.0
