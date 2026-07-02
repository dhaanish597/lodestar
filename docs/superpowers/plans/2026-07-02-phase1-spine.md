# Lodestar Phase 1 — The Spine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real Hormuz tankers render live on a MapLibre/deck.gl map, and a corridor shows a live, explainable risk % — the P1 exit test from `CLAUDE.md` §8: *"real tankers move on the map and a corridor shows a live %."*

**Architecture:** FastAPI backend runs a persistent AISStream WebSocket client that maintains an in-memory vessel store (with dead-reckoning for stale positions), relays it to the frontend over `/ws/vessels`, and exposes `GET /risk/{corridor}` which combines a live GDELT kinetic-news feature with a live AIS vessel-density feature through a deterministic sigmoid risk engine. Next.js + deck.gl + MapLibre renders the live vessels and risk score, plus a hardcoded scenario/reroute card to prove the full UI pipe end-to-end.

**Tech Stack:** Python 3.11, FastAPI, `websockets`, `httpx`, Pydantic v2, `pydantic-settings`, pytest + pytest-asyncio (backend). Next.js 14 (app router) + TypeScript, deck.gl, maplibre-gl (frontend). Docker + docker-compose (api, web only — chroma/redis are later phases).

## Global Constraints

- Real live data over mocks. If a data source can't be live yet, mark it `STUB →` with a TODO naming the real source (from `docs/02_data_sources_and_schemas.md` and `docs/04_model_assumptions_and_constants.md`).
- API keys only from `.env`, never hardcoded, never committed. `backend/.env` is already gitignored (pattern `.env` in `.gitignore` matches at any depth).
- MapLibre + free tiles, no Mapbox token. Use CARTO's free "Positron" style: `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json` (no key required).
- Typed Pydantic contracts: `Vessel`, `RiskScore`, `Scenario`, `RerouteOption` — define once in `backend/app/models.py`, build everything against them.
- AISStream: subscribe within 3s of connect (send immediately after connect — trivially satisfied); reconnect with backoff, resend subscription on every reconnect; dead-reckoning if `now - timestamp > 2h`, flag `signal_lost=true`.
- Risk formula (`docs/04_model_assumptions_and_constants.md` §A): `P = sigmoid(β0 + Σ wi·Xi)`, `β0 = -3.0`, weights `kinetic=0.40, density=0.25, sanctions=0.15, weather=0.10, freight=0.10`. Phase 1 wires `kinetic` and `density` live; `sanctions`, `weather`, `freight` are `STUB →` fixed at `Xi=0.0` (real sources: OpenSanctions, Open-Meteo, FRED — Phase 2/3).
- Vessel "density anomaly" per doc is "≥ Nσ below 30-day MA" — a 30-day baseline cannot exist in a live demo. Phase 1 substitutes a short in-memory rolling window as an `ASSUMPTION` (documented in the docs-sync task), not a fabricated 30-day number.
- Repo structure follows `README.md`'s "Repo structure" section (already written) exactly.
- No LLM in the math path. Risk engine is pure, deterministic, testable.
- Rate limits: Alpha Vantage 25 req/day (not used in Phase 1). GDELT only covers the last 90 days (fine — we query `timespan=72h`).

---

## File Structure

```
backend/
  app/
    __init__.py
    main.py                    # FastAPI app, lifespan (AIS client + httpx client), mounts routers, /health
    config.py                  # pydantic-settings: env keys + corridors.json loader
    models.py                  # Vessel, RiskScore, Scenario, RerouteOption
    ingestion/
      __init__.py
      dead_reckoning.py        # pure extrapolation + signal_lost flagging
      aisstream.py             # VesselStore + AISStreamClient (testable via injected connector)
      density.py               # DensityTracker → X_density
      gdelt.py                 # fetch_kinetic_volume → X_kinetic
    engine/
      __init__.py
      risk.py                  # compute_risk(): sigmoid + per-feature contributions
    api/
      __init__.py
      routes.py                # GET /risk/{corridor}
      ws.py                    # WS /ws/vessels relay
  data/
    corridors.json             # hormuz (+ bab_el_mandeb, malacca stubs) bbox constants
  tests/
    __init__.py
    test_dead_reckoning.py
    test_aisstream.py
    test_density.py
    test_gdelt.py
    test_risk.py
  requirements.txt
  Dockerfile
  .env.example
frontend/
  app/
    layout.tsx
    page.tsx
    globals.css
  components/
    MapDeck.tsx                # deck.gl + MapLibre, live vessel ScatterplotLayer
    RiskPanel.tsx               # fetches GET /risk/hormuz, stacked contribution bar
    ScenarioCard.tsx            # hardcoded scenario readout (proves the pipe)
    RerouteCard.tsx             # hardcoded ranked reroute list (proves the pipe)
  lib/
    types.ts                   # TS mirror of backend Pydantic contracts
    ws.ts                      # useVesselStream() hook
  package.json
  tsconfig.json
  next.config.js
  Dockerfile
docker-compose.yml
```

---

### Task 1: Backend scaffold — config & Pydantic contracts

**Files:**
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/config.py`
- Create: `backend/app/models.py`
- Create: `backend/data/corridors.json`
- Create: `backend/requirements.txt`
- Create: `backend/.env.example`
- Test: `backend/tests/__init__.py` (empty), `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings, singleton via `get_settings()`), `Corridor(bbox: tuple[float,float,float,float], note: str | None)`, `Vessel`, `RiskScore`, `Scenario`, `RerouteOption` — every later task imports these from `app.config` / `app.models`.

- [ ] **Step 1: Write `backend/data/corridors.json`**

```json
{
  "hormuz": { "bbox": [25.2732, 55.1647, 27.3713, 57.3419] },
  "bab_el_mandeb": { "bbox": [11.5, 43.0, 13.2, 43.6], "note": "approx; ~12.5N Djibouti/Eritrea to Yemen; future work, not wired in Phase 1" },
  "malacca": { "bbox": [1.0, 100.0, 6.0, 104.0], "note": "approx; true shape is a multi-point polygon; future work, not wired in Phase 1" }
}
```

- [ ] **Step 2: Write the failing test for models**

