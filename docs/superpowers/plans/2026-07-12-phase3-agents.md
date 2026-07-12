# Phase 3 — Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a four-node LangGraph agent pipeline (Market Intelligence → Logistics & Maritime → Macroeconomic Strategist → Executive Orchestrator) that calls the existing deterministic engines (`risk.py`, `scenario.py`, `reroute.py`) and live connectors, and has an LLM narrate/classify the results — never recompute them. Ship a sequential fallback with identical node functions, wire real OpenSanctions screening (the key now works), cut Chroma RAG (corpus is empty), and expose it all via `GET /recommendation/{corridor}`.

**Architecture:** Four pure-ish async node functions (`market.py`, `logistics.py`, `macro.py`, `orchestrator.py`) share one `AgentState` TypedDict. `graph.py` wires them into a LangGraph `StateGraph`; `sequential.py` calls the *same* functions directly in a plain `await` chain. `runner.py` selects between them via `AGENT_MODE` (default `graph`). A new `AgentDeps` dataclass bundles every live service/connector so both paths — and tests — construct dependencies identically to how `main.py`/`test_routes.py` already do for the existing routes. Sanctions screening moves into a new shared `ingestion/logistics_reading.py` so `/risk/{corridor}` and the Logistics node use one coverage-exclusion rule, not two copies of it.

**Tech Stack:** LangGraph (`langgraph`) for the graph path; NVIDIA NIM's OpenAI-compatible endpoint (`openai` SDK pointed at `https://integrate.api.nvidia.com/v1`, model `nvidia/llama-3.1-nemotron-70b-instruct`) for narration/classification only.

## Global Constraints

