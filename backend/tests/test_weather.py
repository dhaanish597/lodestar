import httpx
import pytest

from app.ingestion.weather import WAVE_HEIGHT_THRESHOLD_M, WeatherCache, WeatherService, _bbox_center

HORMUZ_BBOX = (25.2732, 55.1647, 27.3713, 57.3419)
CALM_RESPONSE = {"hourly": {"wave_height": [0.5, 0.6, 0.58]}}
ROUGH_RESPONSE = {"hourly": {"wave_height": [1.2, 4.5, 3.9]}}


def test_bbox_center_is_the_midpoint():
    lat, lon = _bbox_center(HORMUZ_BBOX)
    assert lat == pytest.approx((25.2732 + 27.3713) / 2)
    assert lon == pytest.approx((55.1647 + 57.3419) / 2)


@pytest.mark.asyncio
async def test_calm_seas_give_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "marine-api.open-meteo.com" in str(request.url)
        return httpx.Response(200, json=CALM_RESPONSE)

    cache = WeatherCache(latitude=26.3, longitude=56.3, ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == 0.0


@pytest.mark.asyncio
async def test_rough_seas_above_threshold_give_one():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ROUGH_RESPONSE)

    cache = WeatherCache(latitude=26.3, longitude=56.3, ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client)

    assert value == 1.0
    assert max(ROUGH_RESPONSE["hourly"]["wave_height"]) >= WAVE_HEIGHT_THRESHOLD_M


@pytest.mark.asyncio
async def test_cache_respects_ttl():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=ROUGH_RESPONSE)

    cache = WeatherCache(latitude=26.3, longitude=56.3, ttl=3600.0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await cache.get(client)
        second = await cache.get(client)

    assert first == second == 1.0
    assert call_count == 1


@pytest.mark.asyncio
async def test_fetch_failure_serves_last_cached_value_not_a_crash():
    cache = WeatherCache(latitude=26.3, longitude=56.3, ttl=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        value = await cache.get(client)

    assert value == 0.0  # no prior successful fetch, fails safe to 0


@pytest.mark.asyncio
async def test_service_caches_per_corridor_independently():
    def handler(request: httpx.Request) -> httpx.Response:
        lat = float(request.url.params["latitude"])
        return httpx.Response(200, json=ROUGH_RESPONSE if lat > 20 else CALM_RESPONSE)

    service = WeatherService(ttl=0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hormuz = await service.get_x_weather(client, corridor="hormuz", bbox=HORMUZ_BBOX)
        other = await service.get_x_weather(client, corridor="test_calm", bbox=(1.0, 1.0, 2.0, 2.0))

    assert hormuz == 1.0
    assert other == 0.0
