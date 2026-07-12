# Weather + Freight Connectors, Full 5-Feature Risk Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the risk engine from 2-of-5 live features to 4-of-5 by wiring real Open-Meteo Marine (weather) and FRED (freight) connectors, keep `sanctions` honestly `STUB` (no `OPENSANCTIONS_API_KEY` configured), fix the frontend to label features by their actual live state instead of a hardcoded "— STUB" suffix, sync docs, and produce evidence-based verification.

**Context (investigated this session, not assumed):** Price connectors, scenario cascade, reroute MCDM, and their frontend wiring are already fully committed on `main` (confirmed by reading `prices.py`, `scenario.py`, `reroute.py`, `routes.py`, `ScenarioCard.tsx`, `RerouteCard.tsx` directly, and by `git log`). `docs/03`'s ✅ marks for those items are accurate. The only gap in the 5-feature risk model is `sanctions`/`weather`/`freight`, which are hardcoded `x_*=0.0` in `routes.py`'s `/risk/{corridor}` handler. `FRED_API_KEY` and `EIA_API_KEY`/`ALPHAVANTAGE_API_KEY` are non-empty in `backend/.env`; `OPENSANCTIONS_API_KEY` is empty.

**Architecture:** Two new ingestion modules mirroring `prices.py`'s in-memory TTL-cache-class shape (`_value`/`_last_fetch`, never raises, serves last-good value on error): `weather.py` (per-corridor cache keyed on bbox center, no API key) and `freight.py` (single national-proxy cache, FRED-keyed). Both wired into `app.state` in `main.py`'s guarded-assignment lifespan block, called from `routes.py`'s `/risk/{corridor}` handler alongside the existing kinetic/density fetches, with `feature_states` explicitly marked `LIVE` for both.

**Verified before writing code (raw evidence, not assumption):**
- `curl` against FRED's series-search API (2026-07-10) confirms neither BCTI nor BDI exists as a FRED series — Baltic Exchange doesn't license them to FRED. The closest live substitute is `WPU301301` ("Producer Price Index by Commodity: Transportation Services: Deep Sea Water Transportation of Freight", monthly, BLS via FRED), confirmed reachable with real data through 2026-05 via `GET https://api.stlouisfed.org/fred/series/observations?series_id=WPU301301&api_key=...`.
- `curl` against Open-Meteo Marine for Hormuz's bbox center (26.32, 56.25) returns real hourly `wave_height` data (e.g. `0.58` m at time of check) — confirmed reachable, no key needed.

## Global Constraints

- `sanctions` stays `STUB` in both `DEFAULT_FEATURE_STATES` and the UI — `OPENSANCTIONS_API_KEY` is empty; do not fake it (matches CLAUDE.md "real data over mocks... if you must stub, label it").
- New constants (`WAVE_HEIGHT_THRESHOLD_M`, `WEATHER_CACHE_TTL_SECONDS`, `FREIGHT_SERIES_ID`, `N_BASELINE_MONTHS`, `FREIGHT_STRESS_SCALE_PCT`, `FREIGHT_CACHE_TTL_SECONDS`) must be named module-level constants with an `ASSUMPTION`/`STUB →` comment — never a bare literal — matching `risk.py`/`scenario.py`/`reroute.py` convention.
- Connectors must never raise and must never block a request on a cold cache — same contract as `EiaCache`/`AlphaVantageCache`.
- No secrets in code; `FRED_API_KEY` read only via the existing `Settings.fred_api_key`.
- Update `docs/02`, `docs/03`, `docs/04`, `Readme.md` as part of this same iteration (Task 5), not deferred.
- Follow existing code conventions exactly: TTL-cache class shape from `prices.py`; `app.state` guarded-assignment pattern in `main.py`; tests use `httpx.MockTransport`, mirroring `test_prices.py`.

---

### Task 1: Weather connector — Open-Meteo Marine

**Files:**
- Create: `backend/app/ingestion/weather.py`
- Test: `backend/tests/test_weather.py`

