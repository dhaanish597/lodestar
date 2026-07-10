import httpx
import pytest

from app.ingestion.freight import FreightCache, FreightService


def _fred_response(values_desc: list[float]) -> dict:
    """values_desc[0] is the most recent observation, mirroring FRED's
    sort_order=desc (which the connector requests)."""
    return {"observations": [{"date": "2026-01-01", "value": str(v)} for v in values_desc]}


@pytest.mark.asyncio
async def test_no_key_returns_zero_without_request():
    cache = FreightCache(api_key="", ttl=0)
    async with httpx.AsyncClient() as client:
        value = await cache.get(client)
    assert value == 0.0


@pytest.mark.asyncio
async def test_stable_series_gives_near_zero_stress():
    payload = _fred_response([100.0, 100.0, 100.0, 100.0])

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.stlouisfed.org" in str(request.url)
        return httpx.Response(200, json=payload)

    cache = FreightCache(api_key="test-key", ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == pytest.approx(0.0, abs=1e-6)


@pytest.mark.asyncio
async def test_spike_above_scale_clips_to_one():
    # baseline (avg of last 3) = 100, latest = 130 -> +30% deviation, scale is 15% -> clipped to 1.0
    payload = _fred_response([130.0, 100.0, 100.0, 100.0])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    cache = FreightCache(api_key="test-key", ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == 1.0


@pytest.mark.asyncio
async def test_moderate_deviation_scales_linearly():
    # baseline = 100, latest = 107.5 -> +7.5% deviation, scale 15% -> 0.5
    payload = _fred_response([107.5, 100.0, 100.0, 100.0])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    cache = FreightCache(api_key="test-key", ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == pytest.approx(0.5, abs=1e-6)


@pytest.mark.asyncio
async def test_cache_respects_ttl():
    call_count = 0
    payload = _fred_response([107.5, 100.0, 100.0, 100.0])

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=payload)

    cache = FreightCache(api_key="test-key", ttl=3600.0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await cache.get(client)
        second = await cache.get(client)

    assert first == second
    assert call_count == 1


@pytest.mark.asyncio
async def test_service_wraps_cache():
    payload = _fred_response([100.0, 100.0, 100.0, 100.0])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    service = FreightService(fred_api_key="test-key", ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await service.get_x_freight(client)

    assert value == pytest.approx(0.0, abs=1e-6)