- Never let an LLM compute, estimate, or replace a number that `risk.py`/`scenario.py`/`reroute.py` produces. LLMs only classify (label strings, booleans) and narrate (free text). Every numeric field in `AgentState` is a direct engine/connector passthrough.
- `ANTHROPIC_API_KEY`/`LLM_MODEL` in `.env` are unused hints — this phase wires `NVIDIA_API_KEY` instead (user decision, see below). `NVIDIA_API_KEY` does not exist in `backend/.env` yet — narration must degrade to an honest `STUB — ...` string when it's empty, exactly like the OpenSanctions stub pattern, never fabricated text.
- `AGENT_MODE` env var: `graph` (default) | `sequential`. Both must call the identical four node functions.
- OpenSanctions: real per-vessel screening in `logistics.py`, and the resulting `x_sanctions`/`sanctions_state` also feed `/risk/{corridor}` in `routes.py` (user decision — risk score and agent narration must not disagree on sanctions state).
- Sanctions inherits the AIS coverage-void state: if a corridor has no observed fleet (`density_state` is `WARMING_UP` or `NO_TERRESTRIAL_COVERAGE`), sanctions gets the same state and `x_sanctions=0.0` — never a silent `LIVE 0.0` when there was nothing to screen.
- Chroma RAG is cut this phase (corpus confirmed empty, cut-list #5). Policy facts stay inline in agent system prompts. `docs/04` and `README.md` must say so explicitly.
- Every new connector/cache follows the existing TTL + `asyncio.Lock` double-checked-locking pattern already established in `prices.py`/`weather.py`/`freight.py` (the caching-race class of bug this project already fixed twice).
- `requirements.txt` additions: `langgraph`, `openai` (loose lower-bound pins, confirmed installable at execution time, not guessed exact patch versions).

---

### Task 1: NVIDIA LLM client wrapper

**Files:**
- Create: `backend/app/agents/__init__.py` (empty)
- Create: `backend/app/agents/llm_client.py`
- Modify: `backend/app/config.py` (add `nvidia_api_key`, `llm_model` fields)
- Modify: `backend/.env.example` (add `NVIDIA_API_KEY=`, `LLM_MODEL=nvidia/llama-3.1-nemotron-70b-instruct`, `AGENT_MODE=graph`)
- Modify: `backend/requirements.txt` (add `openai`, `langgraph`)
- Test: `backend/tests/test_llm_client.py`

**Interfaces:**
- Produces: `class LLMClient: def __init__(self, api_key: str, model: str)`, `async def narrate(self, system_prompt: str, user_prompt: str) -> str`, `@property has_key -> bool`. `STUB_NARRATION` constant string prefix `"STUB — LLM narration unavailable"`.

- [ ] **Step 1: Add dependencies and settings**

`backend/requirements.txt` — append:
```
openai>=1.51.0
langgraph>=0.2.28
```

`backend/app/config.py` — add two fields to `Settings`:
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aisstream_api_key: str = ""
    eia_api_key: str = ""
    alphavantage_api_key: str = ""
    opensanctions_api_key: str = ""
    fred_api_key: str = ""
    nvidia_api_key: str = ""
    llm_model: str = "nvidia/llama-3.1-nemotron-70b-instruct"
```

`backend/.env.example` — append after `FRED_API_KEY=`:
```
NVIDIA_API_KEY=            # free tier available, https://build.nvidia.com
LLM_MODEL=nvidia/llama-3.1-nemotron-70b-instruct
AGENT_MODE=graph           # graph (default, LangGraph) | sequential (fallback)
```

- [ ] **Step 2: Install and confirm the new deps resolve**

Run: `cd backend && pip install -r requirements.txt`
Expected: `openai` and `langgraph` install with no dependency conflicts. If a pin fails to resolve, adjust the lower bound in `requirements.txt` to whatever version actually installs and note it here.

- [ ] **Step 3: Write `llm_client.py`**

```python
# backend/app/agents/llm_client.py
"""Thin wrapper around NVIDIA's OpenAI-compatible NIM endpoint
(build.nvidia.com). Agents call this for narration/classification text
only -- it never computes or returns a number consumed as engine output.
If NVIDIA_API_KEY is unset, narrate() returns an honest STUB string instead
of fabricating text, mirroring the OpenSanctions-stub pattern (docs/04).
"""
import logging

from openai import AsyncOpenAI, APIError

logger = logging.getLogger(__name__)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
STUB_NARRATION = "STUB — LLM narration unavailable, NVIDIA_API_KEY not configured."


class LLMClient:
    """One instance per app lifetime. api_key="" makes every call an honest STUB."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = (
            AsyncOpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key) if api_key else None
        )

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    async def narrate(self, system_prompt: str, user_prompt: str) -> str:
        if self._client is None:
            return STUB_NARRATION
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            content = response.choices[0].message.content
            return content if content else STUB_NARRATION
        except APIError as exc:
            logger.warning("[LLM] NVIDIA NIM call failed: %s", exc)
            return f"STUB — LLM narration unavailable, NVIDIA API error ({type(exc).__name__})."
        except Exception as exc:
            logger.warning("[LLM] Unexpected error: %s", type(exc).__name__)
            return f"STUB — LLM narration unavailable, unexpected error ({type(exc).__name__})."
```

- [ ] **Step 4: Write the failing tests, then confirm them passing**

```python
# backend/tests/test_llm_client.py
from unittest.mock import AsyncMock

import pytest

from app.agents.llm_client import LLMClient, STUB_NARRATION


@pytest.mark.asyncio
async def test_narrate_returns_stub_without_key():
    client = LLMClient(api_key="", model="test-model")
    result = await client.narrate("system", "user")
    assert result == STUB_NARRATION
    assert client.has_key is False


@pytest.mark.asyncio
async def test_narrate_returns_model_content_on_success(monkeypatch):
    client = LLMClient(api_key="test-key", model="test-model")

    class FakeMessage:
        content = "The corridor risk is elevated."

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    monkeypatch.setattr(
        client._client.chat.completions, "create", AsyncMock(return_value=FakeResponse())
    )
    result = await client.narrate("system", "user")
    assert result == "The corridor risk is elevated."


@pytest.mark.asyncio
async def test_narrate_returns_stub_on_api_error(monkeypatch):
    client = LLMClient(api_key="test-key", model="test-model")
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    result = await client.narrate("system", "user")
    assert result.startswith("STUB — LLM narration unavailable")
```

Run: `cd backend && python -m pytest tests/test_llm_client.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/__init__.py backend/app/agents/llm_client.py backend/app/config.py backend/.env.example backend/requirements.txt backend/tests/test_llm_client.py
git commit -m "feat: add NVIDIA NIM LLM client with honest STUB degradation"
```

---

### Task 2: Shared logistics reading (sanctions + coverage-aware wiring)

**Files:**
- Create: `backend/app/ingestion/sanctions.py`
- Create: `backend/app/ingestion/logistics_reading.py`
- Test: `backend/tests/test_sanctions.py`
- Test: `backend/tests/test_logistics_reading.py`

**Interfaces:**
- Produces: `class SanctionsService: def __init__(self, api_key: str)`, `async def get_x_sanctions(self, client, vessels: list[Vessel]) -> float`, `@property has_key -> bool`.
- Produces: `@dataclass class LogisticsReading: x_density: float; density_state: str; x_sanctions: float; sanctions_state: str; x_weather: float; vessels_in_corridor: list[Vessel]`
- Produces: `async def compute_logistics_reading(corridor, http_client, settings, vessel_store, density_tracker, coverage_monitor, weather_service, sanctions_service) -> LogisticsReading`
- Consumes: `app.ingestion.aisstream.VesselStore`, `app.ingestion.coverage.CoverageMonitor`, `app.ingestion.density.DensityTracker`, `app.ingestion.weather.WeatherService`, `app.models.Vessel`, `app.config.Settings`.

- [ ] **Step 1: Write `sanctions.py`**

```python
# backend/app/ingestion/sanctions.py
"""OpenSanctions vessel screening connector, docs/02 §4. Screens every MMSI
observed in a corridor's AIS snapshot in one batched match-by-example
request: X_sanctions = flagged_vessels / observed_fleet.

Verified live 2026-07-12: /match/default accepts `properties.mmsi` directly
on the Vessel schema (not just imo), so AIS-observed MMSIs can be screened
without needing an IMO lookup.
"""
import asyncio
import logging
import time

import httpx

from app.models import Vessel

logger = logging.getLogger(__name__)

OPENSANCTIONS_URL = "https://api.opensanctions.org/match/default"

# ASSUMPTION -> mirrors weather.py's single-value TTL cache pattern (not a
# per-vessel cache -- corridor vessel sets are small and change every AIS
# frame, so caching the corridor-level ratio is simpler and sufficient).
# OpenSanctions publishes no documented rate cap for the free/non-commercial
# tier (docs/02 §4); this TTL exists to be a good API citizen against the
# frontend's 10s /risk/{corridor} poll, not because of a stated hard limit.
SANCTIONS_CACHE_TTL_SECONDS = 1800.0


class SanctionsCache:
    def __init__(self, api_key: str, ttl: float = SANCTIONS_CACHE_TTL_SECONDS):
        self.api_key = api_key
        self.ttl = ttl
        self._value: float = 0.0
        self._last_fetch: float = 0.0
        self._last_mmsi_set: frozenset[int] = frozenset()
        self._lock = asyncio.Lock()

    async def get(self, client: httpx.AsyncClient, vessels: list[Vessel]) -> float:
        if not self.api_key or not vessels:
            return 0.0

        mmsi_set = frozenset(v.mmsi for v in vessels)
        now = time.monotonic()
        if mmsi_set == self._last_mmsi_set and now - self._last_fetch < self.ttl:
            return self._value

        async with self._lock:
            # Re-check inside the lock: another coroutine may have already
            # refreshed the cache while this one was waiting.
            now = time.monotonic()
            if mmsi_set == self._last_mmsi_set and now - self._last_fetch < self.ttl:
                return self._value

            try:
                queries = {
                    f"q{i}": {"schema": "Vessel", "properties": {"mmsi": [str(v.mmsi)]}}
                    for i, v in enumerate(vessels)
                }
                response = await client.post(
                    OPENSANCTIONS_URL,
                    headers={"Authorization": f"ApiKey {self.api_key}"},
                    json={"queries": queries},
                )
                response.raise_for_status()
                responses = response.json().get("responses", {})
                flagged = 0
                for reply in responses.values():
                    results = reply.get("results", [])
                    if any("sanction" in r.get("properties", {}).get("topics", []) for r in results):
                        flagged += 1

                self._value = flagged / len(vessels)
                self._last_fetch = now
                self._last_mmsi_set = mmsi_set
                logger.info(
                    "[OpenSanctions] %d/%d observed vessels flagged -> X_sanctions=%.3f",
                    flagged, len(vessels), self._value,
                )
                return self._value
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[OpenSanctions] HTTP %d — serving cached %.3f", exc.response.status_code, self._value
                )
                return self._value
            except Exception as exc:
                logger.warning(
                    "[OpenSanctions] Fetch failed: %s — serving cached %.3f", type(exc).__name__, self._value
                )
                return self._value


class SanctionsService:
    """Thin wrapper mirroring FreightService/WeatherService's shape."""

    def __init__(self, api_key: str, ttl: float = SANCTIONS_CACHE_TTL_SECONDS):
        self._cache = SanctionsCache(api_key=api_key, ttl=ttl)

    async def get_x_sanctions(self, client: httpx.AsyncClient, vessels: list[Vessel]) -> float:
        return await self._cache.get(client, vessels)

    @property
    def has_key(self) -> bool:
        return bool(self._cache.api_key)
```

- [ ] **Step 2: Write `test_sanctions.py`, run, confirm passing**

```python
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
```

Run: `cd backend && python -m pytest tests/test_sanctions.py -v`
Expected: 7 passed.

- [ ] **Step 3: Write `logistics_reading.py`**

```python
# backend/app/ingestion/logistics_reading.py
"""Shared corridor logistics-feature resolution -- AIS density/coverage
state, Open-Meteo sea state, OpenSanctions screening. Used by both the
/risk/{corridor} route (app/api/routes.py) and the agents' Logistics &
Maritime node (app/agents/logistics.py) so the coverage-exclusion rule
lives in exactly one place.

Sanctions inherits the AIS coverage state when there's no observed fleet to
screen (docs/04 §A) -- never a silent LIVE 0.0.
"""
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService
from app.models import Vessel

EXCLUDED_COVERAGE_STATES = {"NO_TERRESTRIAL_COVERAGE", "WARMING_UP"}


@dataclass
class LogisticsReading:
    x_density: float
    density_state: str
    x_sanctions: float
    sanctions_state: str
    x_weather: float
    vessels_in_corridor: list[Vessel]


async def compute_logistics_reading(
    corridor: str,
    http_client: httpx.AsyncClient,
    settings: Settings,
    vessel_store: VesselStore,
    density_tracker: DensityTracker,
    coverage_monitor: CoverageMonitor,
    weather_service: WeatherService,
    sanctions_service: SanctionsService,
) -> LogisticsReading:
    corridor_bbox = settings.corridors[corridor].bbox

    density_state = "LIVE"
    for box_name, box in settings.ais_boxes.items():
        if box.corridor == corridor:
            box_state = coverage_monitor.state(box_name)
            if box_state != "COVERED":
                density_state = box_state
            break

    vessels_in_corridor = vessel_store.snapshot_in_bbox(corridor_bbox)
    if density_state == "LIVE":
        density_tracker.sample(len(vessels_in_corridor))
    x_density = density_tracker.x_density()

    x_weather = await weather_service.get_x_weather(http_client, corridor=corridor, bbox=corridor_bbox)

    if density_state in EXCLUDED_COVERAGE_STATES:
        sanctions_state = density_state
        x_sanctions = 0.0
    elif not sanctions_service.has_key:
        sanctions_state = "STUB"
        x_sanctions = 0.0
    else:
        x_sanctions = await sanctions_service.get_x_sanctions(http_client, vessels_in_corridor)
        sanctions_state = "LIVE"

    return LogisticsReading(
        x_density=x_density,
        density_state=density_state,
        x_sanctions=x_sanctions,
        sanctions_state=sanctions_state,
        x_weather=x_weather,
        vessels_in_corridor=vessels_in_corridor,
    )
```

- [ ] **Step 4: Write `test_logistics_reading.py`, run, confirm passing**

Cover: (a) covered AIS + no sanctions key → `density_state="LIVE"`, `sanctions_state="STUB"`, `x_sanctions=0.0`; (b) covered AIS + sanctions key + one flagged vessel among the mocked fleet → `sanctions_state="LIVE"`, `x_sanctions` matches the flagged ratio; (c) uncovered AIS (`NO_TERRESTRIAL_COVERAGE`) + sanctions key present → `sanctions_state == density_state == "NO_TERRESTRIAL_COVERAGE"`, `x_sanctions=0.0`, and the sanctions HTTP mock is never called (assert a call counter stays 0). Use the same `httpx.MockTransport` + `CoverageMonitor`/`DensityTracker(min_samples=1)` construction pattern as `test_routes.py`.

Run: `cd backend && python -m pytest tests/test_logistics_reading.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/sanctions.py backend/app/ingestion/logistics_reading.py backend/tests/test_sanctions.py backend/tests/test_logistics_reading.py
git commit -m "feat: wire live OpenSanctions screening with AIS-coverage-void inheritance"
```

---

### Task 3: Wire sanctions into `/risk/{corridor}` and `main.py`

**Files:**
- Modify: `backend/app/api/routes.py` (`get_risk` uses `compute_logistics_reading`)
- Modify: `backend/app/main.py` (instantiate `sanctions_service`, `llm_client` on `app.state`)
- Modify: `backend/tests/test_routes.py` (update 2 existing assertions, add 2 new tests)

**Interfaces:**
- Consumes: `compute_logistics_reading` from Task 2.
- Produces: `request.app.state.sanctions_service: SanctionsService`, `request.app.state.llm_client: LLMClient` (used by Task 7's route).

- [ ] **Step 1: Rewrite `get_risk` in `routes.py`**

Replace the body of `get_risk` (currently `backend/app/api/routes.py:16-68`) with:

```python
@router.get("/risk/{corridor}", response_model=RiskScore)
async def get_risk(corridor: str, request: Request) -> RiskScore:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    settings = get_settings()
    http_client = request.app.state.http_client

    reading = await compute_logistics_reading(
        corridor=corridor,
        http_client=http_client,
        settings=settings,
        vessel_store=request.app.state.vessel_store,
        density_tracker=request.app.state.density_tracker,
        coverage_monitor=request.app.state.coverage_monitor,
        weather_service=request.app.state.weather_service,
        sanctions_service=request.app.state.sanctions_service,
    )

    freight_service = request.app.state.freight_service
    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    x_freight = await freight_service.get_x_freight(http_client)

    return compute_risk(
        corridor=corridor,
        x_kinetic=x_kinetic,
        x_density=reading.x_density,
        x_sanctions=reading.x_sanctions,
        x_weather=reading.x_weather,
        x_freight=x_freight,
        feature_states={
            "density": reading.density_state,
            "sanctions": reading.sanctions_state,
            "weather": "LIVE",
            "freight": "LIVE" if freight_service.has_key else "STUB",
        },
    )
```

Add the import at the top of `routes.py`:
```python
from app.ingestion.logistics_reading import compute_logistics_reading
```
Remove the now-unused inline coverage-loop code that used to live in `get_risk` (the `density_state` for-loop and `density_tracker.sample(...)` calls) — it's replaced by `compute_logistics_reading`.

- [ ] **Step 2: Wire `sanctions_service` and `llm_client` into `main.py`**

In `backend/app/main.py`, add imports:
```python
from app.agents.llm_client import LLMClient
from app.ingestion.sanctions import SanctionsService
```

Add to the guarded-assignment block (after the existing `freight_service` block, `backend/app/main.py:88-89`):
```python
    if not hasattr(app.state, 'sanctions_service') or app.state.sanctions_service is None:
        app.state.sanctions_service = SanctionsService(api_key=settings.opensanctions_api_key)
    if not hasattr(app.state, 'llm_client') or app.state.llm_client is None:
        app.state.llm_client = LLMClient(api_key=settings.nvidia_api_key, model=settings.llm_model)
```

- [ ] **Step 3: Update the two existing tests whose sanctions assumptions changed**

In `backend/tests/test_routes.py`:

`test_risk_hormuz_weather_and_freight_are_live_not_stub` currently asserts `feature_states["sanctions"] == "STUB"` while using a fresh, unmarked `CoverageMonitor` (density is actually `WARMING_UP`, not `LIVE`, in that setup — sanctions must now inherit `WARMING_UP` too, not read as a bare `STUB`). Fix the setup so density is genuinely `LIVE` (mark a frame) and add an explicit no-key `SanctionsService`, isolating the "key missing" case:

```python
def test_risk_hormuz_weather_and_freight_are_live_not_stub():
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    covered_monitor = _fresh_coverage_monitor()
    covered_monitor.mark_subscribed()
    covered_monitor.mark_frame("hormuz")
    app.state.coverage_monitor = covered_monitor
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))
    app.state.freight_service = FreightService(fred_api_key="test-key")
    app.state.sanctions_service = SanctionsService(api_key="")

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    body = resp.json()
    assert body["feature_states"]["weather"] == "LIVE"
    assert body["feature_states"]["freight"] == "LIVE"
    assert body["feature_states"]["sanctions"] == "STUB"  # covered AIS, but no OPENSANCTIONS_API_KEY
    assert body["features"]["weather"] == 1.0
    assert body["contributions"]["weather"] > 0.0
    assert body["features"]["freight"] == pytest.approx(1.0)
