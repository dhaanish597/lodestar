# backend/tests/test_gdelt.py
import httpx
import pytest

from app.ingestion.gdelt import GdeltCache

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

    cache = GdeltCache(ttl=0)  # fresh cache, no TTL for test
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == pytest.approx(1.0)  # latest point (10) is the max of the series


@pytest.mark.asyncio
async def test_fetch_kinetic_volume_handles_empty_timeline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"timeline": []})

    cache = GdeltCache(ttl=0)  # fresh cache — default value is 0.0
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == 0.0


@pytest.mark.asyncio
async def test_429_returns_cached_value_and_backs_off():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=GDELT_RESPONSE)
        return httpx.Response(429, headers={"Retry-After": "60"})

    cache = GdeltCache(ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await cache.get(client)
        assert first == pytest.approx(1.0)

        # Force cache expiry so it tries a second fetch
        cache._last_fetch = 0.0
        second = await cache.get(client)
        # Should serve the cached value, not crash
        assert second == pytest.approx(1.0)

        # Should still be rate-limited (Retry-After=60s)
        third = await cache.get(client)
        assert third == pytest.approx(1.0)
        # Only 2 real requests should have been made (third was served from cache)
        assert call_count == 2