**Interfaces:**
- Consumes: nothing new (`httpx.AsyncClient` passed by caller).
- Produces: `WeatherService(ttl: float = WEATHER_CACHE_TTL_SECONDS)` with `async def get_x_weather(self, client: httpx.AsyncClient, corridor: str, bbox: tuple[float, float, float, float]) -> float` — never raises, always returns `0.0` or `1.0`. Also exports `WeatherCache`, `WAVE_HEIGHT_THRESHOLD_M`, `_bbox_center` for direct testing. Task 3 imports `WeatherService`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_weather.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_weather.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.weather'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ingestion/weather.py
"""Open-Meteo Marine sea-state connector, in-memory TTL cache. No API key
required (10k req/day free tier, docs/02 §6).

Verified reachable 2026-07-10 for the Hormuz bbox center (26.32, 56.25):
GET https://marine-api.open-meteo.com/v1/marine?latitude=26.32&longitude=56.25
&hourly=wave_height,... returned real hourly wave_height data.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# ASSUMPTION -> docs/02 §6, docs/04 §F. Forecast max wave height at/above this
# is flagged as disruption-relevant (X_weather=1); below it, X_weather=0.
WAVE_HEIGHT_THRESHOLD_M = 4.0

# The frontend polls /risk/{corridor} every 10s (RiskPanel.tsx). Without a
# TTL that's one real Open-Meteo call per poll. Hourly forecast data doesn't
# change meaningfully faster than this window.
WEATHER_CACHE_TTL_SECONDS = 1800.0


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    lat_min, lon_min, lat_max, lon_max = bbox
    return (lat_min + lat_max) / 2, (lon_min + lon_max) / 2


class WeatherCache:
    """TTL cache for one corridor's forecast max wave height -> X_weather."""

    def __init__(self, latitude: float, longitude: float, ttl: float = WEATHER_CACHE_TTL_SECONDS):
        self.latitude = latitude
        self.longitude = longitude
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float:
        now = time.monotonic()
        if self._last_fetch > 0 and now - self._last_fetch < self.ttl:
            return self._value

        try:
            response = await client.get(
                OPEN_METEO_MARINE_URL,
                params={
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "hourly": "wave_height,wind_wave_direction,swell_wave_period",
                    "forecast_days": 1,
                },
            )
            response.raise_for_status()
            heights = response.json().get("hourly", {}).get("wave_height", [])
            max_height = max(heights) if heights else 0.0

            self._value = 1.0 if max_height >= WAVE_HEIGHT_THRESHOLD_M else 0.0
            self._last_fetch = now
            logger.info("[OpenMeteo] wave_height_max=%.2fm -> X_weather=%.0f", max_height, self._value)
            return self._value
        except Exception as exc:
            logger.warning("[OpenMeteo] Fetch failed: %s — serving cached %.0f", exc, self._value)
            return self._value


class WeatherService:
    """Per-corridor WeatherCache, keyed on bbox center. Never raises."""

    def __init__(self, ttl: float = WEATHER_CACHE_TTL_SECONDS):
        self.ttl = ttl
        self._caches: dict[str, WeatherCache] = {}

    async def get_x_weather(
        self, client: httpx.AsyncClient, corridor: str, bbox: tuple[float, float, float, float]
    ) -> float:
        if corridor not in self._caches:
            lat, lon = _bbox_center(bbox)
            self._caches[corridor] = WeatherCache(latitude=lat, longitude=lon, ttl=self.ttl)
        return await self._caches[corridor].get(client)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_weather.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/weather.py backend/tests/test_weather.py
