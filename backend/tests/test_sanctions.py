# backend/tests/test_sanctions.py
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.ingestion.sanctions import SanctionsCache, SanctionsService
from app.models import Vessel


def _vessel(mmsi: int) -> Vessel:
    return Vessel(mmsi=mmsi, lat=26.0, lon=56.0, sog=10.0, timestamp=datetime.now(timezone.utc))


def _handler_for(flagged_mmsi: set[int], call_counter: list[int] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if call_counter is not None:
            call_counter[0] += 1
        payload = json.loads(request.read())
        responses = {}
        for key, q in payload["queries"].items():
            mmsi = int(q["properties"]["mmsi"][0])
            topics = ["sanction"] if mmsi in flagged_mmsi else []
            results = (
                [{"score": 0.99, "id": "x", "caption": "x", "properties": {"topics": topics}}]
                if topics
                else []
            )
            responses[key] = {"status": 200, "results": results}
        return httpx.Response(200, json={"responses": responses})

    return handler


@pytest.mark.asyncio
async def test_no_key_returns_zero_without_request():
    called = [0]
    cache = SanctionsCache(api_key="")
    transport = httpx.MockTransport(_handler_for(set(), called))
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client, [_vessel(1)])
    assert value == 0.0
    assert called[0] == 0


@pytest.mark.asyncio
async def test_no_vessels_returns_zero_without_request():
    called = [0]
    cache = SanctionsCache(api_key="test-key")
    transport = httpx.MockTransport(_handler_for(set(), called))
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client, [])
    assert value == 0.0
    assert called[0] == 0


@pytest.mark.asyncio
async def test_flagged_ratio_computed_from_topics():
    transport = httpx.MockTransport(_handler_for({111}))
    cache = SanctionsCache(api_key="test-key", ttl=3600.0)
    async with httpx.AsyncClient(transport=transport) as client:
        value = await cache.get(client, [_vessel(111), _vessel(222), _vessel(333), _vessel(444)])
    assert value == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_cache_respects_ttl_for_same_fleet():
    called = [0]
    transport = httpx.MockTransport(_handler_for({111}, called))
    cache = SanctionsCache(api_key="test-key", ttl=3600.0)
    vessels = [_vessel(111), _vessel(222)]
    async with httpx.AsyncClient(transport=transport) as client:
        first = await cache.get(client, vessels)
        second = await cache.get(client, vessels)
    assert first == second
    assert called[0] == 1


@pytest.mark.asyncio
async def test_changed_fleet_triggers_refetch_even_within_ttl():
    called = [0]
    transport = httpx.MockTransport(_handler_for({111}, called))
    cache = SanctionsCache(api_key="test-key", ttl=3600.0)
    async with httpx.AsyncClient(transport=transport) as client:
        await cache.get(client, [_vessel(111), _vessel(222)])
        await cache.get(client, [_vessel(111), _vessel(333)])
    assert called[0] == 2


@pytest.mark.asyncio
async def test_service_wraps_cache():
    transport = httpx.MockTransport(_handler_for(set()))
    service = SanctionsService(api_key="test-key")
    async with httpx.AsyncClient(transport=transport) as client:
        value = await service.get_x_sanctions(client, [_vessel(1)])
    assert value == 0.0
    assert service.has_key is True


@pytest.mark.asyncio
async def test_cache_concurrent_requests_on_cold_cache_dedupe_to_one_fetch():
    import asyncio

    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # widen the race window so a real bug reliably reproduces
        payload = json.loads(request.read())
        responses = {key: {"status": 200, "results": []} for key in payload["queries"]}
        return httpx.Response(200, json={"responses": responses})

    cache = SanctionsCache(api_key="test-key", ttl=3600.0)
    vessels = [_vessel(1), _vessel(2)]
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        results = await asyncio.gather(*[cache.get(client, vessels) for _ in range(10)])

    assert call_count == 1
    assert all(r == 0.0 for r in results)