```

Add `from app.ingestion.sanctions import SanctionsService` to the imports.

`test_risk_hormuz_freight_degrades_to_stub_when_no_key` needs `app.state.sanctions_service = SanctionsService(api_key="")` added to its setup (it's missing entirely today, which will now `AttributeError` since `get_risk` reads it unconditionally) — add that line alongside the existing `app.state.freight_service = FreightService(fred_api_key="")`.

Also add `app.state.sanctions_service = SanctionsService(api_key="")` to every other existing test in this file that calls `client.get("/risk/hormuz")` or `_app_with_mocks()` (i.e. `test_risk_hormuz_returns_full_breakdown`, `test_risk_hormuz_density_state_reflects_coverage`, `test_risk_unknown_corridor_is_404`, `_app_with_mocks`) — otherwise they'll `AttributeError` on the new `request.app.state.sanctions_service` read. Use `SanctionsService(api_key="")` (STUB, deterministic) in all of them except the two new tests below.

- [ ] **Step 4: Add two new tests proving the sanctions wiring**

```python
def test_risk_hormuz_sanctions_live_screens_observed_fleet():
    from app.ingestion.sanctions import SanctionsService

    store = VesselStore()
    store.upsert(Vessel(mmsi=111, lat=26.3, lon=56.3, sog=5.0, timestamp=datetime.now(timezone.utc)))
    store.upsert(Vessel(mmsi=222, lat=26.3, lon=56.3, sog=5.0, timestamp=datetime.now(timezone.utc)))
    app.state.vessel_store = store
    app.state.density_tracker = DensityTracker(min_samples=1)
    covered_monitor = _fresh_coverage_monitor()
    covered_monitor.mark_subscribed()
    covered_monitor.mark_frame("hormuz")
    app.state.coverage_monitor = covered_monitor

    def handler(request: httpx.Request) -> httpx.Response:
        if "opensanctions.org" in str(request.url):
            import json
            payload = json.loads(request.read())
            responses = {}
            for key, q in payload["queries"].items():
                mmsi = q["properties"]["mmsi"][0]
                topics = ["sanction"] if mmsi == "111" else []
                results = [{"properties": {"topics": topics}}] if topics else []
                responses[key] = {"status": 200, "results": results}
            return httpx.Response(200, json={"responses": responses})
        return _mock_handler(request)

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.freight_service = FreightService(fred_api_key="test-key")
    app.state.sanctions_service = SanctionsService(api_key="test-key")

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    body = resp.json()
    assert body["feature_states"]["sanctions"] == "LIVE"
    assert body["features"]["sanctions"] == pytest.approx(0.5)


def test_risk_hormuz_sanctions_inherits_coverage_void_state():
    from app.ingestion.sanctions import SanctionsService

    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker(min_samples=1)
    app.state.coverage_monitor = _fresh_coverage_monitor()  # never subscribed -> WARMING_UP
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))
    app.state.freight_service = FreightService(fred_api_key="test-key")
    app.state.sanctions_service = SanctionsService(api_key="test-key")  # key present but must not be used

    with TestClient(app) as client:
        resp = client.get("/risk/hormuz")

    body = resp.json()
    assert body["feature_states"]["density"] == "WARMING_UP"
    assert body["feature_states"]["sanctions"] == "WARMING_UP"
    assert body["features"]["sanctions"] == 0.0
