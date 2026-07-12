# Phase 2 — Scenario Cascade, Reroute MCDM & Price Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the scenario cascade and reroute MCDM engines (both deterministic, per `docs/04`), add live EIA + Alpha Vantage price connectors, expose every scenario assumption as a live-readout frontend slider, and constrain reroute ranking by the `grade_match` matrix from a new `crude_grades.json` — so dragging the disruption-% slider visibly re-cascades and re-ranks in the browser.

**Architecture:** Two new pure, dependency-free engine modules (`scenario.py`, `reroute.py`) mirroring the existing `risk.py` pattern — plain functions in, typed Pydantic models out, fully unit-testable without I/O. A new `prices.py` ingestion module mirrors `gdelt.py`'s proven TTL-cache pattern for EIA (weekly baseline) and Alpha Vantage (hourly-capped intraday), orchestrated by a `PriceService` with a static fallback so the app never blocks on a missing key. Two new routes (`/scenario/{corridor}`, `/reroute/{corridor}`) glue engines to live price data. The frontend lifts scenario slider state to `page.tsx` so both the cascade readout and the reroute ranking react to the same `disruption_factor` in real time, debounced 250ms.

**Tech Stack:** FastAPI + Pydantic v2 (backend, unchanged), httpx (price connectors, mirrors existing GDELT connector), pytest + pytest-asyncio + `httpx.MockTransport` (tests, mirrors `test_gdelt.py`), Next.js/React (frontend, no new dependencies — native `<input type="range">`, no slider library needed).

## Global Constraints

- Risk engine (`risk.py`) is **out of scope** — already implements the full 5-feature weighted sigmoid + contribution breakdown; `X_sanctions`/`X_weather`/`X_freight` stay `STUB → 0.0` per the cut-list (user-confirmed this session).
- Reroute MCDM weights (docs/04 §C, `ASSUMPTION`): `w_cost=0.35, w_time=0.25, w_grade=0.30, w_cong=0.10`.
- `grade_match ∈ {1.0 ideal, 0.5 needs blending, 0.0 incompatible}` — read directly from `crude_grades.json` as **a hard input**, never computed at request time (docs/04 §C: "the defensibility centrepiece").
- Scenario cascade sourced/anchored constants (docs/04 §B): SPR dedicated buffer = **9.5 days at 100% fill**; OMC commercial buffer = **64.5 days**; GDP drag = **15 bps per 10% crude price rise** (dossier 2019 Abqaiq anchor); RBI CPI rule = **+0.3–0.4 pp per 10% crude basket rise**.
- Scenario sliders and their doc-specified ranges: `disruption_factor` 0–1, `substitution_rate` 0–1, `hormuz_share` 0.30–0.60, `spr_fill_pct` 0–1, `cpi_sensitivity` 0.3–0.4, `cad_sensitivity` 0.2–0.5 (ASSUMPTION range).
- Alpha Vantage hard cap: **25 requests/day** → cache TTL must guarantee ≤1 real call/hour (≤24/day), and must never fire directly on a page load — only on TTL expiry.
- No secrets in code; `EIA_API_KEY` / `ALPHAVANTAGE_API_KEY` already present in `backend/.env` (read via existing `Settings`).
- New assumption constants introduced by this plan (`price_sensitivity`, freight/congestion proxies) must be named module-level constants with an `ASSUMPTION`/`STUB →` comment, never bare numeric literals — matches the existing `BETA0`/`WEIGHTS` pattern in `risk.py`.
- Follow existing code conventions exactly: pure engine functions take primitives and return the Pydantic model; connectors follow the `GdeltCache` TTL-cache shape (`_value`, `_last_fetch`, graceful fallback on any exception, `logger.info`/`warning` on fetch/failure); `app.state` services use the "guarded assignment" pattern in `main.py` so tests can pre-mock them.

---

### Task 1: Price Connectors — EIA baseline + Alpha Vantage cached intraday

**Files:**
- Create: `backend/app/ingestion/prices.py`
- Test: `backend/tests/test_prices.py`