git commit -m "feat: add live Open-Meteo Marine weather connector"
```

---

### Task 2: Freight connector — FRED (BCTI/BDI unavailable, substitutes verified live PPI series)

**Files:**
- Create: `backend/app/ingestion/freight.py`
- Test: `backend/tests/test_freight.py`

**Interfaces:**
- Consumes: nothing new (`httpx.AsyncClient` passed by caller).
- Produces: `FreightService(fred_api_key: str, ttl: float = FREIGHT_CACHE_TTL_SECONDS)` with `async def get_x_freight(self, client: httpx.AsyncClient) -> float` — never raises, always returns a value in `[0, 1]`. Also exports `FreightCache`, `FREIGHT_SERIES_ID`, `FREIGHT_STRESS_SCALE_PCT` for direct testing. Task 3 imports `FreightService`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_freight.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_freight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.freight'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ingestion/freight.py
"""FRED freight-stress connector, in-memory TTL cache.

docs/02 §7 specifies BCTI/BDI as the target series. Verified live 2026-07-10
via FRED's series-search API that neither exists as a FRED series -- the
Baltic Exchange does not license them to FRED. The nearest live substitute,
also verified reachable with current data (through 2026-05):
  WPU301301 "Producer Price Index by Commodity: Transportation Services:
  Deep Sea Water Transportation of Freight" (monthly, BLS via FRED).
This is a LIVE connector on a real substitute series, not the static-stub
fallback docs/02 §7 sanctions for a genuinely unreachable feed -- flagged
here because it substitutes the specifically-named series.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

# STUB -> BCTI/BDI unavailable on FRED (verified 2026-07-10); substitute a
# live series. ASSUMPTION: PPI for deep-sea freight transport is a defensible
# systemic ocean-freight-cost proxy, though not a tanker spot index like BCTI.
FREIGHT_SERIES_ID = "WPU301301"

# The series is monthly, not daily, so docs/02 §7's literal "90-day baseline"
# becomes "the ~3 monthly prints preceding the latest one". ASSUMPTION.
N_BASELINE_MONTHS = 3

# ASSUMPTION -> maps pct deviation from baseline onto the risk engine's [0,1]
# feature convention: a deviation at/beyond this magnitude reads as full
# freight stress (X_freight=1.0).
FREIGHT_STRESS_SCALE_PCT = 15.0

FREIGHT_CACHE_TTL_SECONDS = 3600.0


class FreightCache:
    def __init__(self, api_key: str, ttl: float = FREIGHT_CACHE_TTL_SECONDS):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float:
        if not self.api_key:
            return 0.0

        now = time.monotonic()
        if self._last_fetch > 0 and now - self._last_fetch < self.ttl:
            return self._value

        try:
            response = await client.get(
                FRED_URL,
                params={
                    "series_id": FREIGHT_SERIES_ID,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": N_BASELINE_MONTHS + 1,
                },
            )
            response.raise_for_status()
            observations = response.json().get("observations", [])
            values = [float(o["value"]) for o in observations if o.get("value") not in (None, ".")]
            if len(values) < 2:
                logger.debug("[FRED] Not enough observations, serving cached %.3f", self._value)
                return self._value

            latest, baseline_points = values[0], values[1:]
            baseline = sum(baseline_points) / len(baseline_points)
            pct_deviation = ((latest - baseline) / baseline) * 100 if baseline else 0.0

            self._value = max(0.0, min(1.0, abs(pct_deviation) / FREIGHT_STRESS_SCALE_PCT))
            self._last_fetch = now
            logger.info(
                "[FRED] %s latest=%.2f baseline=%.2f deviation=%.1f%% -> X_freight=%.3f",
                FREIGHT_SERIES_ID, latest, baseline, pct_deviation, self._value,
            )
            return self._value
        except Exception as exc:
            logger.warning("[FRED] Fetch failed: %s — serving cached %.3f", exc, self._value)
            return self._value


class FreightService:
    """Thin wrapper so main.py/routes.py mirror WeatherService/PriceService shape."""

    def __init__(self, fred_api_key: str, ttl: float = FREIGHT_CACHE_TTL_SECONDS):
        self._cache = FreightCache(api_key=fred_api_key, ttl=ttl)

    async def get_x_freight(self, client: httpx.AsyncClient) -> float:
        return await self._cache.get(client)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_freight.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/freight.py backend/tests/test_freight.py
git commit -m "feat: add live FRED freight-stress connector (WPU301301 substitute for unavailable BCTI/BDI)"
```

---

### Task 3: Wire weather + freight into `/risk/{corridor}`

**Files:**
- Modify: `backend/app/main.py` (wire `app.state.weather_service` / `app.state.freight_service`)
- Modify: `backend/app/api/routes.py` (`get_risk` fetches and passes live weather/freight)
- Modify: `backend/tests/test_routes.py` (add coverage + realistic mock handlers)

**Interfaces:**
- Consumes: `WeatherService` (Task 1), `FreightService` (Task 2).
- Produces: `/risk/{corridor}` response now has `feature_states.weather == "LIVE"` and `feature_states.freight == "LIVE"` whenever the services are wired (regardless of whether the underlying fetch succeeded this cycle — matches the existing `kinetic` convention, which is always `LIVE` even though `fetch_kinetic_volume` can silently serve a cached/zero value on transient failure).

- [ ] **Step 1: Wire the services into `main.py` lifespan**

In `backend/app/main.py`, add imports:

```python
from app.ingestion.freight import FreightService
from app.ingestion.weather import WeatherService
```

