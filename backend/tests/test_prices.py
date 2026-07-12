import asyncio

import httpx
import pytest

from app.ingestion.prices import AlphaVantageCache, BRENT_FALLBACK_USD_BBL, EiaCache, PriceService

EIA_RESPONSE = {"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}}
ALPHAVANTAGE_RESPONSE = {"data": [{"date": "2026-07-01", "value": "76.20"}]}


@pytest.mark.asyncio
async def test_eia_cache_parses_latest_value():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.eia.gov" in str(request.url)
        return httpx.Response(200, json=EIA_RESPONSE)

    cache = EiaCache(api_key="test-key", ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == pytest.approx(74.50)


@pytest.mark.asyncio
async def test_eia_cache_returns_none_without_key():
    cache = EiaCache(api_key="", ttl=0)
    async with httpx.AsyncClient() as client:
        value = await cache.get(client)

    assert value is None


@pytest.mark.asyncio
async def test_alphavantage_cache_parses_latest_value_and_respects_ttl():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert "alphavantage.co" in str(request.url)
        return httpx.Response(200, json=ALPHAVANTAGE_RESPONSE)

    cache = AlphaVantageCache(api_key="test-key", ttl=3600.0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await cache.get(client)
        second = await cache.get(client)

    assert first == pytest.approx(76.20)
    assert second == pytest.approx(76.20)
    assert call_count == 1  # second call served from the 1-hour cache, never a real request


@pytest.mark.asyncio
async def test_price_service_prefers_alphavantage_over_eia():
    def handler(request: httpx.Request) -> httpx.Response:
        if "alphavantage.co" in str(request.url):
            return httpx.Response(200, json=ALPHAVANTAGE_RESPONSE)
        return httpx.Response(200, json=EIA_RESPONSE)

    service = PriceService(eia_api_key="eia-key", alphavantage_api_key="av-key")
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        price = await service.get_brent_price(client)

    assert price == pytest.approx(76.20)


@pytest.mark.asyncio
async def test_price_service_falls_back_to_eia_when_alphavantage_unset():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EIA_RESPONSE)

    service = PriceService(eia_api_key="eia-key", alphavantage_api_key="")
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        price = await service.get_brent_price(client)

    assert price == pytest.approx(74.50)


@pytest.mark.asyncio
async def test_price_service_falls_back_to_static_constant_when_both_unset():
    service = PriceService(eia_api_key="", alphavantage_api_key="")
    async with httpx.AsyncClient() as client:
        price = await service.get_brent_price(client)

    assert price == BRENT_FALLBACK_USD_BBL


@pytest.mark.asyncio
async def test_eia_cache_concurrent_requests_on_cold_cache_dedupe_to_one_fetch():
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # widen the race window so a real bug reliably reproduces
        return httpx.Response(200, json=EIA_RESPONSE)

    cache = EiaCache(api_key="test-key", ttl=3600.0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        results = await asyncio.gather(*[cache.get(client) for _ in range(10)])

    assert call_count == 1
    assert all(r == pytest.approx(74.50) for r in results)


@pytest.mark.asyncio
async def test_alphavantage_cache_concurrent_requests_on_cold_cache_dedupe_to_one_fetch():
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=ALPHAVANTAGE_RESPONSE)

    cache = AlphaVantageCache(api_key="test-key", ttl=3600.0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        results = await asyncio.gather(*[cache.get(client) for _ in range(10)])

    assert call_count == 1
    assert all(r == pytest.approx(76.20) for r in results)