**Interfaces:**
- Consumes: nothing new (uses `httpx.AsyncClient` passed by caller, same as `gdelt.py`).
- Produces: `PriceService(eia_api_key: str, alphavantage_api_key: str)` with `async def get_brent_price(self, client: httpx.AsyncClient) -> float` — never raises, always returns a float. Also exports `EiaCache`, `AlphaVantageCache`, `BRENT_FALLBACK_USD_BBL` for direct testing. Tasks 2–4 depend on `PriceService.get_brent_price`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_prices.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.prices'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ingestion/prices.py
"""EIA (weekly baseline) + Alpha Vantage (cached intraday) Brent price connectors.

Alpha Vantage free tier caps at 25 requests/day (docs/02 §5). The
AlphaVantageCache TTL (3600s) guarantees at most one real outbound call per
hour regardless of how often the frontend polls -- 24 calls/day max, safely
under the cap, and never triggered directly by a page load. EIA spot prices
publish weekly (~Tuesdays) per docs/02 §2, so it serves as the fallback
baseline when Alpha Vantage is unset or unreachable.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

EIA_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"

# ASSUMPTION -> served only if both EIA and Alpha Vantage are unset/unreachable
# (e.g. no keys configured in a fresh dev environment). docs/04 §B.
BRENT_FALLBACK_USD_BBL = 75.0


class EiaCache:
    """TTL cache for EIA daily Brent spot price (weekly-cadence data, key required)."""

    def __init__(self, api_key: str, ttl: float = 3600.0):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float | None = None
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float | None:
        if not self.api_key:
            return None

        now = time.monotonic()
        if now - self._last_fetch < self.ttl and self._value is not None:
            return self._value

        try:
            response = await client.get(
                EIA_URL,
                params={
                    "api_key": self.api_key,
                    "frequency": "daily",
                    "data[]": "value",
                    "facets[series][]": "DCOILBRENTEU",
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": 5,
                },
            )
            response.raise_for_status()
            rows = response.json()["response"]["data"]
            if not rows:
                logger.debug("[EIA] Empty data array, serving cached %s", self._value)
                return self._value

            self._value = float(rows[0]["value"])
            self._last_fetch = now
            logger.info("[EIA] Fetched Brent baseline: %.2f", self._value)
            return self._value
        except Exception as exc:
            logger.warning("[EIA] Fetch failed: %s — serving cached %s", exc, self._value)
            return self._value


class AlphaVantageCache:
    """TTL cache for Alpha Vantage Brent quote. Mandatory 1-hour TTL -> 25 req/day cap."""

    def __init__(self, api_key: str, ttl: float = 3600.0):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float | None = None
        self._last_fetch: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> float | None:
        if not self.api_key:
            return None

        now = time.monotonic()
        if now - self._last_fetch < self.ttl and self._value is not None:
            return self._value

        try:
            response = await client.get(
                ALPHAVANTAGE_URL,
                params={"function": "BRENT", "interval": "daily", "apikey": self.api_key},
            )
            response.raise_for_status()
            rows = response.json().get("data", [])
            if not rows:
                logger.debug("[AlphaVantage] Empty data array, serving cached %s", self._value)
                return self._value

            self._value = float(rows[0]["value"])
            self._last_fetch = now
            logger.info("[AlphaVantage] Fetched Brent intraday: %.2f", self._value)
            return self._value
        except Exception as exc:
            logger.warning("[AlphaVantage] Fetch failed: %s — serving cached %s", exc, self._value)
            return self._value


class PriceService:
    """Orchestrates Alpha Vantage (preferred, intraday-ish) with EIA (weekly
    baseline) and a static fallback -- never raises, always returns a usable price."""

    def __init__(self, eia_api_key: str, alphavantage_api_key: str):
        self.eia_cache = EiaCache(api_key=eia_api_key)
        self.alphavantage_cache = AlphaVantageCache(api_key=alphavantage_api_key)

    async def get_brent_price(self, client: httpx.AsyncClient) -> float:
        alphavantage_value = await self.alphavantage_cache.get(client)
        if alphavantage_value is not None:
            return alphavantage_value

        eia_value = await self.eia_cache.get(client)
        if eia_value is not None:
            return eia_value

        logger.warning(
            "[PriceService] No live price available, serving fallback %.2f", BRENT_FALLBACK_USD_BBL
        )
        return BRENT_FALLBACK_USD_BBL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_prices.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/prices.py backend/tests/test_prices.py
git commit -m "feat: add EIA + Alpha Vantage cached price connectors"
```

---

### Task 2: Scenario Cascade Engine

**Files:**
- Modify: `backend/app/models.py` (add 3 fields to `Scenario`)
- Create: `backend/app/engine/scenario.py`
- Test: `backend/tests/test_scenario.py`

**Interfaces:**
- Consumes: nothing (pure function, no I/O).
- Produces: `compute_scenario(corridor: str, disruption_factor=0.30, substitution_rate=0.20, hormuz_share=0.45, india_imports_mbd=4.7, spr_fill_pct=0.64, cpi_sensitivity=0.35, cad_sensitivity=0.35, price_sensitivity=PRICE_SENSITIVITY, brent_baseline_usd_bbl=BRENT_BASELINE_USD_BBL) -> Scenario` and `crude_price_rise_pct(disruption_factor: float, price_sensitivity: float = PRICE_SENSITIVITY) -> float` (percentage, e.g. `30.0` for 30%). Task 3 imports `crude_price_rise_pct` and `PRICE_SENSITIVITY`. Task 4 imports `compute_scenario`.

- [ ] **Step 1: Add new `Scenario` fields**

In `backend/app/models.py`, extend the `Scenario` class (after `cad_widening_pct_gdp`):

```python
    crude_price_rise_pct: float
    price_sensitivity: float
    brent_baseline_usd_bbl: float
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_scenario.py
import pytest

from app.engine.scenario import (
    GDP_DRAG_BPS_PER_10PCT,
    OMC_COMMERCIAL_DAYS,
    SPR_DEDICATED_DAYS_AT_FULL_FILL,
    compute_scenario,
    crude_price_rise_pct,
)


def test_zero_disruption_gives_zero_gap_and_full_buffer_days():
    s = compute_scenario(corridor="hormuz", disruption_factor=0.0)
    assert s.supply_gap_mbd == 0.0
    assert s.utilization_drop_pct == 0.0
    assert s.crude_price_rise_pct == 0.0
    assert s.cpi_delta_pp == 0.0
    assert s.gdp_drag_bps == 0.0
    assert s.cad_widening_pct_gdp == 0.0
    expected_buffer_days = SPR_DEDICATED_DAYS_AT_FULL_FILL * 0.64 + OMC_COMMERCIAL_DAYS
    assert s.days_cover_remaining == pytest.approx(expected_buffer_days)


def test_supply_gap_formula():
    s = compute_scenario(
        corridor="hormuz",
        disruption_factor=0.5,
        substitution_rate=0.25,
        hormuz_share=0.40,
        india_imports_mbd=5.0,
    )
    expected = (5.0 * 0.40) * 0.5 * (1 - 0.25)
    assert s.supply_gap_mbd == pytest.approx(expected)


def test_higher_disruption_shrinks_days_cover_remaining():
    low = compute_scenario(corridor="hormuz", disruption_factor=0.1)
    high = compute_scenario(corridor="hormuz", disruption_factor=0.8)
    assert high.days_cover_remaining < low.days_cover_remaining


def test_price_rise_pct_scales_with_disruption_and_sensitivity():
    assert crude_price_rise_pct(disruption_factor=0.3, price_sensitivity=1.0) == pytest.approx(30.0)
    assert crude_price_rise_pct(disruption_factor=0.3, price_sensitivity=0.5) == pytest.approx(15.0)


def test_cpi_gdp_cad_formulas_are_internally_consistent():
    s = compute_scenario(
        corridor="hormuz",
        disruption_factor=0.4,
        cpi_sensitivity=0.35,
        cad_sensitivity=0.4,
        brent_baseline_usd_bbl=80.0,
    )
    assert s.cpi_delta_pp == pytest.approx((s.crude_price_rise_pct / 10) * 0.35)
    assert s.gdp_drag_bps == pytest.approx((s.crude_price_rise_pct / 10) * GDP_DRAG_BPS_PER_10PCT)
    crude_usd_increase = 80.0 * (s.crude_price_rise_pct / 100)
    assert s.cad_widening_pct_gdp == pytest.approx((crude_usd_increase / 10) * 0.4)


def test_all_scenario_fields_round_trip_inputs():
    s = compute_scenario(corridor="hormuz", disruption_factor=0.3, spr_fill_pct=0.5)
    assert s.corridor == "hormuz"
    assert s.disruption_factor == 0.3
    assert s.spr_fill_pct == 0.5
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_scenario.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.scenario'`

- [ ] **Step 4: Write the implementation**

```python
# backend/app/engine/scenario.py
"""5-step macroeconomic cascade: supply gap -> refinery utilization -> SPR days
cover -> CPI -> GDP/CAD. All formulas and sourced anchors are docs/04 §B.