In `lifespan()`, immediately after the existing `price_service` guarded-assignment block, add:

```python
    if not hasattr(app.state, 'weather_service') or app.state.weather_service is None:
        app.state.weather_service = WeatherService()
    if not hasattr(app.state, 'freight_service') or app.state.freight_service is None:
        app.state.freight_service = FreightService(fred_api_key=settings.fred_api_key)
```

- [ ] **Step 2: Write the failing test**

Add these mock handlers and tests to `backend/tests/test_routes.py`. First, extend `_mock_handler` (used by `_app_with_mocks`) to also serve weather/freight:

```python
def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "gdeltproject.org" in url:
        return httpx.Response(200, json=GDELT_RESPONSE)
    if "alphavantage.co" in url:
        return httpx.Response(200, json={"data": [{"date": "2026-07-01", "value": "76.20"}]})
    if "api.eia.gov" in url:
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}})
    if "marine-api.open-meteo.com" in url:
        return httpx.Response(200, json={"hourly": {"wave_height": [1.0, 4.5, 2.0]}})
    if "api.stlouisfed.org" in url:
        return httpx.Response(200, json={"observations": [
            {"date": "2026-05-01", "value": "130.0"},
            {"date": "2026-04-01", "value": "100.0"},
            {"date": "2026-03-01", "value": "100.0"},
            {"date": "2026-02-01", "value": "100.0"},
        ]})
    return httpx.Response(404)
```

Then update `test_risk_hormuz_returns_full_breakdown` to assert liveness, and add a dedicated test:

```python
def test_risk_hormuz_returns_full_breakdown(monkeypatch):
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["corridor"] == "hormuz"
    assert set(body["contributions"]) == {"kinetic", "density", "sanctions", "weather", "freight"}
    assert set(body["feature_states"]) == set(body["contributions"])


def test_risk_hormuz_weather_and_freight_are_live_not_stub():
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    body = resp.json()
    assert body["feature_states"]["weather"] == "LIVE"
    assert body["feature_states"]["freight"] == "LIVE"
    assert body["feature_states"]["sanctions"] == "STUB"  # no OPENSANCTIONS_API_KEY
    # mocked wave_height max 4.5m >= 4.0m threshold -> X_weather=1 -> nonzero contribution
    assert body["features"]["weather"] == 1.0
    assert body["contributions"]["weather"] > 0.0
    # mocked FRED: latest 130 vs baseline avg 100 -> +30% deviation -> clipped to 1.0
    assert body["features"]["freight"] == pytest.approx(1.0)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_routes.py -v -k weather_and_freight`