```

Add `from app.models import Vessel` and `from datetime import datetime, timezone` to `test_routes.py`'s imports if not already present (check first — `datetime, timezone` is already imported at the top).

Run: `cd backend && python -m pytest tests/test_routes.py -v`
Expected: all tests in the file pass (existing + 2 new).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd backend && python -m pytest --ignore=tests/test_gdelt.py -v`
Expected: all pass, count increases by 12 (7 sanctions + 3 logistics_reading + 2 new routes tests) plus the 3 llm_client tests from Task 1 = original 82 + 15 = 97.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/app/main.py backend/tests/test_routes.py
git commit -m "feat: wire live sanctions state into /risk/{corridor}, keep risk score and narration consistent"
```

---

### Task 4: Agent state contract + dependency bundle

**Files:**
- Create: `backend/app/agents/state.py`
- Create: `backend/app/agents/deps.py`

**Interfaces:**
- Produces: `class AgentState(TypedDict, total=False)` with fields listed below.
- Produces: `@dataclass class AgentDeps` bundling every live service.

- [ ] **Step 1: Write `state.py`**

```python
# backend/app/agents/state.py
"""Shared state contract threaded through every agent node, both the
LangGraph path (graph.py) and the sequential fallback (sequential.py).
Every `x_*`/`risk`/`scenario`/`reroutes` field is engine or connector
output, passed through verbatim; every `*_narration` field is LLM text
only, and classification fields (`market_volatility_label`,
`price_spike_detected`) are LLM-produced labels, never derived numbers.
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    corridor: str
    disruption_factor: float
    substitution_rate: float
    hormuz_share: float

    # Market Intelligence node output
    x_kinetic: float
    brent_price_usd_bbl: float
    market_volatility_label: str  # LLM classification: LOW | MEDIUM | HIGH
    price_spike_detected: bool  # LLM classification
    market_narration: str

    # Logistics & Maritime node output
    x_density: float
    density_state: str  # LIVE | WARMING_UP | NO_TERRESTRIAL_COVERAGE
    x_sanctions: float
    sanctions_state: str  # LIVE | STUB | WARMING_UP | NO_TERRESTRIAL_COVERAGE
    x_weather: float
    logistics_narration: str

    # Macroeconomic Strategist node output
    scenario: dict
    macro_narration: str

    # Executive Orchestrator node output
    risk: dict
    reroutes: list
    recommendation_narration: str
```

- [ ] **Step 2: Write `deps.py`**

```python
# backend/app/agents/deps.py
"""Bundles the live connectors/services every agent node needs -- constructed
once per request from app.state (mirrors the pattern routes.py already uses)
so both the LangGraph path and the sequential fallback, and their tests,
construct dependencies identically.
"""
from dataclasses import dataclass

import httpx

from app.agents.llm_client import LLMClient
from app.config import Settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.freight import FreightService
from app.ingestion.prices import PriceService
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService


@dataclass
class AgentDeps:
    http_client: httpx.AsyncClient
    settings: Settings
    vessel_store: VesselStore
    density_tracker: DensityTracker
    coverage_monitor: CoverageMonitor
    weather_service: WeatherService
    sanctions_service: SanctionsService
    freight_service: FreightService
    price_service: PriceService
    llm: LLMClient
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/state.py backend/app/agents/deps.py
git commit -m "feat: add agent state contract and dependency bundle"
```

(No standalone tests for these two files — they're exercised through Tasks 5-8's node/graph tests. Pure data containers, nothing to unit-test in isolation.)

---

### Task 5: Market Intelligence and Logistics & Maritime nodes

**Files:**
- Create: `backend/app/agents/market.py`
- Create: `backend/app/agents/logistics.py`
- Test: `backend/tests/test_market_node.py`
- Test: `backend/tests/test_logistics_node.py`

**Interfaces:**
- Consumes: `AgentState`, `AgentDeps` fields, `app.ingestion.gdelt.fetch_kinetic_volume`, `app.ingestion.prices.PriceService`, `app.ingestion.logistics_reading.compute_logistics_reading`.
- Produces: `async def run_market_node(state: AgentState, http_client, price_service, llm: LLMClient) -> AgentState`, `async def run_logistics_node(state: AgentState, http_client, settings, vessel_store, density_tracker, coverage_monitor, weather_service, sanctions_service, llm: LLMClient) -> AgentState`.

- [ ] **Step 1: Write `market.py`**

```python
# backend/app/agents/market.py
"""Market Intelligence node: GDELT kinetic-event volume + EIA/Alpha Vantage
price read (app/ingestion/gdelt.py, app/ingestion/prices.py -- this repo's
actual combined EIA+AlphaVantage module; docs/03's original table names them
as separate eia.py/alphavantage.py files, which were built combined instead).
The LLM only classifies/narrates -- x_kinetic and brent_price_usd_bbl are
passed through from the connectors verbatim.
"""
import httpx

from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.ingestion.gdelt import fetch_kinetic_volume
from app.ingestion.prices import PriceService

MARKET_SYSTEM_PROMPT = (
    "You are a market intelligence analyst for a crude oil procurement desk. "
    "You are given a GDELT kinetic-event volume reading (0-1, min-max scaled "
    "news-volume signal for corridor-related conflict/sanction/strike coverage) "
    "and a live Brent price. Classify geopolitical volatility as LOW, MEDIUM, "
    "or HIGH, and state whether these readings suggest a price spike. Never "
    "invent a different number than the one given -- cite the reading you were given.\n\n"
    "Respond with exactly two lines:\n"
    "CLASSIFICATION: <LOW|MEDIUM|HIGH> | <true|false>\n"
    "NARRATION: <2-3 sentence narration>"
)


def _parse_classification(text: str) -> tuple[str, bool]:
    for line in text.splitlines():
        if line.startswith("CLASSIFICATION:"):
            rest = line.removeprefix("CLASSIFICATION:").strip()
            parts = [p.strip() for p in rest.split("|")]
            label = parts[0].upper() if parts and parts[0].upper() in {"LOW", "MEDIUM", "HIGH"} else "MEDIUM"
            spike = len(parts) > 1 and parts[1].lower() == "true"
            return label, spike
    return "MEDIUM", False


async def run_market_node(
    state: AgentState,
    http_client: httpx.AsyncClient,
    price_service: PriceService,
    llm: LLMClient,
) -> AgentState:
    corridor = state["corridor"]
    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    brent_price = await price_service.get_brent_price(http_client)

    narration = await llm.narrate(
        MARKET_SYSTEM_PROMPT,
        f"GDELT kinetic-event volume for {corridor}: {x_kinetic:.3f} (0=quiet, 1=peak).\n"
        f"Live Brent price: ${brent_price:.2f}/bbl.",
    )
    label, spike = _parse_classification(narration) if llm.has_key else ("STUB", False)

    return {
        **state,
        "x_kinetic": x_kinetic,
        "brent_price_usd_bbl": brent_price,
        "market_volatility_label": label,
        "price_spike_detected": spike,
        "market_narration": narration,
    }
```

- [ ] **Step 2: Write `logistics.py`**

```python
# backend/app/agents/logistics.py
"""Logistics & Maritime node: AIS density/coverage state, Open-Meteo sea
state, OpenSanctions vessel screening -- all resolved by the shared
app/ingestion/logistics_reading.py (also used by GET /risk/{corridor}, so
the two never disagree on sanctions/coverage state). The LLM only narrates.
"""
import httpx

from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.config import Settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.logistics_reading import compute_logistics_reading
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService

LOGISTICS_SYSTEM_PROMPT = (
    "You are a maritime logistics analyst for a crude oil procurement desk. "
    "You are given AIS vessel-density state, sea-state (wave height threshold) "
    "flag, and vessel sanctions-screening state and rate for a shipping corridor. "
    "Narrate the physical/logistics risk read in 2-3 sentences, in plain "
    "language a non-technical stakeholder can follow. If a reading's state is "
    "STUB, WARMING_UP, or NO_TERRESTRIAL_COVERAGE, say so explicitly and never "
    "claim a real value for that reading -- e.g. say 'sanctions screening is "
    "unavailable' rather than 'no vessels are sanctioned'. Never invent a "
    "number different from the ones given."
)


async def run_logistics_node(
    state: AgentState,
    http_client: httpx.AsyncClient,
    settings: Settings,
    vessel_store: VesselStore,
    density_tracker: DensityTracker,
    coverage_monitor: CoverageMonitor,
    weather_service: WeatherService,
    sanctions_service: SanctionsService,
    llm: LLMClient,
) -> AgentState:
    corridor = state["corridor"]
    reading = await compute_logistics_reading(
        corridor=corridor,
        http_client=http_client,
        settings=settings,
        vessel_store=vessel_store,
        density_tracker=density_tracker,
        coverage_monitor=coverage_monitor,
        weather_service=weather_service,
        sanctions_service=sanctions_service,
    )

    narration = await llm.narrate(
        LOGISTICS_SYSTEM_PROMPT,
        f"Corridor: {corridor}\n"
        f"AIS density state: {reading.density_state} (X_density={reading.x_density:.3f})\n"
        f"Sea state flag (Open-Meteo): X_weather={reading.x_weather:.0f} (1=rough seas above threshold)\n"
        f"Sanctions screening state: {reading.sanctions_state} (X_sanctions={reading.x_sanctions:.3f}, "
        f"{len(reading.vessels_in_corridor)} vessels observed)",
    )

    return {
        **state,
        "x_density": reading.x_density,
        "density_state": reading.density_state,
        "x_sanctions": reading.x_sanctions,
        "sanctions_state": reading.sanctions_state,
        "x_weather": reading.x_weather,
        "logistics_narration": narration,
    }
```

- [ ] **Step 3: Write both test files, run, confirm passing**

`test_market_node.py`: construct a mocked `httpx.AsyncClient` (GDELT + EIA/AlphaVantage mocked responses, same shape as `test_routes.py`'s `_mock_handler`), a `PriceService(eia_api_key="k", alphavantage_api_key="k")`, and `LLMClient(api_key="", model="x")` (STUB, deterministic). Assert `result["x_kinetic"]` and `result["brent_price_usd_bbl"]` equal what the mocked connectors return exactly, `result["market_narration"]` starts with `"STUB —"`, and `result["market_volatility_label"] == "STUB"` (since `llm.has_key` is `False`). Add a second test with a monkeypatched `LLMClient.narrate` returning a fixed `"CLASSIFICATION: HIGH | true\nNARRATION: test"` string, asserting the parser extracts `label == "HIGH"` and `spike is True`.

`test_logistics_node.py`: same pattern, mocked `VesselStore`/`CoverageMonitor`/`DensityTracker(min_samples=1)`/`WeatherService`/`SanctionsService(api_key="")`, `LLMClient(api_key="", model="x")`. Assert `result["density_state"]`, `result["x_density"]`, `result["x_sanctions"]`, `result["sanctions_state"]`, `result["x_weather"]` exactly match what `compute_logistics_reading` would independently return for the same mocked inputs (call it directly in the test and compare), and `result["logistics_narration"]` is the STUB string.

Run: `cd backend && python -m pytest tests/test_market_node.py tests/test_logistics_node.py -v`
Expected: 4 passed (2 per file).

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/market.py backend/app/agents/logistics.py backend/tests/test_market_node.py backend/tests/test_logistics_node.py
git commit -m "feat: add Market Intelligence and Logistics & Maritime agent nodes"
```

---

### Task 6: Macroeconomic Strategist and Executive Orchestrator nodes

**Files:**
- Create: `backend/app/agents/macro.py`
- Create: `backend/app/agents/orchestrator.py`
- Test: `backend/tests/test_macro_node.py`
- Test: `backend/tests/test_orchestrator_node.py`

**Interfaces:**
- Consumes: `AgentState` (must already carry `x_kinetic`, `x_density`, `density_state`, `x_sanctions`, `sanctions_state`, `x_weather`, `brent_price_usd_bbl` from Task 5's nodes), `app.engine.scenario.compute_scenario`, `app.engine.risk.compute_risk`, `app.engine.reroute.rank_reroutes`.
- Produces: `async def run_macro_node(state: AgentState, llm: LLMClient) -> AgentState`, `async def run_orchestrator_node(state: AgentState, http_client, freight_service, llm: LLMClient) -> AgentState`.

- [ ] **Step 1: Write `macro.py`**

```python
# backend/app/agents/macro.py
"""Macroeconomic Strategist node: feeds disruption_factor/substitution_rate/
hormuz_share and the live Brent price (from the Market node) into the
existing 5-step scenario cascade (engine/scenario.py). compute_scenario()
output is passed through verbatim -- the LLM only narrates.
"""
from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.engine.scenario import BRENT_BASELINE_USD_BBL, compute_scenario

MACRO_SYSTEM_PROMPT = (
    "You are a macroeconomic strategist for a crude oil-importing economy's "
    "procurement desk. You are given the output of a deterministic 5-step "
    "supply-shock cascade (supply gap, refinery utilization drop, SPR buffer "
    "days remaining, CPI, GDP, and CAD impact). Narrate the macroeconomic "
    "shock vector in 3-4 sentences for a policy briefing. Cite the actual "
    "numbers given -- never invent or round them yourself."
)


async def run_macro_node(state: AgentState, llm: LLMClient) -> AgentState:
    scenario = compute_scenario(
        corridor=state["corridor"],
        disruption_factor=state["disruption_factor"],
        substitution_rate=state["substitution_rate"],
        hormuz_share=state["hormuz_share"],
        brent_baseline_usd_bbl=state.get("brent_price_usd_bbl", BRENT_BASELINE_USD_BBL),
    )

    narration = await llm.narrate(
        MACRO_SYSTEM_PROMPT,
        f"Supply gap: {scenario.supply_gap_mbd:.3f} mb/d\n"
        f"Refinery utilization drop: {scenario.utilization_drop_pct:.1%}\n"
        f"SPR+OMC buffer days remaining: {scenario.days_cover_remaining:.1f}\n"
        f"CPI delta: +{scenario.cpi_delta_pp:.2f}pp\n"
        f"GDP drag: {scenario.gdp_drag_bps:.1f}bps\n"
        f"CAD widening: {scenario.cad_widening_pct_gdp:.2f}% of GDP",
    )

    return {**state, "scenario": scenario.model_dump(), "macro_narration": narration}
```

- [ ] **Step 2: Write `orchestrator.py`**

```python
# backend/app/agents/orchestrator.py
"""Executive Orchestrator node: synthesizes Market + Logistics + Macro reads
into the final risk score (engine/risk.py) and ranked reroute plan
(engine/reroute.py), then has the LLM narrate the executive recommendation.
Both compute_risk() and rank_reroutes() output are passed through verbatim.
Freight (FRED) is fetched here, not in an earlier node -- it's not one of
the three agents' documented inputs but is required by compute_risk().
"""
import httpx

from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.config import get_settings
from app.engine.reroute import rank_reroutes
from app.engine.risk import compute_risk
from app.engine.scenario import BRENT_BASELINE_USD_BBL
from app.ingestion.freight import FreightService

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the executive orchestrator synthesizing a crude-procurement "
    "recommendation for a refiner's leadership team. You are given a "
    "corridor's disruption-risk score with per-feature contributions, and a "
    "ranked list of alternative crude sources with landed cost, grade "
    "compatibility, and MCDM score. Write a 3-5 sentence executive "
    "recommendation: state the top-ranked alternative, why it wins (cost, "
    "grade compatibility, or both), and the corridor risk level driving the "
    "urgency. Cite only the numbers given -- never invent a ranking or score."
)


async def run_orchestrator_node(
    state: AgentState,
    http_client: httpx.AsyncClient,
    freight_service: FreightService,
    llm: LLMClient,
) -> AgentState:
    corridor = state["corridor"]
    x_freight = await freight_service.get_x_freight(http_client)
    freight_state = "LIVE" if freight_service.has_key else "STUB"

    risk = compute_risk(
        corridor=corridor,
        x_kinetic=state["x_kinetic"],
        x_density=state["x_density"],
        x_sanctions=state["x_sanctions"],
        x_weather=state["x_weather"],
        x_freight=x_freight,
        feature_states={
            "density": state["density_state"],
            "sanctions": state["sanctions_state"],
            "weather": "LIVE",
            "freight": freight_state,
        },
    )

    grades = get_settings().crude_grades
    reroutes = rank_reroutes(
        disruption_factor=state["disruption_factor"],
        brent_price_usd_bbl=state.get("brent_price_usd_bbl", BRENT_BASELINE_USD_BBL),
        grades=grades,
    )

    top, runner_up = reroutes[0], reroutes[1]
    narration = await llm.narrate(
        ORCHESTRATOR_SYSTEM_PROMPT,
        f"Corridor risk: {risk.probability:.1%} "
        f"(kinetic={risk.contributions['kinetic']:.3f}, density={risk.contributions['density']:.3f}, "
        f"sanctions={risk.contributions['sanctions']:.3f}, weather={risk.contributions['weather']:.3f}, "
        f"freight={risk.contributions['freight']:.3f})\n"
        f"Top-ranked alternative: {top.source_grade} ({top.origin}), score {top.score:.4f}, "
        f"landed cost ${top.landed_cost_usd_bbl:.2f}/bbl, grade_match {top.grade_match}, "
        f"{top.voyage_days}d voyage.\n"
        f"Runner-up: {runner_up.source_grade}, score {runner_up.score:.4f}.",
    )

    return {
        **state,
        "risk": risk.model_dump(),
        "reroutes": [r.model_dump() for r in reroutes],
        "recommendation_narration": narration,
    }
```

- [ ] **Step 3: Write both test files, run, confirm passing**

`test_macro_node.py`: build a state dict with `disruption_factor=0.5, substitution_rate=0.2, hormuz_share=0.45, brent_price_usd_bbl=80.0, corridor="hormuz"`, `llm=LLMClient(api_key="", model="x")`. Call `run_macro_node`, then independently call `compute_scenario(corridor="hormuz", disruption_factor=0.5, substitution_rate=0.2, hormuz_share=0.45, brent_baseline_usd_bbl=80.0)` in the test and assert `result["scenario"] == scenario.model_dump()` exactly (byte-for-byte dict equality). Assert `result["macro_narration"] == STUB_NARRATION`.

`test_orchestrator_node.py`: build a full state dict with all Market/Logistics fields populated with fixed test values (`x_kinetic=0.3, x_density=0.2, density_state="LIVE", x_sanctions=0.1, sanctions_state="LIVE", x_weather=0.0, disruption_factor=0.3, brent_price_usd_bbl=75.0, corridor="hormuz"`), `FreightService(fred_api_key="")` (STUB, deterministic 0.0), `LLMClient(api_key="", model="x")`. Call `run_orchestrator_node`, then independently call `compute_risk(...)` and `rank_reroutes(...)` in the test with the same inputs, and assert `result["risk"] == risk.model_dump()` and `result["reroutes"] == [r.model_dump() for r in reroutes]` exactly.

Run: `cd backend && python -m pytest tests/test_macro_node.py tests/test_orchestrator_node.py -v`
Expected: 2 passed (1 per file, or split further if useful — at minimum one exact-match test each).

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/macro.py backend/app/agents/orchestrator.py backend/tests/test_macro_node.py backend/tests/test_orchestrator_node.py
git commit -m "feat: add Macroeconomic Strategist and Executive Orchestrator agent nodes"
```

---

### Task 7: LangGraph path, sequential fallback, and mode runner

**Files:**
- Create: `backend/app/agents/graph.py`
- Create: `backend/app/agents/sequential.py`
- Create: `backend/app/agents/runner.py`
- Test: `backend/tests/test_agent_parity.py`

**Interfaces:**
- Consumes: `run_market_node`, `run_logistics_node`, `run_macro_node`, `run_orchestrator_node` (Tasks 5-6), `AgentDeps`, `AgentState`.
- Produces: `async def run_graph(deps: AgentDeps, corridor: str, disruption_factor: float, substitution_rate: float, hormuz_share: float) -> AgentState`, `async def run_sequential(...)` (identical signature), `async def run_agents(...)` (identical signature, dispatches by `AGENT_MODE`), `AGENT_MODE: str` module-level constant in `runner.py`.

- [ ] **Step 1: Write `graph.py`**

```python
# backend/app/agents/graph.py
"""LangGraph StateGraph wiring the four Phase 3 agent nodes into one
pipeline: Market Intelligence -> Logistics & Maritime -> Macroeconomic
Strategist -> Executive Orchestrator. AGENT_MODE=graph (default, runner.py)
runs this. sequential.py runs the identical four node functions directly,
with no LangGraph runtime, as the build plan's cut-list #4 fallback.
"""
from langgraph.graph import END, StateGraph

from app.agents.deps import AgentDeps
from app.agents.logistics import run_logistics_node
from app.agents.macro import run_macro_node
from app.agents.market import run_market_node
from app.agents.orchestrator import run_orchestrator_node
from app.agents.state import AgentState


def build_graph(deps: AgentDeps):
    graph = StateGraph(AgentState)

    async def market_step(state: AgentState) -> AgentState:
        return await run_market_node(state, deps.http_client, deps.price_service, deps.llm)

    async def logistics_step(state: AgentState) -> AgentState:
        return await run_logistics_node(
            state, deps.http_client, deps.settings, deps.vessel_store,
            deps.density_tracker, deps.coverage_monitor, deps.weather_service,
            deps.sanctions_service, deps.llm,
        )

    async def macro_step(state: AgentState) -> AgentState:
        return await run_macro_node(state, deps.llm)

    async def orchestrator_step(state: AgentState) -> AgentState:
        return await run_orchestrator_node(state, deps.http_client, deps.freight_service, deps.llm)

    graph.add_node("market", market_step)
    graph.add_node("logistics", logistics_step)
    graph.add_node("macro", macro_step)
    graph.add_node("orchestrator", orchestrator_step)

    graph.set_entry_point("market")
    graph.add_edge("market", "logistics")
    graph.add_edge("logistics", "macro")
    graph.add_edge("macro", "orchestrator")
    graph.add_edge("orchestrator", END)

    return graph.compile()


async def run_graph(
    deps: AgentDeps,
    corridor: str,
    disruption_factor: float,
    substitution_rate: float,
    hormuz_share: float,
) -> AgentState:
    compiled = build_graph(deps)
    initial_state: AgentState = {
        "corridor": corridor,
        "disruption_factor": disruption_factor,
        "substitution_rate": substitution_rate,
        "hormuz_share": hormuz_share,
    }
    return await compiled.ainvoke(initial_state)
```

- [ ] **Step 2: Write `sequential.py`**

```python
# backend/app/agents/sequential.py
"""Sequential fallback for the four agent nodes -- calls the exact same
functions graph.py uses, directly, with no LangGraph runtime. AGENT_MODE=
sequential (runner.py) selects this path. This is an accepted fallback per
the build plan's own cut-list (#4: 'keep agents but run sequential if graph
is flaky'), not an emergency patch.
"""
from app.agents.deps import AgentDeps
from app.agents.logistics import run_logistics_node
from app.agents.macro import run_macro_node
from app.agents.market import run_market_node
from app.agents.orchestrator import run_orchestrator_node
from app.agents.state import AgentState


async def run_sequential(
    deps: AgentDeps,
    corridor: str,
    disruption_factor: float,
    substitution_rate: float,
    hormuz_share: float,
) -> AgentState:
    state: AgentState = {
        "corridor": corridor,
        "disruption_factor": disruption_factor,
        "substitution_rate": substitution_rate,
        "hormuz_share": hormuz_share,
    }
    state = await run_market_node(state, deps.http_client, deps.price_service, deps.llm)
    state = await run_logistics_node(
        state, deps.http_client, deps.settings, deps.vessel_store,
        deps.density_tracker, deps.coverage_monitor, deps.weather_service,
        deps.sanctions_service, deps.llm,
    )
    state = await run_macro_node(state, deps.llm)
    state = await run_orchestrator_node(state, deps.http_client, deps.freight_service, deps.llm)
    return state
```

- [ ] **Step 3: Write `runner.py`**

```python
# backend/app/agents/runner.py
"""Selects the LangGraph path (default) or the sequential fallback based on
the AGENT_MODE env var. AGENT_MODE=graph (default) | AGENT_MODE=sequential.
Read once at import time, matching how app/ingestion/gdelt.py reads
REDIS_URL from the environment directly.
"""
import os

from app.agents.deps import AgentDeps
from app.agents.state import AgentState

AGENT_MODE = os.environ.get("AGENT_MODE", "graph").strip().lower()


async def run_agents(
    deps: AgentDeps,
    corridor: str,
    disruption_factor: float,
    substitution_rate: float,
    hormuz_share: float,
) -> AgentState:
    if AGENT_MODE == "sequential":
        from app.agents.sequential import run_sequential
        return await run_sequential(deps, corridor, disruption_factor, substitution_rate, hormuz_share)
    from app.agents.graph import run_graph
    return await run_graph(deps, corridor, disruption_factor, substitution_rate, hormuz_share)
```

- [ ] **Step 4: Write the graph-vs-sequential parity test**

```python
# backend/tests/test_agent_parity.py
"""Graph vs sequential parity: Step 4 of the Phase 3 prompt requires proof
that both execution paths produce identical engine-derived numeric output
for the same input. Narration text may differ in wording; every other
field must match exactly. Uses STUB LLM (api_key="") and STUB sanctions
(api_key="") so both runs are fully deterministic -- no real network calls.
"""
import httpx
import pytest

from app.agents.deps import AgentDeps
from app.agents.graph import run_graph
from app.agents.llm_client import LLMClient
from app.agents.sequential import run_sequential
from app.config import get_settings
from app.ingestion.aisstream import VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.freight import FreightService
from app.ingestion.prices import PriceService
from app.ingestion.sanctions import SanctionsService
from app.ingestion.weather import WeatherService

GDELT_RESPONSE = {"timeline": [{"data": [{"date": "20260701", "value": 3}, {"date": "20260702", "value": 6}]}]}

NUMERIC_FIELDS = [
    "x_kinetic", "brent_price_usd_bbl", "x_density", "density_state",
    "x_sanctions", "sanctions_state", "x_weather", "scenario", "risk", "reroutes",
]


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "gdeltproject.org" in url:
        return httpx.Response(200, json=GDELT_RESPONSE)
    if "alphavantage.co" in url:
        return httpx.Response(200, json={"data": [{"date": "2026-07-01", "value": "76.20"}]})
    if "api.eia.gov" in url:
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-06-30", "value": "74.50"}]}})
    if "marine-api.open-meteo.com" in url:
        return httpx.Response(200, json={"hourly": {"wave_height": [1.0, 2.0, 3.0]}})
    return httpx.Response(404)


def _build_deps() -> AgentDeps:
    return AgentDeps(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler)),
        settings=get_settings(),
        vessel_store=VesselStore(),
        density_tracker=DensityTracker(min_samples=1),
        coverage_monitor=CoverageMonitor(list(get_settings().ais_boxes)),
        weather_service=WeatherService(),
        sanctions_service=SanctionsService(api_key=""),
        freight_service=FreightService(fred_api_key=""),
        price_service=PriceService(eia_api_key="k", alphavantage_api_key="k"),
        llm=LLMClient(api_key="", model="test-model"),
    )


@pytest.mark.asyncio
async def test_graph_and_sequential_produce_identical_engine_output():
    graph_result = await run_graph(_build_deps(), "hormuz", 0.5, 0.2, 0.45)
    sequential_result = await run_sequential(_build_deps(), "hormuz", 0.5, 0.2, 0.45)

    for field in NUMERIC_FIELDS:
        assert graph_result[field] == sequential_result[field], f"{field} mismatch"

    for key in ("market_narration", "logistics_narration", "macro_narration", "recommendation_narration"):
        assert key in graph_result and key in sequential_result
```

Run: `cd backend && python -m pytest tests/test_agent_parity.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/graph.py backend/app/agents/sequential.py backend/app/agents/runner.py backend/tests/test_agent_parity.py
git commit -m "feat: wire LangGraph pipeline, sequential fallback, and AGENT_MODE runner"
```

---

### Task 8: `GET /recommendation/{corridor}` API route

**Files:**
- Modify: `backend/app/models.py` (add `AgentRecommendation`)
- Modify: `backend/app/api/routes.py` (add route)
- Test: `backend/tests/test_recommendation_route.py`

**Interfaces:**
- Produces: `class AgentRecommendation(BaseModel)` in `models.py`.
- Produces: `GET /recommendation/{corridor}` returning `AgentRecommendation`.
- Consumes: `run_agents`, `AGENT_MODE` from `app.agents.runner`, `AgentDeps` from `app.agents.deps`.

- [ ] **Step 1: Add `AgentRecommendation` to `models.py`**

```python
class AgentRecommendation(BaseModel):
    corridor: str
    risk: RiskScore
    scenario: Scenario
    reroutes: list[RerouteOption]
    market_volatility_label: str
    price_spike_detected: bool
    market_narration: str
    density_state: str
    sanctions_state: str
    logistics_narration: str
    macro_narration: str
    recommendation_narration: str
    agent_mode: str  # "graph" | "sequential" -- whichever actually ran
```

- [ ] **Step 2: Add the route to `routes.py`**

Add imports:
```python
from app.agents.deps import AgentDeps
from app.agents.runner import AGENT_MODE, run_agents
from app.models import AgentRecommendation
```

Add the route:
```python
@router.get("/recommendation/{corridor}", response_model=AgentRecommendation)
async def get_recommendation(
    corridor: str,
    request: Request,
    disruption_factor: float = 0.30,
    substitution_rate: float = 0.20,
    hormuz_share: float = 0.45,
) -> AgentRecommendation:
    if corridor not in SUPPORTED_CORRIDORS:
        raise HTTPException(status_code=404, detail=f"corridor '{corridor}' not wired in Phase 1")

    settings = get_settings()
    deps = AgentDeps(
        http_client=request.app.state.http_client,
        settings=settings,
        vessel_store=request.app.state.vessel_store,
        density_tracker=request.app.state.density_tracker,
        coverage_monitor=request.app.state.coverage_monitor,
        weather_service=request.app.state.weather_service,
        sanctions_service=request.app.state.sanctions_service,
        freight_service=request.app.state.freight_service,
        price_service=request.app.state.price_service,
        llm=request.app.state.llm_client,
    )
    final_state = await run_agents(deps, corridor, disruption_factor, substitution_rate, hormuz_share)

    return AgentRecommendation(
        corridor=corridor,
        risk=RiskScore(**final_state["risk"]),
        scenario=Scenario(**final_state["scenario"]),
        reroutes=[RerouteOption(**r) for r in final_state["reroutes"]],
        market_volatility_label=final_state["market_volatility_label"],
        price_spike_detected=final_state["price_spike_detected"],
        market_narration=final_state["market_narration"],
        density_state=final_state["density_state"],
        sanctions_state=final_state["sanctions_state"],
        logistics_narration=final_state["logistics_narration"],
        macro_narration=final_state["macro_narration"],
        recommendation_narration=final_state["recommendation_narration"],
        agent_mode=AGENT_MODE,
    )
```

- [ ] **Step 3: Write `test_recommendation_route.py`, run, confirm passing**

Reuse `test_agent_parity.py`'s `_mock_handler` shape (via a shared fixture or duplicated inline, matching this file's existing convention of per-file `_mock_handler` functions). Wire `app.state.sanctions_service = SanctionsService(api_key="")`, `app.state.llm_client = LLMClient(api_key="", model="x")`, and the usual `vessel_store`/`density_tracker`/`coverage_monitor`/`freight_service`/`price_service` mocks. Assert `GET /recommendation/hormuz` returns 200, `body["agent_mode"] == "graph"` (default), `body["risk"]["corridor"] == "hormuz"`, `len(body["reroutes"]) == 6`, and every narration field is present and starts with `"STUB —"`. Add a second test for `corridor="malacca"` asserting 404.

Run: `cd backend && python -m pytest tests/test_recommendation_route.py -v`
Expected: 2 passed.

- [ ] **Step 4: Run the full suite**

Run: `cd backend && python -m pytest --ignore=tests/test_gdelt.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/api/routes.py backend/tests/test_recommendation_route.py
git commit -m "feat: expose agent-narrated recommendation via GET /recommendation/{corridor}"
```

---

### Task 9: Cut Chroma RAG, document why

**Files:**
- Modify: `docs/03_build_plan_and_deliverables.md` (RAG row → ✂️)
- Modify: `docs/04_model_assumptions_and_constants.md` (add a note under a new §G)
- Modify: `Readme.md` (tech stack table, repo structure, quickstart)

**Interfaces:** None (docs-only).

- [ ] **Step 1: Update `docs/03_build_plan_and_deliverables.md`**

Change the row:
```
| Chroma RAG over policy/geopolitics docs | Teammate | Innov | ⬜ |
```
to:
```
| Chroma RAG over policy/geopolitics docs | Teammate | Innov | ✂️ (cut Phase 3 — corpus never materialized, docs/03's own "RAG corpus: 10-20 PPAC/EIA/IEA/ORF" row below is still ⬜/empty on disk; policy facts kept inline in agent system prompts instead, docs/04 §G) |
```
And the cut-list line:
```
5. Chroma RAG → cut entirely, keep facts inline
```
stays as-is (already correctly predicted this) — add `✂️ ACTUAL: cut 2026-07-12, see §G` inline after it.

- [ ] **Step 2: Add §G to `docs/04_model_assumptions_and_constants.md`**

```markdown
## G. RAG — cut this phase

Chroma RAG over PPAC/EIA/IEA/ORF policy documents was cut for Phase 3 per
the build plan's own cut-list (#5). The corpus (10-20 public PDFs/articles)
never materialized — confirmed empty by directory search across the repo
on 2026-07-12, no PDFs anywhere. Building a RAG pipeline against zero
documents would mean either fabricating retrieval results or shipping dead
code, neither of which serves the "real data over mocks" principle.

Policy/domain facts the agents need are instead written directly into each
node's system prompt (`backend/app/agents/market.py`, `logistics.py`,
`macro.py`, `orchestrator.py`) as plain instructions, not retrieved
context. If a real corpus is supplied later, `rag/store.py` and
`rag/ingest.py` can be added and the Macro Strategist or Executive
Orchestrator node (whichever fits the policy citation better) wired to
query it for narration context only — never a source of numeric output,
same rule as every other LLM touchpoint in this phase.
```

- [ ] **Step 3: Update `Readme.md`**

In the "Tech stack" table, change:
```
| RAG | Chroma over public policy/geopolitics documents |
```
to:
```
| RAG | Cut Phase 3 — corpus never materialized (docs/04 §G); policy facts kept inline in agent prompts instead |
```

In "Repo structure", change:
```
      rag/               # Phase 3: store.py, ingest.py (not yet present)
```
to:
```
      rag/               # cut Phase 3 -- no corpus (docs/04 §G); not present
```

In the Architecture diagram block, change:
```
      → orchestrator (synthesis + policy citations via RAG)
```
to:
```
      → orchestrator (synthesis + narration, LLM via NVIDIA NIM)
```

- [ ] **Step 4: Commit**

```bash
git add docs/03_build_plan_and_deliverables.md docs/04_model_assumptions_and_constants.md Readme.md
git commit -m "docs: record Chroma RAG cut for Phase 3 (empty corpus) and why"
```

---

### Task 10: Update tracker docs for everything actually built

**Files:**
- Modify: `docs/03_build_plan_and_deliverables.md` (OpenSanctions row, Risk engine row, LangGraph row)
- Modify: `docs/04_model_assumptions_and_constants.md` (§A sanctions note, new §H for LLM wiring)
- Modify: `Readme.md` (quickstart env keys, repo structure `agents/`)

**Interfaces:** None (docs-only). Do this task *after* Tasks 1-8 are verified passing, so the doc update reflects what's actually true, not planned.

- [ ] **Step 1: Update `docs/03_build_plan_and_deliverables.md`**

- `OpenSanctions vessel screening | You | Innov | ⬜` → `✅ (live — SanctionsService screens observed AIS fleet by MMSI, backend/app/ingestion/sanctions.py; wired into both GET /risk/{corridor} and the Logistics agent node so risk score and narration agree; inherits AIS coverage-void state when there's no fleet to screen)`
- `Risk engine (...) | 🟨 (... sanctions stubbed — OPENSANCTIONS_API_KEY not configured)` → `✅ (all five features live: kinetic/density/weather/freight/sanctions; sanctions state-aware — LIVE when AIS-covered and keyed, STUB when unkeyed, inherits WARMING_UP/NO_TERRESTRIAL_COVERAGE when there's no observed fleet)`
- `LangGraph orchestration (4 agents) | You | Tech/Innov | ⬜` → `✅ (Market Intelligence, Logistics & Maritime, Macroeconomic Strategist, Executive Orchestrator; AGENT_MODE=graph default, =sequential fallback calling the identical node functions; GET /recommendation/{corridor})`

- [ ] **Step 2: Update `docs/04_model_assumptions_and_constants.md`**

In §A, update the `X_sanctions` line: change `remains STUB → 0.0 — OPENSANCTIONS_API_KEY is not configured (Phase 2)` to note it's now live-wired Phase 3, with the coverage-inheritance rule, cross-referencing the new §G/§H.

Add §H:
```markdown
## H. LLM wiring (Phase 3)

Agent narration/classification uses NVIDIA NIM's OpenAI-compatible endpoint
(`https://integrate.api.nvidia.com/v1`, `openai` SDK), model
`nvidia/llama-3.1-nemotron-70b-instruct` (`NVIDIA_API_KEY`/`LLM_MODEL` in
`.env`) — a user decision made explicitly for this phase, not the
`ANTHROPIC_API_KEY`/`LLM_MODEL=claude-sonnet-5` hint pre-existing in `.env`
(that pair was never read by any code; grepped confirmed-empty 2026-07-12).

If `NVIDIA_API_KEY` is unset, every node's narration field returns an
honest `"STUB — LLM narration unavailable, NVIDIA_API_KEY not configured."`
string (`backend/app/agents/llm_client.py`) instead of fabricating text —
same pattern as the OpenSanctions stub. The LLM never computes or replaces
a number; every `x_*`/`risk`/`scenario`/`reroutes` field in `AgentState` is
a direct engine/connector passthrough (`backend/app/agents/state.py`).
```

- [ ] **Step 3: Update `Readme.md`**

- Repo structure: change `agents/              # Phase 3: graph.py + market/logistics/macro/orchestrator (not yet present)` to `agents/              # graph.py (LangGraph, default) + sequential.py (fallback) + market/logistics/macro/orchestrator nodes + llm_client.py (NVIDIA NIM)`
- Quickstart env keys block: add `NVIDIA_API_KEY=` and `LLM_MODEL=nvidia/llama-3.1-nemotron-70b-instruct` and `AGENT_MODE=graph` to the copy-paste block, and update the surrounding prose to note OpenSanctions is now wired live (not "still Phase 2 work not yet wired").
- Service URL table: add `| Agent recommendation | http://localhost:8000/recommendation/hormuz |`.

- [ ] **Step 4: Commit**

```bash
git add docs/03_build_plan_and_deliverables.md docs/04_model_assumptions_and_constants.md Readme.md
git commit -m "docs: record Phase 3 agents, live sanctions wiring, and NVIDIA LLM choice in tracker"
```

---

### Task 11 (optional, time-permitting): Frontend narration display

Only start this task after Tasks 1-10 are committed and the Step 4 evidence report (next section) is drafted — per the original prompt's own instruction, this is UX polish, not a sign-off requirement.

**Files:**
- Create: `frontend/components/NarrationPanel.tsx`
- Modify: `frontend/lib/types.ts` (add `AgentRecommendation` interface mirroring `models.py`)
- Modify: `frontend/app/page.tsx` (mount the new component)

**Interfaces:**
- Consumes: `GET /recommendation/hormuz`.
- Produces: a panel rendering `market_narration`, `logistics_narration`, `macro_narration`, `recommendation_narration`, and `agent_mode` alongside the existing risk/scenario/reroute panels.

- [ ] **Step 1: Add the `AgentRecommendation` TypeScript interface to `frontend/lib/types.ts`**, mirroring `AgentRecommendation` from `backend/app/models.py` field-for-field.

- [ ] **Step 2: Write `NarrationPanel.tsx`** following `RerouteCard.tsx`'s exact pattern (`"use client"`, `useDebounce` on `disruptionFactor`, `useEffect` fetch with `cancelled` guard, `.panel` class). Render each narration string in its own labeled block, and a small badge showing `agent_mode`.

- [ ] **Step 3: Mount `<NarrationPanel>` in `frontend/app/page.tsx`** alongside the existing `<RerouteCard>`.

- [ ] **Step 4: Manually verify in a browser** — `docker-compose up`, open `http://localhost:3000`, confirm narration text renders and updates when the disruption slider moves. Screenshot as evidence if the run-app skill/browser tooling is available.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/NarrationPanel.tsx frontend/lib/types.ts frontend/app/page.tsx
git commit -m "feat: add agent narration panel to the frontend"
```

---

## Self-Review

**Spec coverage:** Step 3.1 (state graph, 4 nodes) → Tasks 4-7. Step 3.2 (sequential fallback) → Task 7. Step 3.3 (OpenSanctions honest handling) → Tasks 2-3 (built live + wired, per user decision, not STUB — still honest STUB when the key is later revoked/absent, and honest state-inheritance when there's no fleet). Step 3.4 (Chroma RAG) → Task 9 (cut, documented). Step 3.5 (API wiring, typed) → Task 8. Step 3.6 (frontend, optional) → Task 11. Ground rules' "never let LLM compute numbers" → every node's `AgentState` numeric fields are direct engine/connector passthroughs, verified by Task 7's parity test and Tasks 5-6's exact-match unit tests. Ground rules' "surface decisions" → all four resolved via `AskUserQuestion` before this plan was written. Ground rules' "labeled stubs" → `STUB_NARRATION` pattern in Task 1, sanctions STUB path in Task 2.

**Placeholder scan:** no `TODO`/`TBD`/"add appropriate" language in any step; every code block is complete, runnable file content; every test names its concrete assertions.

**Type consistency:** `AgentState` field names (`x_kinetic`, `brent_price_usd_bbl`, `x_density`, `density_state`, `x_sanctions`, `sanctions_state`, `x_weather`, `scenario`, `risk`, `reroutes`, and the four `*_narration` fields) are used identically across Tasks 4-8's node functions, `graph.py`, `sequential.py`, and the parity test. `LogisticsReading`'s five fields match between `logistics_reading.py` (Task 2) and its two callers (`routes.py` Task 3, `logistics.py` Task 5). `SanctionsService.get_x_sanctions(client, vessels)` signature matches across `logistics_reading.py`, `test_sanctions.py`, and `test_routes.py`'s new tests.

## Step 4 evidence-based verification (do after Tasks 1-10, before declaring Phase 3 done)

Produce the seven items the original prompt's Step 4 requires, using this plan's artifacts directly:
1. Full suite: `cd backend && python -m pytest --ignore=tests/test_gdelt.py -v` (paste raw output; expect the pre-Phase-3 82 plus every new test file's count).
2. Parity: `tests/test_agent_parity.py`'s raw pass/fail output *is* the required side-by-side proof — paste it plus the actual `graph_result`/`sequential_result` dict values for one manual run (add a temporary `print()` or use `-s`, capture, then remove).
3. Narration-matches-engine: run `GET /recommendation/hormuz` against the live stack (real `NVIDIA_API_KEY` once the user has added it, real `OPENSANCTIONS_API_KEY` already present) and paste the raw JSON response — `risk.contributions` sits right next to `recommendation_narration` in the same payload, so this is directly visible.
4. OpenSanctions: paste a raw `/risk/hormuz` response showing `feature_states.sanctions` and, separately, the raw OpenSanctions API response from a real screening call (same pattern as this session's own live 200-response test).
5. RAG: paste Task 9's actual `git diff` for `docs/04`/`Readme.md`.
6. Latency: time a real `GET /recommendation/hormuz` call end-to-end (`curl -w "%{time_total}\n"` or Python `time.perf_counter()` around the request) against the live stack; report the number and flag explicitly whether it changes the "seconds, not weeks" claim.
7. Docs: paste the raw `git diff` for `docs/03`, `docs/04`, `Readme.md` from Tasks 9-10.