Every constant below is named and commented so no assumption is hidden, per
CLAUDE.md's "no hidden constants" rule. `disruption_factor` alone drives the
whole cascade (via `crude_price_rise_pct`) so a single frontend slider
re-computes every step live.
"""
from app.models import Scenario

# --- Sourced anchors (docs/04 §B step3) ---
SPR_DEDICATED_DAYS_AT_FULL_FILL = 9.5
OMC_COMMERCIAL_DAYS = 64.5

# --- ASSUMPTION anchors (docs/04 §B step5, dossier 2019 Abqaiq anchor) ---
GDP_DRAG_BPS_PER_10PCT = 15.0

# ASSUMPTION -> derives Step 4's crude_price_rise_pct directly from
# disruption_factor so that one slider cascades through all 5 steps, instead
# of requiring a second independent "price rise" slider. Calibrated 1:1 as
# the simplest defensible default; revisit with a historical regression.
# docs/04 §B step4.
PRICE_SENSITIVITY = 1.0

# ASSUMPTION -> used only if the caller doesn't supply a live price (e.g. no
# PriceService wired). Mirrors prices.BRENT_FALLBACK_USD_BBL. docs/04 §B.
BRENT_BASELINE_USD_BBL = 75.0


def crude_price_rise_pct(disruption_factor: float, price_sensitivity: float = PRICE_SENSITIVITY) -> float:
    """Percentage crude price rise implied by a given disruption level, e.g. 30.0 for 30%."""
    return disruption_factor * price_sensitivity * 100.0


def compute_scenario(
    corridor: str,
    disruption_factor: float = 0.30,
    substitution_rate: float = 0.20,
    hormuz_share: float = 0.45,
    india_imports_mbd: float = 4.7,
    spr_fill_pct: float = 0.64,
    cpi_sensitivity: float = 0.35,
    cad_sensitivity: float = 0.35,
    price_sensitivity: float = PRICE_SENSITIVITY,
    brent_baseline_usd_bbl: float = BRENT_BASELINE_USD_BBL,
) -> Scenario:
    # Step 1 — supply gap
    india_hormuz_volume = india_imports_mbd * hormuz_share
    supply_gap_mbd = india_hormuz_volume * disruption_factor * (1 - substitution_rate)

    # Step 2 — refinery run-rate impact.
    # ASSUMPTION -> denominator uses india_imports_mbd (imports ~90% of
    # throughput per docs/01) rather than a separately-derived MMT/month
    # throughput figure, to avoid inventing an unsourced unit conversion.
    utilization_drop_pct = supply_gap_mbd / india_imports_mbd if india_imports_mbd else 0.0

    # Step 3 — SPR / buffer drawdown
    buffer_days = SPR_DEDICATED_DAYS_AT_FULL_FILL * spr_fill_pct + OMC_COMMERCIAL_DAYS
    buffer_volume_mb = buffer_days * india_imports_mbd
    days_cover_remaining = buffer_volume_mb / supply_gap_mbd if supply_gap_mbd > 0 else buffer_days

    # Step 4 — fuel price / CPI
    price_rise_pct = crude_price_rise_pct(disruption_factor, price_sensitivity)
    cpi_delta_pp = (price_rise_pct / 10) * cpi_sensitivity

    # Step 5 — GDP & CAD
    gdp_drag_bps = (price_rise_pct / 10) * GDP_DRAG_BPS_PER_10PCT
    crude_usd_increase = brent_baseline_usd_bbl * (price_rise_pct / 100)
    cad_widening_pct_gdp = (crude_usd_increase / 10) * cad_sensitivity

    return Scenario(
        corridor=corridor,
        disruption_factor=disruption_factor,
        substitution_rate=substitution_rate,
        hormuz_share=hormuz_share,
        india_imports_mbd=india_imports_mbd,
        supply_gap_mbd=supply_gap_mbd,
        utilization_drop_pct=utilization_drop_pct,
        spr_fill_pct=spr_fill_pct,
        days_cover_remaining=days_cover_remaining,
        cpi_sensitivity=cpi_sensitivity,
        cpi_delta_pp=cpi_delta_pp,
        gdp_drag_bps=gdp_drag_bps,
        cad_sensitivity=cad_sensitivity,
        cad_widening_pct_gdp=cad_widening_pct_gdp,
        crude_price_rise_pct=price_rise_pct,
        price_sensitivity=price_sensitivity,
        brent_baseline_usd_bbl=brent_baseline_usd_bbl,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_scenario.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/engine/scenario.py backend/tests/test_scenario.py
git commit -m "feat: add 5-step scenario cascade engine, no hidden constants"
```

---

### Task 3: Reroute MCDM Engine + `crude_grades.json`

**Files:**
- Create: `backend/data/crude_grades.json`
- Modify: `backend/app/config.py` (add `CrudeGrade` model + `Settings.crude_grades` property)
- Create: `backend/app/engine/reroute.py`
- Test: `backend/tests/test_reroute.py`

**Interfaces:**
- Consumes: `crude_price_rise_pct`, `PRICE_SENSITIVITY` from `app.engine.scenario` (Task 2).
- Produces: `rank_reroutes(disruption_factor: float, brent_price_usd_bbl: float, grades: list[CrudeGrade], price_sensitivity: float = PRICE_SENSITIVITY) -> list[RerouteOption]` (sorted descending by score). `Settings.crude_grades -> list[CrudeGrade]`. Task 4 imports both.

- [ ] **Step 1: Write `crude_grades.json`**

```json
{
  "grade_match_rule": "ASSUMPTION -> docs/04 SS C. Compatibility of each grade with India's refining mix, keyed on published API gravity + sulfur%: 1.0 (broadly compatible -- API>=28 and sulfur<=1.5%, most PSU + complex refiners can run it) | 0.5 (needs blending before simple/PSU refiners can run it; complex refiners take it natively -- 20<=API<28 or 1.5%<sulfur<=2.5%) | 0.0 (incompatible with the majority PSU/simple refining capacity, only deep-conversion coking refiners like RIL Jamnagar can process it -- API<20 or sulfur>2.5%). Voyage days and API/sulfur figures are docs/04 SS C table midpoints. price_differential_usd_bbl and base_congestion_penalty are illustrative ASSUMPTION values (not a live feed) -- STUB -> replace with live differentials/Portcast when available (docs/02 SS 8).",
  "grades": [
    {
      "grade": "Urals",
      "origin": "Russia",
      "api_gravity": 31.0,
      "sulfur_pct": 1.3,
      "class": "medium_sour",
      "voyage_days": 25,
      "price_differential_usd_bbl": -15.0,
      "base_congestion_penalty": 0.10,
      "grade_match": 1.0,
      "best_fit_refineries": ["RIL Jamnagar", "Nayara Vadinar"]
    },
    {
      "grade": "WTI",
      "origin": "United States",
      "api_gravity": 39.0,
      "sulfur_pct": 0.25,
      "class": "light_sweet",
      "voyage_days": 42,
      "price_differential_usd_bbl": 2.0,
      "base_congestion_penalty": 0.05,
      "grade_match": 1.0,
      "best_fit_refineries": ["IOCL", "BPCL", "HPCL"]
    },
    {
      "grade": "Mars",
      "origin": "United States",
      "api_gravity": 30.0,
      "sulfur_pct": 1.9,
      "class": "medium_sour",
      "voyage_days": 42,
      "price_differential_usd_bbl": -1.0,
      "base_congestion_penalty": 0.08,
      "grade_match": 0.5,
      "best_fit_refineries": ["RIL Jamnagar", "IOCL"]
    },
    {
      "grade": "Bonny Light",
      "origin": "West Africa",
      "api_gravity": 35.0,
      "sulfur_pct": 0.15,
      "class": "light_sweet",
      "voyage_days": 27,
      "price_differential_usd_bbl": 1.5,
      "base_congestion_penalty": 0.06,
      "grade_match": 1.0,
      "best_fit_refineries": ["PSU refiners"]
    },
    {
      "grade": "Merey",
      "origin": "Venezuela",
      "api_gravity": 16.0,
      "sulfur_pct": 2.7,
      "class": "heavy_sour",
      "voyage_days": 47,
      "price_differential_usd_bbl": -22.0,
      "base_congestion_penalty": 0.15,
      "grade_match": 0.0,
      "best_fit_refineries": ["RIL Jamnagar (coking only)"]
    },
    {
      "grade": "Liza",
      "origin": "Guyana",
      "api_gravity": 32.0,
      "sulfur_pct": 0.58,
      "class": "medium_sweet",
      "voyage_days": 47,
      "price_differential_usd_bbl": 1.0,
      "base_congestion_penalty": 0.07,
      "grade_match": 1.0,
      "best_fit_refineries": ["IOCL", "BPCL"]
    }
  ]
}
```

- [ ] **Step 2: Add `CrudeGrade` model + `Settings.crude_grades` property**

In `backend/app/config.py`, add after the `Corridor` class:

```python
class CrudeGrade(BaseModel):
    grade: str
    origin: str
    api_gravity: float
    sulfur_pct: float
    class_: str = Field(alias="class")
    voyage_days: float
    price_differential_usd_bbl: float
    base_congestion_penalty: float
    grade_match: float
    best_fit_refineries: list[str]
```

Add `Field` to the pydantic import line (`from pydantic import BaseModel, Field`).

Add this property inside `Settings`, after `corridors`:

```python
    @property
    def crude_grades(self) -> list[CrudeGrade]:
        raw = json.loads((DATA_DIR / "crude_grades.json").read_text())
        return [CrudeGrade(**g) for g in raw["grades"]]
```

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/test_reroute.py
import pytest

from app.config import CrudeGrade
from app.engine.reroute import rank_reroutes


def make_grade(**overrides) -> CrudeGrade:
    payload = {
        "grade": "Test", "origin": "Testland", "api_gravity": 30.0, "sulfur_pct": 1.0,
        "class": "medium_sour", "voyage_days": 30, "price_differential_usd_bbl": 0.0,
        "base_congestion_penalty": 0.05, "grade_match": 1.0, "best_fit_refineries": ["Test Refinery"],
    }
    payload.update(overrides)
    return CrudeGrade(**payload)


URALS = make_grade(grade="Urals", origin="Russia", api_gravity=31.0, sulfur_pct=1.3, voyage_days=25,
                    price_differential_usd_bbl=-15.0, base_congestion_penalty=0.10, grade_match=1.0,
                    best_fit_refineries=["RIL Jamnagar", "Nayara Vadinar"])
MEREY = make_grade(grade="Merey", origin="Venezuela", api_gravity=16.0, sulfur_pct=2.7, voyage_days=47,
                    price_differential_usd_bbl=-22.0, base_congestion_penalty=0.15, grade_match=0.0,
                    best_fit_refineries=["RIL Jamnagar (coking only)"])
BONNY = make_grade(grade="Bonny Light", origin="West Africa", api_gravity=35.0, sulfur_pct=0.15, voyage_days=27,
                    price_differential_usd_bbl=1.5, base_congestion_penalty=0.06, grade_match=1.0,
                    best_fit_refineries=["PSU refiners"])


def test_grade_match_is_read_directly_from_input_not_derived():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS, MEREY, BONNY])
    by_grade = {o.source_grade: o for o in options}
    assert by_grade["Urals"].grade_match == 1.0
    assert by_grade["Merey"].grade_match == 0.0
    assert by_grade["Bonny Light"].grade_match == 1.0


def test_incompatible_grade_scores_lower_than_compatible_grade():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS, MEREY])
    by_grade = {o.source_grade: o for o in options}
    assert by_grade["Urals"].score > by_grade["Merey"].score


def test_results_sorted_descending_by_score():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS, MEREY, BONNY])
    scores = [o.score for o in options]
    assert scores == sorted(scores, reverse=True)


def test_higher_disruption_increases_landed_cost_and_congestion_penalty():
    low = rank_reroutes(disruption_factor=0.1, brent_price_usd_bbl=75.0, grades=[URALS])[0]
    high = rank_reroutes(disruption_factor=0.9, brent_price_usd_bbl=75.0, grades=[URALS])[0]
    assert high.landed_cost_usd_bbl > low.landed_cost_usd_bbl
    assert high.congestion_penalty > low.congestion_penalty


def test_higher_disruption_changes_the_score_gap_between_grades():
    # Merey's much longer voyage (47d vs 25d) means its congestion penalty
    # grows faster with disruption_factor than Urals' -- proving the ranking
    # engine is live-reactive to the slider, not a static precomputed table.
    low = rank_reroutes(disruption_factor=0.0, brent_price_usd_bbl=75.0, grades=[URALS, MEREY])
    high = rank_reroutes(disruption_factor=1.0, brent_price_usd_bbl=75.0, grades=[URALS, MEREY])
    low_gap = low[0].score - low[1].score
    high_gap = high[0].score - high[1].score
    assert high_gap != pytest.approx(low_gap)


def test_single_grade_normalizes_without_division_by_zero():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS])
    assert len(options) == 1
    assert options[0].score > 0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reroute.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.reroute'`

- [ ] **Step 5: Write the implementation**

```python
# backend/app/engine/reroute.py
"""Multi-criteria (MCDM) reroute ranking, constrained by the grade_match
matrix -- a hard input, not a tiebreaker. Formula and weights: docs/04 §C.
"""
from app.config import CrudeGrade
from app.engine.scenario import PRICE_SENSITIVITY, crude_price_rise_pct
from app.models import RerouteOption

# ASSUMPTION -> docs/04 §C
W_COST = 0.35
W_TIME = 0.25
W_GRADE = 0.30
W_CONG = 0.10

# STUB -> FRED BCTI/BDI freight proxy, docs/02 §7 (cut-list #2). ASSUMPTION
# ballpark tanker freight cost per voyage-day, applied uniformly across grades.
FREIGHT_PROXY_USD_BBL_PER_DAY = 0.10

# ASSUMPTION -> port congestion stress rises with corridor disruption as
# buyers scramble for the same alternative barrels; scaled by a grade's
# relative voyage exposure. STUB -> Portcast, docs/02 §8.
CONGESTION_DISRUPTION_SENSITIVITY = 0.15
_CONGESTION_VOYAGE_REFERENCE_DAYS = 30.0


def _minmax_normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def rank_reroutes(
    disruption_factor: float,
    brent_price_usd_bbl: float,
    grades: list[CrudeGrade],
    price_sensitivity: float = PRICE_SENSITIVITY,
) -> list[RerouteOption]:
    price_rise_pct = crude_price_rise_pct(disruption_factor, price_sensitivity)

    landed_costs: list[float] = []
    congestion_penalties: list[float] = []
    for grade in grades:
        landed_cost = (
            brent_price_usd_bbl * (1 + price_rise_pct / 100)
            + grade.price_differential_usd_bbl
            + FREIGHT_PROXY_USD_BBL_PER_DAY * grade.voyage_days
        )
        landed_costs.append(landed_cost)

        congestion = grade.base_congestion_penalty + disruption_factor * CONGESTION_DISRUPTION_SENSITIVITY * (
            grade.voyage_days / _CONGESTION_VOYAGE_REFERENCE_DAYS
        )
        congestion_penalties.append(congestion)

    norm_cost = _minmax_normalize([1 / c for c in landed_costs])
    norm_time = _minmax_normalize([1 / g.voyage_days for g in grades])

    options = []
    for grade, cost, cong, nc, nt in zip(grades, landed_costs, congestion_penalties, norm_cost, norm_time):
        score = W_COST * nc + W_TIME * nt + W_GRADE * grade.grade_match - W_CONG * cong
        options.append(
            RerouteOption(
                source_grade=grade.grade,
                origin=grade.origin,
                api_gravity=grade.api_gravity,
                sulfur_pct=grade.sulfur_pct,
                landed_cost_usd_bbl=round(cost, 2),
                voyage_days=grade.voyage_days,
                grade_match=grade.grade_match,
                congestion_penalty=round(cong, 4),
                score=round(score, 4),
                best_fit_refineries=grade.best_fit_refineries,
            )
        )

    options.sort(key=lambda o: o.score, reverse=True)
    return options
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reroute.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/data/crude_grades.json backend/app/config.py backend/app/engine/reroute.py backend/tests/test_reroute.py
git commit -m "feat: add reroute MCDM engine constrained by grade_match matrix"
```

---

### Task 4: Wire `/scenario` and `/reroute` routes + `PriceService` lifespan

**Files:**
- Modify: `backend/app/main.py` (wire `app.state.price_service`)
- Modify: `backend/app/api/routes.py` (add two routes)
- Modify: `backend/tests/test_routes.py` (add coverage)

**Interfaces:**
- Consumes: `PriceService` (Task 1), `compute_scenario` (Task 2), `rank_reroutes` + `Settings.crude_grades` (Task 3).
- Produces: `GET /scenario/{corridor}` -> `Scenario`, `GET /reroute/{corridor}` -> `list[RerouteOption]`. Task 6/7 (frontend) call these.

- [ ] **Step 1: Wire `PriceService` into `main.py` lifespan**

In `backend/app/main.py`, add the import:

```python
from app.ingestion.prices import PriceService
```

In `lifespan()`, immediately after the existing `http_client` guarded-assignment block, add:

```python
    if not hasattr(app.state, 'price_service') or app.state.price_service is None:
        app.state.price_service = PriceService(
            eia_api_key=settings.eia_api_key,
            alphavantage_api_key=settings.alphavantage_api_key,
        )
```

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_routes.py` (add `from app.ingestion.prices import PriceService` to the imports at top):

```python
def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "gdeltproject.org" in url:
        return httpx.Response(200, json=GDELT_RESPONSE)
    if "alphavantage.co" in url:
        return httpx.Response(200, json={"data": [{"date": "2026-07-01", "value": "76.20"}]})
    if "api.eia.gov" in url:
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}})
    return httpx.Response(404)


def _app_with_mocks() -> None:
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))
    app.state.price_service = PriceService(eia_api_key="k", alphavantage_api_key="k")


def test_scenario_hormuz_returns_full_cascade():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/scenario/hormuz", params={"disruption_factor": 0.5})

    assert resp.status_code == 200
    body = resp.json()
    assert body["corridor"] == "hormuz"
    assert body["disruption_factor"] == 0.5
    assert body["supply_gap_mbd"] > 0
    assert "crude_price_rise_pct" in body


def test_scenario_disruption_factor_changes_supply_gap():
    _app_with_mocks()
    with TestClient(app) as client:
        low = client.get("/scenario/hormuz", params={"disruption_factor": 0.1}).json()
        high = client.get("/scenario/hormuz", params={"disruption_factor": 0.8}).json()

    assert high["supply_gap_mbd"] > low["supply_gap_mbd"]


def test_scenario_unknown_corridor_is_404():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/scenario/malacca")

    assert resp.status_code == 404


def test_reroute_hormuz_returns_ranked_options_with_grade_match():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/reroute/hormuz", params={"disruption_factor": 0.3})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 6
    scores = [o["score"] for o in body]
    assert scores == sorted(scores, reverse=True)
    merey = next(o for o in body if o["source_grade"] == "Merey")
    assert merey["grade_match"] == 0.0


def test_reroute_disruption_factor_changes_ranking_live():
    _app_with_mocks()
    with TestClient(app) as client:
        low = client.get("/reroute/hormuz", params={"disruption_factor": 0.0}).json()
        high = client.get("/reroute/hormuz", params={"disruption_factor": 1.0}).json()

    low_scores = {o["source_grade"]: o["score"] for o in low}
    high_scores = {o["source_grade"]: o["score"] for o in high}
    assert low_scores != high_scores


def test_reroute_unknown_corridor_is_404():
    _app_with_mocks()
    with TestClient(app) as client:
        resp = client.get("/reroute/malacca")

    assert resp.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_routes.py -v`
Expected: FAIL — `404`/`AttributeError` on `/scenario` and `/reroute` (routes don't exist yet)

- [ ] **Step 4: Implement the routes**

Replace the full contents of `backend/app/api/routes.py`:

```python
# backend/app/api/routes.py
from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.engine.reroute import rank_reroutes
from app.engine.risk import compute_risk
from app.engine.scenario import compute_scenario
from app.ingestion.gdelt import fetch_kinetic_volume
from app.models import RerouteOption, RiskScore, Scenario

router = APIRouter()

SUPPORTED_CORRIDORS = {"hormuz"}  # bab_el_mandeb, malacca: code path exists via corridors.json, not wired yet


@router.get("/risk/{corridor}", response_model=RiskScore)
async def get_risk(corridor: str, request: Request) -> RiskScore:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    store = request.app.state.vessel_store
    density_tracker = request.app.state.density_tracker
    http_client = request.app.state.http_client

    vessel_count = len(store.snapshot())
    density_tracker.sample(vessel_count)

    x_kinetic = await fetch_kinetic_volume(http_client)
    x_density = density_tracker.x_density()

    return compute_risk(corridor=corridor, x_kinetic=x_kinetic, x_density=x_density)


@router.get("/scenario/{corridor}", response_model=Scenario)
async def get_scenario(
    corridor: str,
    request: Request,
    disruption_factor: float = 0.30,
    substitution_rate: float = 0.20,
    hormuz_share: float = 0.45,
    spr_fill_pct: float = 0.64,
    cpi_sensitivity: float = 0.35,
    cad_sensitivity: float = 0.35,
) -> Scenario:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    price_service = request.app.state.price_service
    http_client = request.app.state.http_client
    brent_price = await price_service.get_brent_price(http_client)

    return compute_scenario(
        corridor=corridor,
        disruption_factor=disruption_factor,
        substitution_rate=substitution_rate,
        hormuz_share=hormuz_share,
        spr_fill_pct=spr_fill_pct,
        cpi_sensitivity=cpi_sensitivity,
        cad_sensitivity=cad_sensitivity,
        brent_baseline_usd_bbl=brent_price,
    )


@router.get("/reroute/{corridor}", response_model=list[RerouteOption])
async def get_reroute(
    corridor: str,
    request: Request,
    disruption_factor: float = 0.30,
) -> list[RerouteOption]:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    price_service = request.app.state.price_service
    http_client = request.app.state.http_client
    brent_price = await price_service.get_brent_price(http_client)

    grades = get_settings().crude_grades
    return rank_reroutes(disruption_factor=disruption_factor, brent_price_usd_bbl=brent_price, grades=grades)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS — full suite green, including the pre-existing `test_risk_hormuz_returns_full_breakdown` and `test_risk_unknown_corridor_is_404` which don't touch `price_service`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/api/routes.py backend/tests/test_routes.py
git commit -m "feat: wire /scenario and /reroute routes with live price service"
```

---

### Task 5: Frontend types + debounce hook

**Files:**
- Modify: `frontend/lib/types.ts`
- Create: `frontend/lib/useDebounce.ts`

**Interfaces:**
- Produces: `ScenarioInputs` interface, 3 new `Scenario` fields, `useDebounce<T>(value: T, delayMs: number): T`. Tasks 6–8 depend on these.

- [ ] **Step 1: Update `types.ts`**

In `frontend/lib/types.ts`, extend the `Scenario` interface (add after `cad_widening_pct_gdp`):

```typescript
  crude_price_rise_pct: number;
  price_sensitivity: number;
  brent_baseline_usd_bbl: number;
```

Append this new interface at the end of the file:

```typescript
export interface ScenarioInputs {
  disruption_factor: number;
  substitution_rate: number;
  hormuz_share: number;
  spr_fill_pct: number;
  cpi_sensitivity: number;
  cad_sensitivity: number;
}
```

- [ ] **Step 2: Create `useDebounce.ts`**

```typescript
// frontend/lib/useDebounce.ts
"use client";

import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors (existing components still reference old `Scenario`/`RerouteOption` shapes until Tasks 6–7 land — that's fine, this task only adds types, doesn't yet break consumers since all new fields are additive and `ScenarioInputs`/`useDebounce` are unused-but-valid until wired).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/useDebounce.ts
git commit -m "feat: add ScenarioInputs type and useDebounce hook"
```

---

### Task 6: `ScenarioCard` — live sliders with readout

**Files:**
- Modify: `frontend/components/ScenarioCard.tsx`

**Interfaces:**
- Consumes: `ScenarioInputs`, `useDebounce` (Task 5), `GET /scenario/{corridor}` (Task 4).
- Produces: `ScenarioCard({ apiUrl, inputs, onChange }: { apiUrl: string; inputs: ScenarioInputs; onChange: (next: ScenarioInputs) => void })`. Task 8 (`page.tsx`) renders this with lifted state.

- [ ] **Step 1: Replace `ScenarioCard.tsx`**

```tsx
// frontend/components/ScenarioCard.tsx
"use client";

import { useEffect, useState } from "react";
import type { Scenario, ScenarioInputs } from "@/lib/types";
import { useDebounce } from "@/lib/useDebounce";

const SLIDER_CONFIG: { key: keyof ScenarioInputs; label: string; min: number; max: number; step: number }[] = [
  { key: "disruption_factor", label: "Disruption", min: 0, max: 1, step: 0.01 },
  { key: "substitution_rate", label: "Substitution rate", min: 0, max: 1, step: 0.01 },
  { key: "hormuz_share", label: "Hormuz share of imports", min: 0.3, max: 0.6, step: 0.01 },
  { key: "spr_fill_pct", label: "SPR fill", min: 0, max: 1, step: 0.01 },
  { key: "cpi_sensitivity", label: "CPI sensitivity", min: 0.3, max: 0.4, step: 0.01 },
  { key: "cad_sensitivity", label: "CAD sensitivity", min: 0.2, max: 0.5, step: 0.01 },
];

export default function ScenarioCard({
  apiUrl,
  inputs,
  onChange,
}: {
  apiUrl: string;
  inputs: ScenarioInputs;
  onChange: (next: ScenarioInputs) => void;
}) {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const debouncedInputs = useDebounce(inputs, 250);

  useEffect(() => {
    let cancelled = false;
    async function fetchScenario() {
      const params = new URLSearchParams(
        Object.fromEntries(Object.entries(debouncedInputs).map(([k, v]) => [k, String(v)]))
      );
      try {
        const resp = await fetch(`${apiUrl}/scenario/hormuz?${params}`);
        if (resp.ok && !cancelled) {
          setScenario(await resp.json());
        }
      } catch {
        // network hiccup, next slider move retries
      }
    }
    fetchScenario();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, debouncedInputs]);

  return (
    <div className="panel">
      <h2>Scenario — macro cascade</h2>
      {SLIDER_CONFIG.map(({ key, label, min, max, step }) => (
        <div key={key} style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, opacity: 0.8, display: "flex", justifyContent: "space-between" }}>
            <span>{label}</span>
            <span>{inputs[key].toFixed(2)}</span>
          </label>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={inputs[key]}
            onChange={(e) => onChange({ ...inputs, [key]: Number(e.target.value) })}
            style={{ width: "100%" }}
          />
        </div>
      ))}
      {!scenario ? (
        <div>Loading cascade…</div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, fontSize: 14, lineHeight: 1.8 }}>
          <li>Supply gap: {scenario.supply_gap_mbd.toFixed(2)} mb/d</li>
          <li>Refinery utilization drop: {(scenario.utilization_drop_pct * 100).toFixed(1)}%</li>
          <li>SPR + commercial days cover: {scenario.days_cover_remaining.toFixed(1)} days</li>
          <li>Crude price rise: +{scenario.crude_price_rise_pct.toFixed(1)}%</li>
          <li>CPI impact: +{scenario.cpi_delta_pp.toFixed(2)} pp</li>
          <li>GDP drag: {scenario.gdp_drag_bps.toFixed(1)} bps</li>
          <li>CAD widening: {(scenario.cad_widening_pct_gdp * 100).toFixed(2)}% of GDP</li>
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

(Committed together with Task 8 once `page.tsx` supplies the new props — see Task 8 Step 2. Skip standalone commit here to avoid an intermediate broken build.)

---

### Task 7: `RerouteCard` — live ranking keyed on `disruption_factor`

**Files:**
- Modify: `frontend/components/RerouteCard.tsx`

**Interfaces:**
- Consumes: `useDebounce` (Task 5), `GET /reroute/{corridor}` (Task 4).
- Produces: `RerouteCard({ apiUrl, disruptionFactor }: { apiUrl: string; disruptionFactor: number })`. Task 8 renders this.

- [ ] **Step 1: Replace `RerouteCard.tsx`**

```tsx
// frontend/components/RerouteCard.tsx
"use client";

import { useEffect, useState } from "react";
import type { RerouteOption } from "@/lib/types";
import { useDebounce } from "@/lib/useDebounce";

export default function RerouteCard({ apiUrl, disruptionFactor }: { apiUrl: string; disruptionFactor: number }) {
  const [reroutes, setReroutes] = useState<RerouteOption[]>([]);
  const debouncedDisruption = useDebounce(disruptionFactor, 250);

  useEffect(() => {
    let cancelled = false;
    async function fetchReroutes() {
      try {
        const resp = await fetch(`${apiUrl}/reroute/hormuz?disruption_factor=${debouncedDisruption}`);
        if (resp.ok && !cancelled) {
          setReroutes(await resp.json());
        }
      } catch {
        // network hiccup, next slider move retries
      }
    }
    fetchReroutes();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, debouncedDisruption]);

  return (
    <div className="panel">
      <h2>Ranked reroute options</h2>
      <ol style={{ paddingLeft: 18, fontSize: 14 }}>
        {reroutes.map((r) => (
          <li key={r.source_grade} style={{ marginBottom: 10 }}>
            <strong>
              {r.source_grade} ({r.origin})
            </strong>{" "}
            — score {r.score.toFixed(2)}
            <div style={{ opacity: 0.8 }}>
              ${r.landed_cost_usd_bbl.toFixed(2)}/bbl · {r.voyage_days}d voyage · grade_match {r.grade_match} ·{" "}
              {r.best_fit_refineries.join(", ")}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

(Committed together with Task 8 — see below.)

---

### Task 8: `page.tsx` — lift shared scenario state

**Files:**
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `ScenarioCard` (Task 6), `RerouteCard` (Task 7), `ScenarioInputs` (Task 5).

- [ ] **Step 1: Replace `page.tsx`**

```tsx
// frontend/app/page.tsx
"use client";

import { useState } from "react";
import MapDeck from "@/components/MapDeck";
import RiskPanel from "@/components/RiskPanel";
import ScenarioCard from "@/components/ScenarioCard";
import RerouteCard from "@/components/RerouteCard";
import { useVesselStream } from "@/lib/ws";
import type { ScenarioInputs } from "@/lib/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/vessels";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const DEFAULT_SCENARIO_INPUTS: ScenarioInputs = {
  disruption_factor: 0.3,
  substitution_rate: 0.2,
  hormuz_share: 0.45,
  spr_fill_pct: 0.64,
  cpi_sensitivity: 0.35,
  cad_sensitivity: 0.35,
};

export default function Page() {
  const vessels = useVesselStream(WS_URL);
  const [scenarioInputs, setScenarioInputs] = useState<ScenarioInputs>(DEFAULT_SCENARIO_INPUTS);

  return (
    <main style={{ display: "grid", gridTemplateColumns: "1fr 380px", width: "100vw", height: "100vh" }}>
      <MapDeck vessels={vessels} />
      <aside style={{ overflowY: "auto", padding: 16, background: "#0f131c" }}>
        <RiskPanel apiUrl={API_URL} />
        <ScenarioCard apiUrl={API_URL} inputs={scenarioInputs} onChange={setScenarioInputs} />
        <RerouteCard apiUrl={API_URL} disruptionFactor={scenarioInputs.disruption_factor} />
      </aside>
    </main>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles and commit Tasks 6–8 together**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

```bash
git add frontend/app/page.tsx frontend/components/ScenarioCard.tsx frontend/components/RerouteCard.tsx
git commit -m "feat: wire live scenario sliders and reroute ranking to shared disruption state"
```

---

### Task 9: Exit-test verification — drag the slider, watch both panels update live

**Files:** none (manual/browser verification only)

- [ ] **Step 1: Start the backend**

Run: `cd backend && python -m uvicorn app.main:app --reload --port 8000`
Expected: `[STARTUP]` log line, no `✗` errors, server listening on :8000.

- [ ] **Step 2: Start the frontend**

Run: `cd frontend && npm run dev`
Expected: Next.js dev server on :3000.

- [ ] **Step 3: Open the browser and verify network calls**

Open `http://localhost:3000`, open DevTools → Network tab, filter on `scenario` and `reroute`.
Confirm on page load: one `GET /scenario/hormuz` and one `GET /reroute/hormuz` request, both 200.

- [ ] **Step 4: Drag the "Disruption" slider and confirm live cascade + re-rank**

Drag the Disruption slider from ~0.1 to ~0.9. Confirm:
- A new `GET /scenario/hormuz?disruption_factor=...` fires ~250ms after the drag settles (not on every pixel — debounced).
- The Scenario panel numbers change (`Supply gap`, `Crude price rise`, `CPI impact`, `GDP drag`, `CAD widening` all move).
- A new `GET /reroute/hormuz?disruption_factor=...` fires in the same window.
- The Reroute panel's scores recompute (compare the values at disruption≈0.1 vs disruption≈0.9 — `Merey`'s score gap to the leader should narrow due to its longer voyage/congestion exposure, per `test_higher_disruption_changes_the_score_gap_between_grades`). **Correction (2026-07-12, verified live against a 201-point sweep of the full domain, docs/04 §C):** the ranked *order* does not flip anywhere in `[0.0, 1.0]` for the current 6-grade set — cost dominates the MCDM formula enough that only the score gaps move, not the positions. Don't expect or demo a visible reorder.

- [ ] **Step 5: Confirm `grade_match` is a hard input, not computed**

In the Reroute panel, confirm `Merey (Venezuela)` always shows `grade_match 0.0` regardless of slider position — proving grade compatibility is read from `crude_grades.json`, not derived from cost/time.

- [ ] **Step 6: Run the full backend test suite one more time as a regression gate**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests pass (risk + scenario + reroute + prices + routes + existing Phase 1 suite).

No commit for this task — it's verification only.

---

### Task 10: Update docs per CLAUDE.md (non-negotiable, do this every iteration)

**Files:**
- Modify: `docs/04_model_assumptions_and_constants.md`
- Modify: `docs/03_build_plan_and_deliverables.md`
- Modify: `docs/02_data_sources_and_schemas.md`
- Modify: `Readme.md`

- [ ] **Step 1: Update `docs/04_model_assumptions_and_constants.md`**

Append a new `## E. Scenario cascade — implementation constants (Phase 2)` section after section D, documenting: `PRICE_SENSITIVITY = 1.0` (ASSUMPTION, derives Step 4 from `disruption_factor` alone so one slider drives all 5 steps), `SPR_DEDICATED_DAYS_AT_FULL_FILL = 9.5`, `OMC_COMMERCIAL_DAYS = 64.5`, `GDP_DRAG_BPS_PER_10PCT = 15.0` (now named constants in `backend/app/engine/scenario.py`), and the Step-2 denominator substitution (`india_imports_mbd` instead of an undocumented MMT/month throughput conversion).

Append `## F. Reroute engine — implementation constants (Phase 2)`: `FREIGHT_PROXY_USD_BBL_PER_DAY = 0.10` (STUB → FRED BCTI), `CONGESTION_DISRUPTION_SENSITIVITY = 0.15` (ASSUMPTION, STUB → Portcast), and reference `backend/data/crude_grades.json`'s `grade_match_rule` field as the authoritative grade-compatibility matrix.

- [ ] **Step 2: Update `docs/03_build_plan_and_deliverables.md`**

Flip these rows from ⬜/🟨 to ✅:
- `EIA + Alpha Vantage (cached) price connectors`
- `Risk engine (sigmoid + weighted features + per-feature breakdown)` → ✅ (all 5 features confirmed complete; sanctions/weather/freight remain intentionally `STUB → 0.0` per cut-list, noted in the row)
- `Scenario cascade engine (5 steps, all sliders)`
- `Reroute MCDM (grade_match matrix)`
- `Scenario sliders + live cascade readout`
- `Reroute ranked-list card (executable plan)` → ✅ (now MCDM-driven, not hardcoded)
- `refineries.json, spr.json, corridors.json, crude_grades.json curated + source-verified` → 🟨 (`crude_grades.json` done; `refineries.json`/`spr.json` still ⬜, teammate-owned)

- [ ] **Step 3: Update `docs/02_data_sources_and_schemas.md`**

In section 5 (Alpha Vantage) and section 2 (EIA), add an "Implementation note" paragraph (mirroring the GDELT note style in §3) pointing to `backend/app/ingestion/prices.py`, describing the `PriceService` fallback chain (Alpha Vantage → EIA → static `BRENT_FALLBACK_USD_BBL`) and the mandatory 1-hour TTL.

- [ ] **Step 4: Update `Readme.md`**

In the repo structure block, move `crude_grades.json` and `engine/scenario.py`, `engine/reroute.py`, `ingestion/prices.py` out of their "(Phase 2)" future-tense notes into the present-tense listing. In "Model assumptions & limitations", add a bullet: "Reroute landed cost includes an illustrative price differential + freight-per-day proxy (not a live feed) — labeled `ASSUMPTION`/`STUB` in `crude_grades.json` and `reroute.py`."

- [ ] **Step 5: Commit**

```bash
git add docs/04_model_assumptions_and_constants.md docs/03_build_plan_and_deliverables.md docs/02_data_sources_and_schemas.md Readme.md
git commit -m "docs: sync tracker and constants doc with Phase 2 engines"
```

---

## Self-Review Notes

- **Spec coverage:** ✅ full risk model (already complete, verified, no task needed) · ✅ scenario cascade 5 steps all sliders (Task 2 + 6) · ✅ reroute MCDM constrained by grade_match hard input (Task 3) · ✅ EIA + Alpha Vantage cached price connectors (Task 1) · ✅ unit tests for risk (pre-existing)/scenario/reroute (Tasks 2–3) · ✅ exit test — slider drag re-cascades and re-ranks live (Task 9).
- **No placeholders:** every step above has complete, runnable code — no `TODO`/`TBD` left for the implementer to fill in. `STUB →` / `ASSUMPTION` labels are intentional per CLAUDE.md, not plan placeholders.
- **Type consistency checked:** `CrudeGrade` (config.py) fields match `crude_grades.json` keys exactly; `RerouteOption` fields populated by `reroute.py` match `models.py` exactly (no changes needed there); `Scenario`'s 3 new fields appear in `models.py` (Task 2), `scenario.py`'s return (Task 2), `types.ts` (Task 5), and `ScenarioCard.tsx`'s render (Task 6) consistently.