Expected: FAIL — `feature_states["weather"] == "STUB"`, not `"LIVE"` (routes.py doesn't fetch them yet)

- [ ] **Step 4: Implement the wiring**

In `backend/app/api/routes.py`, inside `get_risk`, replace:

```python
    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    x_density = density_tracker.x_density()

    return compute_risk(
        corridor=corridor,
        x_kinetic=x_kinetic,
        x_density=x_density,
        feature_states={"density": density_state},
    )
```

with:

```python
    weather_service = request.app.state.weather_service
    freight_service = request.app.state.freight_service

    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    x_density = density_tracker.x_density()
    x_weather = await weather_service.get_x_weather(http_client, corridor=corridor, bbox=corridor_bbox)
    x_freight = await freight_service.get_x_freight(http_client)

    return compute_risk(
        corridor=corridor,
        x_kinetic=x_kinetic,
        x_density=x_density,
        x_weather=x_weather,
        x_freight=x_freight,
        feature_states={"density": density_state, "weather": "LIVE", "freight": "LIVE"},
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS — full suite green, including `test_risk.py` (unchanged, still tests `compute_risk` directly with its own defaults) and all of `test_routes.py`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/api/routes.py backend/tests/test_routes.py
git commit -m "feat: wire live weather + freight into /risk/{corridor}, risk engine now 4-of-5 live"
```

---

### Task 4: Frontend — stop hardcoding "— STUB", label by actual feature state

**Files:**
- Modify: `frontend/components/RiskPanel.tsx`

**Interfaces:**
- Consumes: `RiskScore.feature_states` (already in `frontend/lib/types.ts`, unchanged).

- [ ] **Step 1: Replace the hardcoded labels and render the STUB suffix conditionally**

In `frontend/components/RiskPanel.tsx`, replace:

```tsx
const FEATURE_LABELS: Record<string, string> = {
  kinetic: "Kinetic news (GDELT)",
  density: "Vessel density anomaly (AIS)",
  sanctions: "Sanctions exposure — STUB",
  weather: "Sea state — STUB",
  freight: "Freight stress — STUB",
};
```

with:

```tsx
const FEATURE_LABELS: Record<string, string> = {
  kinetic: "Kinetic news (GDELT)",
  density: "Vessel density anomaly (AIS)",
  sanctions: "Sanctions exposure (OpenSanctions)",
  weather: "Sea state (Open-Meteo)",
  freight: "Freight stress (FRED)",
};
```

Then, inside the `.map(([feature, contribution]) => ...)` block, change the label line from:

```tsx
              <div style={{ fontSize: 12, opacity: 0.8 }}>{FEATURE_LABELS[feature] ?? feature}</div>
```

to:

```tsx
              <div style={{ fontSize: 12, opacity: 0.8 }}>
                {FEATURE_LABELS[feature] ?? feature}
                {state === "STUB" ? " — STUB" : ""}
              </div>
```

(`state` is already computed one line above this block via `const state = risk.feature_states?.[feature];` — no new variable needed.)

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/RiskPanel.tsx
git commit -m "fix: label risk features by actual live/stub state instead of hardcoded STUB suffix"
```

---

### Task 5: Docs sync

**Files:**
- Modify: `docs/02_data_sources_and_schemas.md`
- Modify: `docs/03_build_plan_and_deliverables.md`
- Modify: `docs/04_model_assumptions_and_constants.md`
- Modify: `Readme.md`

- [ ] **Step 1: Update `docs/02_data_sources_and_schemas.md`**

In §6 (Open-Meteo Marine), append an "Implementation note" paragraph (mirroring the GDELT/EIA style): points to `backend/app/ingestion/weather.py`, describes the per-corridor `WeatherCache` (keyed on bbox center), the 1800s TTL, and the `WAVE_HEIGHT_THRESHOLD_M = 4.0` constant.

In §7 (FRED), append an "Implementation note": points to `backend/app/ingestion/freight.py`, states plainly that BCTI/BDI were confirmed unavailable on FRED via a live series-search on 2026-07-10, names `WPU301301` as the substitute series and why (deep-sea freight PPI, real ocean-shipping-cost proxy), and documents the monthly-cadence `N_BASELINE_MONTHS = 3` adaptation of the "90-day baseline" spec language plus the `FREIGHT_STRESS_SCALE_PCT = 15.0` normalization.

- [ ] **Step 2: Update `docs/03_build_plan_and_deliverables.md`**

Flip these rows:
- `Open-Meteo + FRED connectors | Teammate | Scale | ⬜` → `✅ (live — Open-Meteo Marine wave height; FRED WPU301301 substitutes unavailable BCTI/BDI, docs/02 §7)`
- `Risk engine (sigmoid + weighted features + per-feature breakdown) | You | Innov/Tech | 🟨 (...)` → `🟨 (kinetic/density/weather/freight live; sanctions stubbed — OPENSANCTIONS_API_KEY not configured)`

Leave `OpenSanctions vessel screening | You | Innov | ⬜` as-is (genuinely not built — key absent).

- [ ] **Step 3: Update `docs/04_model_assumptions_and_constants.md`**

Update §A's "Phase 1 implementation status" line to: "`X_kinetic`, `X_density`, `X_weather`, `X_freight` are live; `X_sanctions` remains `STUB → 0.0` — `OPENSANCTIONS_API_KEY` is not configured (Phase 2)."

Append a new `## F. Weather & freight connectors — implementation constants (Phase 2)` section (after §E) documenting: `WAVE_HEIGHT_THRESHOLD_M = 4.0`, `WEATHER_CACHE_TTL_SECONDS = 1800.0` (`backend/app/ingestion/weather.py`); and `FREIGHT_SERIES_ID = "WPU301301"` with the BCTI/BDI-unavailability finding and citation of the verification date, `N_BASELINE_MONTHS = 3`, `FREIGHT_STRESS_SCALE_PCT = 15.0`, `FREIGHT_CACHE_TTL_SECONDS = 3600.0` (`backend/app/ingestion/freight.py`).

- [ ] **Step 4: Update `Readme.md`**

In the repo structure block, add `ingestion/weather.py` and `ingestion/freight.py` to the present-tense listing. In "Model assumptions & limitations", add a bullet: "Freight-stress feature (`X_freight`) uses FRED's deep-sea freight PPI (`WPU301301`) as a live substitute for BCTI/BDI, which are not available on FRED (verified 2026-07-10) — labeled in `docs/02` §7 and `freight.py`."

- [ ] **Step 5: Commit**

```bash
git add docs/02_data_sources_and_schemas.md docs/03_build_plan_and_deliverables.md docs/04_model_assumptions_and_constants.md Readme.md
git commit -m "docs: sync tracker and assumptions doc with live weather + freight connectors"
```

---

### Task 6: Evidence-based verification (light re-check + exit test)

**Files:** none (verification only — no code changes)

- [ ] **Step 1: Bring the stack up**

Run: `docker-compose up -d --build`
Expected: `api`, `web`, `redis` containers healthy. Capture `docker-compose ps` output as evidence.

- [ ] **Step 2: Full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests pass, including the 12 new tests from Tasks 1–3. Capture the pass count.

- [ ] **Step 3: Live spot-check against the running system (light re-verification of Phase 1's 9 checks)**

Run each, capture raw output:
- `curl http://localhost:8000/health` → expect `{"status":"ok"}`
- `curl http://localhost:8000/coverage` → expect per-box states, confirms AIS pipeline alive
- `curl http://localhost:8000/risk/hormuz` → expect `feature_states` showing `kinetic: LIVE, density: <LIVE|WARMING_UP|NO_TERRESTRIAL_COVERAGE>, sanctions: STUB, weather: LIVE, freight: LIVE`, and `features.weather`/`features.freight` populated (not silently 0.0 from a dead connector — check the backend logs for `[OpenMeteo]`/`[FRED]` fetch lines)
- `curl http://localhost:8000/scenario/hormuz` and `curl http://localhost:8000/reroute/hormuz` → expect full cascade / 6 ranked options (unchanged from Task 1-4 of the prior plan, confirms no regression)
- Backend logs, `docker-compose logs api --tail 200`: confirm no repeated GDELT 429s, no unhandled exceptions from the new connectors

- [ ] **Step 4: Exit-test confirmation — weather/freight now visibly live in the UI**

Open `http://localhost:3000`, look at the Risk panel's per-feature contribution bars. Confirm:
- "Sea state (Open-Meteo)" and "Freight stress (FRED)" no longer show the STUB badge/suffix and instead render as a normal contribution bar (possibly empty/zero-width if current conditions are calm — that's a correct reading, not a bug, given wave height was ~0.58m at investigation time).
- "Sanctions exposure (OpenSanctions)" still shows the STUB badge.
Capture a screenshot as evidence.

- [ ] **Step 5: Record results**

No commit for this task — append a dated section to `docs/PHASE1_VERIFICATION_REPORT.md` (or a new `docs/PHASE2_WEATHER_FREIGHT_VERIFICATION_REPORT.md`) with the raw command outputs from Steps 2–4, timestamped.

---

## Self-Review Notes

- **Spec coverage:** ✅ Open-Meteo Marine weather connector, live, threshold-based (Task 1) · ✅ FRED freight connector, live, with the BCTI/BDI-unavailability finding disclosed rather than silently substituted (Task 2) · ✅ wired into risk engine with explicit `LIVE` states (Task 3) · ✅ sanctions honestly left `STUB` per the ground rules, key absent (no task — explicitly out of scope, documented) · ✅ frontend no longer mislabels live features as STUB (Task 4) · ✅ docs updated same-iteration (Task 5) · ✅ evidence-based verification, not self-report (Task 6).
- **No placeholders:** every code step has complete, runnable code. `STUB →`/`ASSUMPTION` labels are intentional per CLAUDE.md, not plan placeholders.
- **Type consistency checked:** `WeatherService.get_x_weather` / `FreightService.get_x_freight` signatures match their call sites in Task 3's `routes.py` edit exactly; `RiskScore.feature_states` (existing model, unchanged) already supports arbitrary state strings so no `models.py` change is needed.
- **Not in scope, flagged not silently dropped:** OpenSanctions (key absent — stays STUB), the stale `worktree-phase2-engines` git worktree (flagged to the user, not touched), a full cold-restart Phase 1 re-verification (user chose the light-recheck option).