```python
# backend/tests/test_models.py
from datetime import datetime, timezone

from app.models import RerouteOption, RiskScore, Scenario, Vessel


def test_vessel_requires_core_ais_fields():
    v = Vessel(
        mmsi=205344990,
        lat=26.5,
        lon=56.3,
        sog=12.4,
        cog=88.0,
        true_heading=90,
        nav_status=0,
        timestamp=datetime.now(timezone.utc),
    )
    assert v.signal_lost is False
    assert v.extrapolated is False


def test_risk_score_carries_full_feature_breakdown():
    r = RiskScore(
        corridor="hormuz",
        timestamp=datetime.now(timezone.utc),
        probability=0.5,
        beta0=-3.0,
        weights={"kinetic": 0.40, "density": 0.25, "sanctions": 0.15, "weather": 0.10, "freight": 0.10},
        features={"kinetic": 0.8, "density": 0.0, "sanctions": 0.0, "weather": 0.0, "freight": 0.0},
        contributions={"kinetic": 0.32, "density": 0.0, "sanctions": 0.0, "weather": 0.0, "freight": 0.0},
    )
    assert set(r.contributions) == set(r.weights)


def test_scenario_and_reroute_contracts_instantiate():
    s = Scenario(
        corridor="hormuz",
        disruption_factor=0.30,
        substitution_rate=0.20,
        hormuz_share=0.45,
        india_imports_mbd=4.7,
        supply_gap_mbd=0.5,
        utilization_drop_pct=0.06,
        spr_fill_pct=0.64,
        days_cover_remaining=9.5,
        cpi_sensitivity=0.35,
        cpi_delta_pp=0.2,
        gdp_drag_bps=8.0,
        cad_sensitivity=0.35,
        cad_widening_pct_gdp=0.15,
    )
    r = RerouteOption(
        source_grade="Urals",
        origin="Russia",
        api_gravity=31.0,
        sulfur_pct=1.3,
        landed_cost_usd_bbl=78.5,
        voyage_days=25.0,
        grade_match=1.0,
        congestion_penalty=0.1,
        score=0.81,
        best_fit_refineries=["RIL Jamnagar", "Nayara Vadinar"],
    )
    assert s.corridor == "hormuz"
    assert r.grade_match == 1.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` (or `app.models` doesn't exist yet)

- [ ] **Step 4: Write `backend/app/models.py`**

```python
# backend/app/models.py
from datetime import datetime

from pydantic import BaseModel


class Vessel(BaseModel):
    mmsi: int
    lat: float
    lon: float
    sog: float  # speed over ground, knots
    cog: float | None = None
    true_heading: float | None = None
    nav_status: int | None = None
    timestamp: datetime
    valid: bool = True
    signal_lost: bool = False
    extrapolated: bool = False


class RiskScore(BaseModel):
    corridor: str
    timestamp: datetime
    probability: float
    beta0: float
    weights: dict[str, float]
    features: dict[str, float]
    contributions: dict[str, float]


class Scenario(BaseModel):
    corridor: str
    disruption_factor: float
    substitution_rate: float
    hormuz_share: float
    india_imports_mbd: float
    supply_gap_mbd: float
    utilization_drop_pct: float
    spr_fill_pct: float
    days_cover_remaining: float
    cpi_sensitivity: float
    cpi_delta_pp: float
    gdp_drag_bps: float
    cad_sensitivity: float
    cad_widening_pct_gdp: float


class RerouteOption(BaseModel):
    source_grade: str
    origin: str
    api_gravity: float
    sulfur_pct: float
    landed_cost_usd_bbl: float
    voyage_days: float
    grade_match: float
    congestion_penalty: float
    score: float
    best_fit_refineries: list[str]
```

- [ ] **Step 5: Write `backend/app/config.py`**

```python
# backend/app/config.py
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Corridor(BaseModel):
    bbox: tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max
    note: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aisstream_api_key: str = ""
    eia_api_key: str = ""
    alphavantage_api_key: str = ""
    opensanctions_api_key: str = ""
    fred_api_key: str = ""

    @property
    def corridors(self) -> dict[str, Corridor]:
        raw = json.loads((DATA_DIR / "corridors.json").read_text())
        return {name: Corridor(**value) for name, value in raw.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Write `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.9.2
pydantic-settings==2.5.2
websockets==13.1
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 7: Write `backend/.env.example`**

```
AISSTREAM_API_KEY=
EIA_API_KEY=
ALPHAVANTAGE_API_KEY=
OPENSANCTIONS_API_KEY=
FRED_API_KEY=
# GDELT and Open-Meteo need no key
```

- [ ] **Step 8: Install deps and run test to verify it passes**

Run: `cd backend && pip install -r requirements.txt && python -m pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add backend/app/__init__.py backend/app/config.py backend/app/models.py backend/data/corridors.json backend/requirements.txt backend/.env.example backend/tests/__init__.py backend/tests/test_models.py
git commit -m "feat(backend): scaffold config and typed Pydantic contracts"
```

---

### Task 2: FastAPI skeleton + `/health`

**Files:**
- Create: `backend/app/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `get_settings()` from Task 1.
- Produces: FastAPI `app` object at `app.main:app`, importable by `uvicorn` and by later tasks' routers.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write `backend/app/main.py` (minimal — routers added in later tasks)**

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Lodestar API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_health.py
git commit -m "feat(backend): FastAPI skeleton with /health"
```

---

### Task 3: Dead-reckoning utility

**Files:**
- Create: `backend/app/ingestion/__init__.py` (empty)
- Create: `backend/app/ingestion/dead_reckoning.py`
- Test: `backend/tests/test_dead_reckoning.py`

**Interfaces:**
- Consumes: `Vessel` from Task 1.
- Produces: `apply_dead_reckoning(vessel: Vessel, now: datetime) -> Vessel` — consumed by Task 4 (`VesselStore.snapshot`) and Task 5 (`/ws/vessels`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_dead_reckoning.py
from datetime import datetime, timedelta, timezone

from app.ingestion.dead_reckoning import apply_dead_reckoning
from app.models import Vessel


def _vessel(minutes_old: float, sog: float = 10.0, heading: float = 90.0) -> Vessel:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    return Vessel(mmsi=1, lat=26.0, lon=56.0, sog=sog, true_heading=heading, timestamp=ts)


def test_fresh_position_is_unchanged():
    v = _vessel(minutes_old=10)
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.lat == v.lat
    assert out.lon == v.lon
    assert out.signal_lost is False
    assert out.extrapolated is False


def test_stale_position_is_extrapolated_and_flagged():
    v = _vessel(minutes_old=181)  # > 2h
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.signal_lost is True
    assert out.extrapolated is True
    # heading 90 (due east) at nonzero speed moves lon east, lat ~unchanged
    assert out.lon > v.lon
    assert abs(out.lat - v.lat) < 0.05


def test_stale_but_stationary_vessel_does_not_move():
    v = _vessel(minutes_old=181, sog=0.0)
    now = datetime.now(timezone.utc)
    out = apply_dead_reckoning(v, now)
    assert out.signal_lost is True
    assert out.lat == v.lat
    assert out.lon == v.lon
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_dead_reckoning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.dead_reckoning'`

- [ ] **Step 3: Write `backend/app/ingestion/dead_reckoning.py`**

```python
# backend/app/ingestion/dead_reckoning.py
import math
from datetime import datetime, timedelta

from app.models import Vessel

STALE_THRESHOLD = timedelta(hours=2)
EARTH_RADIUS_NM = 3440.065


def _project(lat_deg: float, lon_deg: float, bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    lat1 = math.radians(lat_deg)
    lon1 = math.radians(lon_deg)
    bearing = math.radians(bearing_deg)
    d_r = distance_nm / EARTH_RADIUS_NM

    lat2 = math.asin(math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(bearing))
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def apply_dead_reckoning(vessel: Vessel, now: datetime) -> Vessel:
    age = now - vessel.timestamp
    if age <= STALE_THRESHOLD:
        return vessel

    heading = vessel.true_heading if vessel.true_heading is not None else vessel.cog
    if heading is None or vessel.sog <= 0:
        return vessel.model_copy(update={"signal_lost": True, "extrapolated": True})

    hours = age.total_seconds() / 3600
    distance_nm = vessel.sog * hours
    new_lat, new_lon = _project(vessel.lat, vessel.lon, heading, distance_nm)
    return vessel.model_copy(update={"lat": new_lat, "lon": new_lon, "signal_lost": True, "extrapolated": True})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_dead_reckoning.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/__init__.py backend/app/ingestion/dead_reckoning.py backend/tests/test_dead_reckoning.py
git commit -m "feat(backend): dead-reckoning extrapolation for stale AIS positions"
```

---

### Task 4: AISStream WebSocket client + vessel store

**Files:**
- Create: `backend/app/ingestion/aisstream.py`
- Test: `backend/tests/test_aisstream.py`

**Interfaces:**
- Consumes: `Vessel`, `Corridor` (Task 1), `apply_dead_reckoning` (Task 3).
- Produces: `VesselStore` with `upsert(vessel: Vessel)` and `snapshot(now: datetime | None = None) -> list[Vessel]`; `AISStreamClient(api_key: str, corridor: Corridor, store: VesselStore, connector=websockets.connect)` with `async def run(self) -> None` (production loop) and `async def _consume(self, ws) -> None` (single-connection message loop, unit-testable). Task 5 (`/ws/vessels`) consumes `VesselStore.snapshot()`. Task 9 (`/risk`) consumes `len(store.snapshot())` for density sampling. `main.py` (Task 6 wiring) consumes `AISStreamClient.run()` as a background task.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aisstream.py
import json
from datetime import datetime, timezone

import pytest

from app.config import Corridor
from app.ingestion.aisstream import AISStreamClient, VesselStore


class FakeWebSocket:
    def __init__(self, messages: list[str]):
        self._messages = list(messages)
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def _position_report(mmsi: int) -> str:
    return json.dumps(
        {
            "MessageType": "PositionReport",
            "Message": {
                "PositionReport": {
                    "UserID": mmsi,
                    "Latitude": 26.1,
                    "Longitude": 56.2,
                    "Sog": 11.5,
                    "Cog": 91.0,
                    "TrueHeading": 90,
                    "NavigationalStatus": 0,
                }
            },
            "MetaData": {"time_utc": "2026-07-02T10:00:00Z"},
        }
    )


def test_store_upsert_and_snapshot_returns_latest_per_mmsi():
    store = VesselStore()
    from app.models import Vessel

    store.upsert(Vessel(mmsi=1, lat=1.0, lon=1.0, sog=0, timestamp=datetime.now(timezone.utc)))
    store.upsert(Vessel(mmsi=1, lat=2.0, lon=2.0, sog=0, timestamp=datetime.now(timezone.utc)))
    snap = store.snapshot()
    assert len(snap) == 1
    assert snap[0].lat == 2.0


@pytest.mark.asyncio
async def test_consume_subscribes_within_first_send_and_parses_position_reports():
    store = VesselStore()
    corridor = Corridor(bbox=(25.2732, 55.1647, 27.3713, 57.3419))
    client = AISStreamClient(api_key="testkey", corridor=corridor, store=store)
    ws = FakeWebSocket([_position_report(111222333), _position_report(444555666)])

    await client._consume(ws)

    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["APIKey"] == "testkey"
    assert payload["BoundingBoxes"] == [[[25.2732, 55.1647], [27.3713, 57.3419]]]
    assert payload["FilterMessageTypes"] == ["PositionReport"]

    snap = store.snapshot()
    assert {v.mmsi for v in snap} == {111222333, 444555666}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_aisstream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.aisstream'`

- [ ] **Step 3: Write `backend/app/ingestion/aisstream.py`**

```python
# backend/app/ingestion/aisstream.py
import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from app.config import Corridor
from app.ingestion.dead_reckoning import apply_dead_reckoning
from app.models import Vessel

logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
MAX_BACKOFF_SECONDS = 30


class VesselStore:
    def __init__(self) -> None:
        self._vessels: dict[int, Vessel] = {}

    def upsert(self, vessel: Vessel) -> None:
        self._vessels[vessel.mmsi] = vessel

    def snapshot(self, now: datetime | None = None) -> list[Vessel]:
        now = now or datetime.now(timezone.utc)
        return [apply_dead_reckoning(v, now) for v in self._vessels.values()]


def _parse_position_report(raw: dict) -> Vessel | None:
    if raw.get("MessageType") != "PositionReport":
        return None
    report = raw["Message"]["PositionReport"]
    meta = raw.get("MetaData", {})
    ts_raw = meta.get("time_utc")
    timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.now(timezone.utc)
    return Vessel(
        mmsi=report["UserID"],
        lat=report["Latitude"],
        lon=report["Longitude"],
        sog=report.get("Sog", 0.0),
        cog=report.get("Cog"),
        true_heading=report.get("TrueHeading"),
        nav_status=report.get("NavigationalStatus"),
        timestamp=timestamp,
        valid=raw.get("Valid", True),
    )


class AISStreamClient:
    def __init__(self, api_key: str, corridor: Corridor, store: VesselStore, connector=None):
        self.api_key = api_key
        self.corridor = corridor
        self.store = store
        self._connector = connector or websockets.connect

    def _subscribe_payload(self) -> str:
        lat_min, lon_min, lat_max, lon_max = self.corridor.bbox
        return json.dumps(
            {
                "APIKey": self.api_key,
                "BoundingBoxes": [[[lat_min, lon_min], [lat_max, lon_max]]],
                "FilterMessageTypes": ["PositionReport"],
            }
        )

    async def _consume(self, ws) -> None:
        await ws.send(self._subscribe_payload())
        async for raw_message in ws:
            try:
                data = json.loads(raw_message)
                vessel = _parse_position_report(data)
                if vessel is not None:
                    self.store.upsert(vessel)
            except Exception:
                logger.exception("Failed to process AIS message")

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                async with self._connector(AISSTREAM_URL) as ws:
                    backoff = 1
                    await self._consume(ws)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AISStream connection lost, reconnecting in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
```

- [ ] **Step 4: Add `pytest-asyncio` mode config and run test to verify it passes**

Add to `backend/requirements.txt` (already present from Task 1) — just create `backend/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

Run: `cd backend && python -m pytest tests/test_aisstream.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/aisstream.py backend/tests/test_aisstream.py backend/pytest.ini
git commit -m "feat(backend): AISStream WebSocket client with reconnect-with-backoff and vessel store"
```

---

### Task 5: `/ws/vessels` relay endpoint

**Files:**
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/ws.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_ws_vessels.py`

**Interfaces:**
- Consumes: `VesselStore` (Task 4), attached to `app.state.vessel_store`.
- Produces: WebSocket route `/ws/vessels` streaming `list[Vessel]` as JSON every 2s. Frontend Task 11 consumes this.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ws_vessels.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.ingestion.aisstream import VesselStore
from app.main import app
from app.models import Vessel


def test_ws_vessels_streams_current_snapshot():
    store = VesselStore()
    store.upsert(Vessel(mmsi=9, lat=26.5, lon=56.1, sog=10.0, timestamp=datetime.now(timezone.utc)))
    app.state.vessel_store = store

    with TestClient(app) as client:
        with client.websocket_connect("/ws/vessels") as ws:
            payload = ws.receive_json()

    assert isinstance(payload, list)
    assert payload[0]["mmsi"] == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ws_vessels.py -v`
Expected: FAIL with `404` / route not found (or `AttributeError` on `app.state.vessel_store`)

- [ ] **Step 3: Write `backend/app/api/ws.py`**

```python
# backend/app/api/ws.py
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

BROADCAST_INTERVAL_SECONDS = 2


@router.websocket("/ws/vessels")
async def ws_vessels(websocket: WebSocket) -> None:
    await websocket.accept()
    store = websocket.app.state.vessel_store
    try:
        while True:
            snapshot = store.snapshot()
            await websocket.send_text(json.dumps([v.model_dump(mode="json") for v in snapshot]))
            await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
```

- [ ] **Step 4: Wire into `backend/app/main.py`**

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ws import router as ws_router
from app.ingestion.aisstream import VesselStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.vessel_store = VesselStore()
    yield


app = FastAPI(title="Lodestar API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ws_vessels.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/__init__.py backend/app/api/ws.py backend/app/main.py backend/tests/test_ws_vessels.py
git commit -m "feat(backend): /ws/vessels relay endpoint"
```

---

### Task 6: GDELT connector (`X_kinetic`)

**Files:**
- Create: `backend/app/ingestion/gdelt.py`
- Test: `backend/tests/test_gdelt.py`

**Interfaces:**
- Consumes: `httpx.AsyncClient` (injected).
- Produces: `async def fetch_kinetic_volume(client: httpx.AsyncClient) -> float` returning a MinMax-scaled `[0,1]` value. Task 9 consumes this for `X_kinetic`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gdelt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.gdelt'`

- [ ] **Step 3: Write `backend/app/ingestion/gdelt.py`**

```python
# backend/app/ingestion/gdelt.py
import httpx

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '(Hormuz OR "Red Sea") (attack OR strike OR sanction OR disruption)'
HORMUZ_BBOX = "25.27,55.16,27.37,57.34"


async def fetch_kinetic_volume(client: httpx.AsyncClient) -> float:
    """Fetch GDELT TimelineVol for the corridor and MinMax-scale the latest point into [0,1].

    STUB -> theme filtering (e.g. theme=CRISISLEX_CRISISLEXREC) noted in docs/02
    as a noise-reduction improvement; not applied in Phase 1 for query simplicity.
    """
    response = await client.get(
        GDELT_URL,
        params={
            "query": QUERY,
            "mode": "TimelineVol",
            "timespan": "72h",
            "format": "json",
            "bbox": HORMUZ_BBOX,
        },
    )
    response.raise_for_status()
    payload = response.json()
    timelines = payload.get("timeline", [])
    if not timelines:
        return 0.0
    points = timelines[0].get("data", [])
    if not points:
        return 0.0

    values = [p["value"] for p in points]
    lo, hi = min(values), max(values)
    if hi == lo:
        return 0.0
    return (values[-1] - lo) / (hi - lo)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gdelt.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/gdelt.py backend/tests/test_gdelt.py
git commit -m "feat(backend): GDELT TimelineVol connector for X_kinetic"
```

---

### Task 7: Vessel density feature (`X_density`)

**Files:**
- Create: `backend/app/ingestion/density.py`
- Test: `backend/tests/test_density.py`

**Interfaces:**
- Consumes: nothing external — pure in-memory tracker.
- Produces: `DensityTracker` with `sample(count: int) -> None` and `x_density() -> float`. Task 9 owns one instance and feeds it `len(store.snapshot())` on every risk request.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_density.py
from app.ingestion.density import DensityTracker


def test_returns_zero_with_insufficient_samples():
    t = DensityTracker(min_samples=5)
    for count in [20, 21, 19]:
        t.sample(count)
    assert t.x_density() == 0.0


def test_flags_anomaly_when_count_drops_far_below_rolling_mean():
    t = DensityTracker(min_samples=5, sigma_threshold=1.5)
    for count in [20, 21, 19, 22, 20]:
        t.sample(count)
    assert t.x_density() == 0.0  # baseline established, no drop yet

    t.sample(2)  # sharp drop
    assert t.x_density() == 1.0


def test_window_is_bounded():
    t = DensityTracker(window=3, min_samples=1)
    for count in [10, 10, 10, 10, 10]:
        t.sample(count)
    assert len(t._samples) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_density.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.density'`

- [ ] **Step 3: Write `backend/app/ingestion/density.py`**

```python
# backend/app/ingestion/density.py
import statistics
from collections import deque


class DensityTracker:
    """Rolling-window vessel-count anomaly detector.

    ASSUMPTION -> docs/04_model_assumptions_and_constants.md specifies a 30-day
    moving average baseline for X_density; a live demo cannot accumulate 30 days
    of history. This substitutes a short in-memory rolling window (default 20
    samples) as a calibrated stand-in, documented here and in docs/04.

    STUB -> AISStream PositionReport carries no vessel-type field, so this counts
    all AIS contacts in the bbox, not tankers specifically. Real tanker filtering
    requires subscribing to ShipStaticData messages (TODO: Phase 2, docs/02).
    """

    def __init__(self, window: int = 20, min_samples: int = 5, sigma_threshold: float = 1.5):
        self._samples: deque[int] = deque(maxlen=window)
        self.min_samples = min_samples
        self.sigma_threshold = sigma_threshold

    def sample(self, count: int) -> None:
        self._samples.append(count)

    def x_density(self) -> float:
        if len(self._samples) < self.min_samples:
            return 0.0
        mean = statistics.mean(self._samples)
        stdev = statistics.pstdev(self._samples)
        if stdev == 0:
            return 0.0
        latest = self._samples[-1]
        return 1.0 if latest <= mean - self.sigma_threshold * stdev else 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_density.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/density.py backend/tests/test_density.py
git commit -m "feat(backend): rolling-window vessel-density anomaly tracker for X_density"
```

---

### Task 8: Risk engine

**Files:**
- Create: `backend/app/engine/__init__.py` (empty)
- Create: `backend/app/engine/risk.py`
- Test: `backend/tests/test_risk.py`

**Interfaces:**
- Consumes: `RiskScore` (Task 1).
- Produces: `compute_risk(corridor: str, x_kinetic: float, x_density: float, x_sanctions: float = 0.0, x_weather: float = 0.0, x_freight: float = 0.0, now: datetime | None = None) -> RiskScore`. Task 9 consumes this.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_risk.py
import math

import pytest

from app.engine.risk import BETA0, WEIGHTS, compute_risk


def test_all_zero_features_gives_background_probability():
    r = compute_risk(corridor="hormuz", x_kinetic=0.0, x_density=0.0)
    assert r.probability == pytest.approx(1 / (1 + math.exp(3.0)), abs=1e-6)
    assert r.probability == pytest.approx(0.0474, abs=1e-3)


def test_contributions_sum_matches_logit_offset_from_beta0():
    r = compute_risk(corridor="hormuz", x_kinetic=0.8, x_density=1.0)
    logit = math.log(r.probability / (1 - r.probability))
    assert logit == pytest.approx(BETA0 + sum(r.contributions.values()), abs=1e-6)


def test_unwired_features_are_present_but_zero():
    r = compute_risk(corridor="hormuz", x_kinetic=0.5, x_density=0.5)
    for stub_feature in ("sanctions", "weather", "freight"):
        assert r.features[stub_feature] == 0.0
        assert r.contributions[stub_feature] == 0.0


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_risk.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine'`

- [ ] **Step 3: Write `backend/app/engine/risk.py`**

```python
# backend/app/engine/risk.py
import math
from datetime import datetime, timezone

from app.models import RiskScore

BETA0 = -3.0
WEIGHTS = {
    "kinetic": 0.40,
    "density": 0.25,
    "sanctions": 0.15,
    "weather": 0.10,
    "freight": 0.10,
}


def compute_risk(
    corridor: str,
    x_kinetic: float,
    x_density: float,
    x_sanctions: float = 0.0,  # STUB -> OpenSanctions vessel screening, docs/02 §4 (Phase 2)
    x_weather: float = 0.0,  # STUB -> Open-Meteo Marine wave height, docs/02 §6 (Phase 2)
    x_freight: float = 0.0,  # STUB -> FRED BCTI/BDI freight proxy, docs/02 §7 (Phase 2)
    now: datetime | None = None,
) -> RiskScore:
    features = {
        "kinetic": x_kinetic,
        "density": x_density,
        "sanctions": x_sanctions,
        "weather": x_weather,
        "freight": x_freight,
    }
    contributions = {name: WEIGHTS[name] * value for name, value in features.items()}
    logit = BETA0 + sum(contributions.values())
    probability = 1 / (1 + math.exp(-logit))

    return RiskScore(
        corridor=corridor,
        timestamp=now or datetime.now(timezone.utc),
        probability=probability,
        beta0=BETA0,
        weights=WEIGHTS,
        features=features,
        contributions=contributions,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_risk.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/__init__.py backend/app/engine/risk.py backend/tests/test_risk.py
git commit -m "feat(backend): deterministic sigmoid risk engine with per-feature contributions"
```

---

### Task 9: `GET /risk/{corridor}` — wire GDELT + density + risk engine + AIS client into `main.py`

**Files:**
- Create: `backend/app/api/routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `fetch_kinetic_volume` (Task 6), `DensityTracker` (Task 7), `compute_risk` (Task 8), `VesselStore` (Task 4), `AISStreamClient` (Task 4), `get_settings` (Task 1).
- Produces: `GET /risk/{corridor}` → `RiskScore` JSON; 404 for any corridor other than `hormuz` in Phase 1. Frontend Task 12 consumes this endpoint.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_routes.py -v`
Expected: FAIL with `404` for `/risk/hormuz` (route doesn't exist yet) or `AttributeError` on missing state

- [ ] **Step 3: Write `backend/app/api/routes.py`**

```python
# backend/app/api/routes.py
from fastapi import APIRouter, HTTPException, Request

from app.engine.risk import compute_risk
from app.ingestion.gdelt import fetch_kinetic_volume
from app.models import RiskScore

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
```

- [ ] **Step 4: Wire routes + AIS client + http client into `backend/app/main.py`**

```python
# backend/app/main.py
import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as risk_router
from app.api.ws import router as ws_router
from app.config import get_settings
from app.ingestion.aisstream import AISStreamClient, VesselStore
from app.ingestion.density import DensityTracker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.vessel_store = VesselStore()
    app.state.density_tracker = DensityTracker()
    app.state.http_client = httpx.AsyncClient(timeout=10.0)

    ais_client = AISStreamClient(
        api_key=settings.aisstream_api_key,
        corridor=settings.corridors["hormuz"],
        store=app.state.vessel_store,
    )
    task = asyncio.create_task(ais_client.run())

    yield

    task.cancel()
    await app.state.http_client.aclose()


app = FastAPI(title="Lodestar API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(risk_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests across all prior tasks, including the 2 new ones — full suite should be green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/app/main.py backend/tests/test_routes.py
git commit -m "feat(backend): GET /risk/{corridor} wiring GDELT, density, and risk engine end to end"
```

---

### Task 10: Frontend scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.js`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/globals.css`
- Create: `frontend/lib/types.ts`

**Interfaces:**
- Produces: TS types `Vessel`, `RiskScore`, `Scenario`, `RerouteOption` mirroring `backend/app/models.py` exactly (field names and shapes) — every later frontend task imports from here. Next.js app shell that Task 11/12/13 render inside.

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "lodestar-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start -p 3000"
  },
  "dependencies": {
    "@deck.gl/core": "^9.0.0",
    "@deck.gl/layers": "^9.0.0",
    "@deck.gl/react": "^9.0.0",
    "maplibre-gl": "^4.5.0",
    "next": "14.2.5",
    "react": "18.3.1",
    "react-dom": "18.3.1"
  },
  "devDependencies": {
    "@types/node": "20.14.0",
    "@types/react": "18.3.3",
    "@types/react-dom": "18.3.0",
    "typescript": "5.5.3"
  }
}
```

- [ ] **Step 2: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./*"] },
    "plugins": [{ "name": "next" }]
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Write `frontend/next.config.js`**

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

module.exports = nextConfig;
```

- [ ] **Step 4: Write `frontend/lib/types.ts`**

```typescript
// frontend/lib/types.ts
export interface Vessel {
  mmsi: number;
  lat: number;
  lon: number;
  sog: number;
  cog: number | null;
  true_heading: number | null;
  nav_status: number | null;
  timestamp: string;
  valid: boolean;
  signal_lost: boolean;
  extrapolated: boolean;
}

export interface RiskScore {
  corridor: string;
  timestamp: string;
  probability: number;
  beta0: number;
  weights: Record<string, number>;
  features: Record<string, number>;
  contributions: Record<string, number>;
}

export interface Scenario {
  corridor: string;
  disruption_factor: number;
  substitution_rate: number;
  hormuz_share: number;
  india_imports_mbd: number;
  supply_gap_mbd: number;
  utilization_drop_pct: number;
  spr_fill_pct: number;
  days_cover_remaining: number;
  cpi_sensitivity: number;
  cpi_delta_pp: number;
  gdp_drag_bps: number;
  cad_sensitivity: number;
  cad_widening_pct_gdp: number;
}

export interface RerouteOption {
  source_grade: string;
  origin: string;
  api_gravity: number;
  sulfur_pct: number;
  landed_cost_usd_bbl: number;
  voyage_days: number;
  grade_match: number;
  congestion_penalty: number;
  score: number;
  best_fit_refineries: string[];
}
```

- [ ] **Step 5: Write `frontend/app/globals.css`**

```css
* {
  box-sizing: border-box;
}

html,
body,
#__next {
  height: 100%;
  margin: 0;
  padding: 0;
  background: #0b0e14;
  color: #e6e6e6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
```

- [ ] **Step 6: Write `frontend/app/layout.tsx`**

```tsx
// frontend/app/layout.tsx
import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Lodestar",
  description: "Live energy supply-chain resilience for the Strait of Hormuz",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 7: Install deps and verify the project builds (no page yet — expect a build error naming the missing page, which Task 11 resolves)**

Run: `cd frontend && npm install`
Expected: install completes with no errors

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/next.config.js frontend/app/layout.tsx frontend/app/globals.css frontend/lib/types.ts
git commit -m "feat(frontend): Next.js + TypeScript scaffold with backend-mirrored types"
```

---

### Task 11: Live vessel map — deck.gl + MapLibre + `/ws/vessels`

**Files:**
- Create: `frontend/lib/ws.ts`
- Create: `frontend/components/MapDeck.tsx`
- Create: `frontend/app/page.tsx` (placeholder — replaced fully in Task 13)

**Interfaces:**
- Consumes: `Vessel` type (Task 10), backend `/ws/vessels` (Task 5).
- Produces: `useVesselStream(url: string): Vessel[]` hook; `<MapDeck vessels={Vessel[]} />` component. Task 13's `page.tsx` renders `<MapDeck />`.

- [ ] **Step 1: Write `frontend/lib/ws.ts`**

```typescript
// frontend/lib/ws.ts
"use client";

import { useEffect, useState } from "react";
import type { Vessel } from "./types";

export function useVesselStream(url: string): Vessel[] {
  const [vessels, setVessels] = useState<Vessel[]>([]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(url);
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as Vessel[];
          setVessels(data);
        } catch {
          // ignore malformed frame
        }
      };
      socket.onclose = () => {
        if (!cancelled) setTimeout(connect, 2000);
      };
      socket.onerror = () => socket?.close();
    }

    connect();
    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [url]);

  return vessels;
}
```

- [ ] **Step 2: Write `frontend/components/MapDeck.tsx`**

```tsx
// frontend/components/MapDeck.tsx
"use client";

import DeckGL from "@deck.gl/react";
import { ScatterplotLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMemo, useRef, useEffect } from "react";
import type { Vessel } from "@/lib/types";

const MAPLIBRE_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

const HORMUZ_VIEW = {
  longitude: 56.25,
  latitude: 26.3,
  zoom: 7,
  pitch: 0,
  bearing: 0,
};

export default function MapDeck({ vessels }: { vessels: Vessel[] }) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    mapRef.current = new maplibregl.Map({
      container: mapContainer.current,
      style: MAPLIBRE_STYLE,
      center: [HORMUZ_VIEW.longitude, HORMUZ_VIEW.latitude],
      zoom: HORMUZ_VIEW.zoom,
      interactive: false,
    });
    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  const layers = useMemo(
    () => [
      new ScatterplotLayer<Vessel>({
        id: "vessels",
        data: vessels,
        getPosition: (v) => [v.lon, v.lat],
        getRadius: 400,
        getFillColor: (v) => (v.signal_lost ? [255, 140, 0, 200] : [0, 200, 255, 200]),
        pickable: true,
      }),
    ],
    [vessels]
  );

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={mapContainer} style={{ position: "absolute", inset: 0 }} />
      <DeckGL
        viewState={HORMUZ_VIEW}
        controller={false}
        layers={layers}
        style={{ position: "absolute", inset: 0 }}
      />
    </div>
  );
}
```

- [ ] **Step 3: Write a placeholder `frontend/app/page.tsx` (Task 13 replaces this with the full layout)**

```tsx
// frontend/app/page.tsx
"use client";

import MapDeck from "@/components/MapDeck";
import { useVesselStream } from "@/lib/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/vessels";

export default function Page() {
  const vessels = useVesselStream(WS_URL);

  return (
    <main style={{ width: "100vw", height: "100vh" }}>
      <MapDeck vessels={vessels} />
    </main>
  );
}
```

- [ ] **Step 4: Manual verification**

Run: `cd backend && uvicorn app.main:app --reload` (in one terminal, with a real `AISSTREAM_API_KEY` in `backend/.env`)
Run: `cd frontend && npm run dev` (in another terminal)
Expected: open `http://localhost:3000` — the Hormuz map renders and vessel dots appear within a few seconds as AIS messages arrive. (No automated test here: this step needs a live WebSocket + a real API key, which is exactly the "real live data on stage" requirement — automate later with Playwright if time allows, not part of Phase 1 spine.)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/ws.ts frontend/components/MapDeck.tsx frontend/app/page.tsx
git commit -m "feat(frontend): live vessel layer via deck.gl + MapLibre over /ws/vessels"
```

---

### Task 12: Risk panel — live corridor risk %

**Files:**
- Create: `frontend/components/RiskPanel.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `RiskScore` type (Task 10), `GET /risk/hormuz` (Task 9).
- Produces: `<RiskPanel apiUrl={string} />`. Task 13's final `page.tsx` renders it alongside `MapDeck`.

- [ ] **Step 1: Write `frontend/components/RiskPanel.tsx`**

```tsx
// frontend/components/RiskPanel.tsx
"use client";

import { useEffect, useState } from "react";
import type { RiskScore } from "@/lib/types";

const FEATURE_LABELS: Record<string, string> = {
  kinetic: "Kinetic news (GDELT)",
  density: "Vessel density anomaly (AIS)",
  sanctions: "Sanctions exposure — STUB",
  weather: "Sea state — STUB",
  freight: "Freight stress — STUB",
};

export default function RiskPanel({ apiUrl }: { apiUrl: string }) {
  const [risk, setRisk] = useState<RiskScore | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const resp = await fetch(`${apiUrl}/risk/hormuz`);
        if (resp.ok && !cancelled) {
          setRisk(await resp.json());
        }
      } catch {
        // network hiccup, retry on next tick
      }
    }
    poll();
    const interval = setInterval(poll, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [apiUrl]);

  if (!risk) {
    return <div className="panel">Loading corridor risk…</div>;
  }

  return (
    <div className="panel">
      <h2>Strait of Hormuz — Disruption Probability</h2>
      <div style={{ fontSize: "2.5rem", fontWeight: 700 }}>{(risk.probability * 100).toFixed(1)}%</div>
      <div style={{ marginTop: 12 }}>
        {Object.entries(risk.contributions).map(([feature, contribution]) => (
          <div key={feature} style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 12, opacity: 0.8 }}>{FEATURE_LABELS[feature] ?? feature}</div>
            <div style={{ background: "#1c2330", borderRadius: 4, overflow: "hidden", height: 8 }}>
              <div
                style={{
                  width: `${Math.min(contribution / risk.weights[feature], 1) * 100}%`,
                  background: "#00c8ff",
                  height: "100%",
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Run: `cd backend && uvicorn app.main:app --reload` and `cd frontend && npm run dev`
Expected: `curl http://localhost:8000/risk/hormuz` returns a JSON `RiskScore`; once `<RiskPanel apiUrl="http://localhost:8000" />` is added to a page it shows a live percentage that changes as GDELT/vessel data changes.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/RiskPanel.tsx
git commit -m "feat(frontend): risk panel with live corridor probability and feature contribution bars"
```

---

### Task 13: Hardcoded Scenario + Reroute cards, and final page layout

**Files:**
- Create: `frontend/components/ScenarioCard.tsx`
- Create: `frontend/components/RerouteCard.tsx`
- Modify: `frontend/app/page.tsx` (final layout: map + risk panel + scenario + reroute)

**Interfaces:**
- Consumes: `Scenario`, `RerouteOption` types (Task 10) — data is hardcoded in Phase 1, but shaped exactly like the backend contract so Phase 2 only needs to swap a fetch call in.
- Produces: final Phase 1 `page.tsx`, assembling every component built so far.

- [ ] **Step 1: Write `frontend/components/ScenarioCard.tsx`**

```tsx
// frontend/components/ScenarioCard.tsx
"use client";

import type { Scenario } from "@/lib/types";

// HARDCODED — proves the UI pipe end to end. Phase 2 replaces this with a live
// POST to a /scenario endpoint driven by slider state (see docs/04 §B).
const HARDCODED_SCENARIO: Scenario = {
  corridor: "hormuz",
  disruption_factor: 0.3,
  substitution_rate: 0.2,
  hormuz_share: 0.45,
  india_imports_mbd: 4.7,
  supply_gap_mbd: 0.51,
  utilization_drop_pct: 0.06,
  spr_fill_pct: 0.64,
  days_cover_remaining: 9.5,
  cpi_sensitivity: 0.35,
  cpi_delta_pp: 0.24,
  gdp_drag_bps: 8.1,
  cad_sensitivity: 0.35,
  cad_widening_pct_gdp: 0.17,
};

export default function ScenarioCard() {
  const s = HARDCODED_SCENARIO;
  return (
    <div className="panel">
      <h2>Scenario — 30% disruption (hardcoded, Phase 2 wires sliders)</h2>
      <ul style={{ listStyle: "none", padding: 0, fontSize: 14, lineHeight: 1.8 }}>
        <li>Supply gap: {s.supply_gap_mbd.toFixed(2)} mb/d</li>
        <li>Refinery utilization drop: {(s.utilization_drop_pct * 100).toFixed(1)}%</li>
        <li>SPR + commercial days cover: {s.days_cover_remaining.toFixed(1)} days</li>
        <li>CPI impact: +{s.cpi_delta_pp.toFixed(2)} pp</li>
        <li>GDP drag: {s.gdp_drag_bps.toFixed(1)} bps</li>
        <li>CAD widening: {(s.cad_widening_pct_gdp * 100).toFixed(2)}% of GDP</li>
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Write `frontend/components/RerouteCard.tsx`**

```tsx
// frontend/components/RerouteCard.tsx
"use client";

import type { RerouteOption } from "@/lib/types";

// HARDCODED — proves the UI pipe end to end. Phase 2 replaces this with a live
// GET /reroute/{corridor} ranked by the MCDM engine (docs/04 §C).
const HARDCODED_REROUTES: RerouteOption[] = [
  {
    source_grade: "Urals",
    origin: "Russia",
    api_gravity: 31.0,
    sulfur_pct: 1.3,
    landed_cost_usd_bbl: 78.5,
    voyage_days: 25,
    grade_match: 1.0,
    congestion_penalty: 0.1,
    score: 0.81,
    best_fit_refineries: ["RIL Jamnagar", "Nayara Vadinar"],
  },
  {
    source_grade: "Bonny Light",
    origin: "W. Africa",
    api_gravity: 35.0,
    sulfur_pct: 0.2,
    landed_cost_usd_bbl: 84.0,
    voyage_days: 27,
    grade_match: 1.0,
    congestion_penalty: 0.15,
    score: 0.74,
    best_fit_refineries: ["PSU refiners"],
  },
  {
    source_grade: "Merey",
    origin: "Venezuela",
    api_gravity: 16.0,
    sulfur_pct: 2.5,
    landed_cost_usd_bbl: 61.0,
    voyage_days: 47,
    grade_match: 0.0,
    congestion_penalty: 0.2,
    score: 0.22,
    best_fit_refineries: ["RIL Jamnagar (coking only)"],
  },
];

export default function RerouteCard() {
  return (
    <div className="panel">
      <h2>Ranked reroute options (hardcoded, Phase 2 wires the MCDM engine)</h2>
      <ol style={{ paddingLeft: 18, fontSize: 14 }}>
        {HARDCODED_REROUTES.map((r) => (
          <li key={r.source_grade} style={{ marginBottom: 10 }}>
            <strong>
              {r.source_grade} ({r.origin})
            </strong>{" "}
            — score {r.score.toFixed(2)}
            <div style={{ opacity: 0.8 }}>
              ${r.landed_cost_usd_bbl}/bbl · {r.voyage_days}d voyage · grade_match {r.grade_match} ·{" "}
              {r.best_fit_refineries.join(", ")}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite `frontend/app/page.tsx` with the full Phase 1 layout**

```tsx
// frontend/app/page.tsx
"use client";

import MapDeck from "@/components/MapDeck";
import RiskPanel from "@/components/RiskPanel";
import ScenarioCard from "@/components/ScenarioCard";
import RerouteCard from "@/components/RerouteCard";
import { useVesselStream } from "@/lib/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/vessels";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Page() {
  const vessels = useVesselStream(WS_URL);

  return (
    <main style={{ display: "grid", gridTemplateColumns: "1fr 380px", width: "100vw", height: "100vh" }}>
      <MapDeck vessels={vessels} />
      <aside style={{ overflowY: "auto", padding: 16, background: "#0f131c" }}>
        <RiskPanel apiUrl={API_URL} />
        <ScenarioCard />
        <RerouteCard />
      </aside>
    </main>
  );
}
```

- [ ] **Step 4: Add minimal panel styling to `frontend/app/globals.css`**

```css
.panel {
  background: #141a24;
  border: 1px solid #232b3a;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.panel h2 {
  font-size: 15px;
  margin: 0 0 12px 0;
  font-weight: 600;
  opacity: 0.9;
}
```

- [ ] **Step 5: Manual verification**

Run: `cd frontend && npm run build`
Expected: build succeeds with no type errors
Run: `cd backend && uvicorn app.main:app --reload` + `cd frontend && npm run dev`, open `http://localhost:3000`
Expected: map with live vessels on the left; risk %, hardcoded scenario, and hardcoded reroute list on the right — the full P1 exit test.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/ScenarioCard.tsx frontend/components/RerouteCard.tsx frontend/app/page.tsx frontend/app/globals.css
git commit -m "feat(frontend): assemble Phase 1 layout with hardcoded scenario and reroute cards"
```

---

### Task 14: docker-compose + Dockerfiles

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: `backend/requirements.txt` (Task 1), `frontend/package.json` (Task 10).
- Produces: `docker compose up --build` running `api` on 8000 and `web` on 3000, matching `README.md`'s Quickstart exactly.

- [ ] **Step 1: Write `backend/Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `frontend/Dockerfile`**

```dockerfile
FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - backend/.env
    restart: unless-stopped

  web:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
      NEXT_PUBLIC_WS_URL: ws://localhost:8000/ws/vessels
    depends_on:
      - api
    restart: unless-stopped
```

- [ ] **Step 4: Manual verification**

Run: `docker compose up --build` from repo root (with `backend/.env` populated with a real `AISSTREAM_API_KEY`)
Expected: both containers start; `http://localhost:8000/health` returns `{"status":"ok"}`; `http://localhost:3000` shows the live map.

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile docker-compose.yml
git commit -m "feat: docker-compose for api + web, one-command Phase 1 run"
```

---

### Task 15: Docs sync (non-negotiable per `CLAUDE.md`)

**Files:**
- Modify: `docs/03_build_plan_and_deliverables.md`
- Modify: `docs/02_data_sources_and_schemas.md`
- Modify: `docs/04_model_assumptions_and_constants.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing — this is a documentation-only reconciliation task, run last so it reflects the actual code from Tasks 1–14.

- [ ] **Step 1: Update `docs/03_build_plan_and_deliverables.md`**

Change status column: `FastAPI skeleton + /health + typed Pydantic models` ⬜→✅; `AISStream WS client + dead-reckoning + /ws/vessels relay` ⬜→✅; `GDELT connector (TimelineVol, corridor bbox)` ⬜→✅; `Risk engine (sigmoid + weighted features + per-feature breakdown)` ⬜→🟨 (kinetic + density live, sanctions/weather/freight stubbed at 0 pending Phase 2); `Next.js + deck.gl + MapLibre base` ⬜→✅; `Live vessel layer (Scatterplot + Path + Trips dead-reckoning)` ⬜→🟨 (Scatterplot done; Path/Trips interpolation is Phase 2 polish); `Risk panel w/ stacked feature-contribution bar` ⬜→✅; `Reroute ranked-list card (executable plan)` ⬜→🟨 (hardcoded, not yet MCDM-driven); `docker-compose (api, web, chroma, redis)` ⬜→🟨 (api+web done; chroma/redis land with Phase 2/3 RAG + caching).

- [ ] **Step 2: Update `docs/02_data_sources_and_schemas.md`**

Under §10 feed→feature map, add an implementation note under `X_density`: "Phase 1 substitutes a short in-memory rolling window (`DensityTracker`, `backend/app/ingestion/density.py`) for the 30-day MA baseline — a live demo can't accumulate 30 days of history. `ASSUMPTION`, revisit if a persistent store is added." Add a note under GDELT (§3) confirming the exact query implemented in `backend/app/ingestion/gdelt.py` matches the documented query/timespan/bbox.

- [ ] **Step 3: Update `docs/04_model_assumptions_and_constants.md`**

Under §A, add: "Phase 1 implementation status: `X_kinetic` and `X_density` are live; `X_sanctions`, `X_weather`, `X_freight` are `STUB → 0.0` pending Phase 2 connectors (OpenSanctions, Open-Meteo, FRED respectively). See `backend/app/engine/risk.py`." Add a line noting the `X_density` 30-day-MA substitution (cross-reference the note added in Step 2).

- [ ] **Step 4: Verify `README.md` still matches reality**

Confirm the "Repo structure", "Quickstart", and service URL table already match what Tasks 1–14 built (they do — README was written ahead of the code as the spec for §6 of `CLAUDE.md`). No changes expected here unless a deviation was made during implementation; if so, update the relevant section.

- [ ] **Step 5: Commit**

```bash
git add docs/03_build_plan_and_deliverables.md docs/02_data_sources_and_schemas.md docs/04_model_assumptions_and_constants.md README.md
git commit -m "docs: sync tracker, data-source notes, and assumptions with Phase 1 implementation"
```

---

## Self-Review Notes

- **Spec coverage:** every P1 bullet in `CLAUDE.md` §4/§8 and `docs/03`'s "Backend"/"Frontend"/"Packaging" rows relevant to Phase 1 maps to a task above (Tasks 1–2 FastAPI+Pydantic, 3–5 AIS+dead-reckoning+relay, 6 GDELT, 7–9 risk engine wired live, 10–13 frontend spine incl. hardcoded scenario/reroute, 14 compose, 15 docs sync — the non-negotiable CLAUDE.md docs-update rule).
- **Deferred to Phase 2 explicitly (not silently dropped):** EIA/Alpha Vantage/Open-Meteo/FRED/OpenSanctions connectors, scenario cascade engine, reroute MCDM engine, LangGraph agents, Chroma RAG, corridor risk polygons, Path/Trips dead-reckoning interpolation, chroma/redis in compose. These are Phase 2/3 per `docs/03`'s own tracker and the cut-list — correctly out of scope for "the spine."
- **Type consistency check:** `Vessel`/`RiskScore`/`Scenario`/`RerouteOption` field names in `backend/app/models.py` (Task 1) match `frontend/lib/types.ts` (Task 10) match the hardcoded data in Task 13 match the assertions in Task 9's test — verified field-by-field while writing.
