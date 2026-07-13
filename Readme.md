# Lodestar

**An anticipatory decision tool for import-dependent energy security — built on live public data, not mockups.**

Lodestar ingests **live** maritime (AIS), commodity-price, and geopolitical signals; scores disruption probability per shipping corridor with a transparent, explainable model; simulates disruption scenarios with **assumptions you can see and adjust**; and generates a ranked, executable crude-procurement **rerouting plan** — all on a live geospatial map.

Built for the **ET AI Hackathon 2.0 · Problem Statement 2** (AI-Driven Energy Supply Chain Resilience for Import-Dependent Economies). The spine is **Strait of Hormuz × India**.

> Lodestar is a **decision tool**, not a dashboard. It watches signals continuously, quantifies risk with visible assumptions, and hands a procurement team a defensible course of action in minutes.

---

## Why it's defensible

- **Real data, live.** The demo runs on genuinely live, free public feeds — real tankers in the Strait of Hormuz, real Brent/WTI prices, real news volume. Where a real-time feed doesn't exist, the source is a cited static constant, clearly marked.
- **Every number traces to something.** Each figure on screen maps to a source or a stated, adjustable assumption. Nothing is hidden.
- **Deterministic engines, not a black box.** The risk, scenario, and reroute math is deterministic and auditable. The multi-agent layer reasons about and narrates the outputs — it never replaces the math. Policymakers need auditability.

---

## What it does (the spine)

```
Live Hormuz AIS  →  corridor risk score (explainable)  →  macro cascade (visible sliders)
    →  ranked executable reroute plan  →  on the map  →  signal→recommendation latency badge
```

- **Live vessel tracking** in the Hormuz bounding box, with dead-reckoning for stale/dark transponders (flagged, not hidden).
- **Explainable corridor risk** with a per-feature contribution breakdown.
- **Scenario cascade** — a 5-step macroeconomic what-if with every assumption exposed as an adjustable slider.
- **Constrained rerouting** — recommendations bounded by crude-grade/refinery compatibility (API gravity + sulfur), not just distance.

---

## Architecture

Live feeds are consumed by specialized agents — Market Intelligence and Logistics & Maritime run concurrently (a real LangGraph parallel fan-out; neither reads the other's output), then Macroeconomic Strategist and Executive Orchestrator run sequentially after, synthesizing both branches' output — which call **deterministic engines** to do the math. FastAPI streams a **typed payload** over WebSocket to a deck.gl + MapLibre frontend.

```
feeds → Market Intelligence + Logistics & Maritime (parallel) → Macroeconomic Strategist → Executive Orchestrator (synthesis + narration, LLM via NVIDIA NIM)
      → FastAPI + /ws relay (typed payloads)
      → Next.js · deck.gl · MapLibre (vessels · risk polygons · sliders · reroute card · latency badge)
```

The full architecture diagram is in `docs/` and the submission deck.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python · FastAPI · WebSockets |
| Agent orchestration | LangGraph (Market · Logistics · Macro · Orchestrator) |
| RAG | Cut Phase 3 — corpus never materialized (docs/04 §G); policy facts kept inline in agent prompts instead |
| Frontend | Next.js · deck.gl · MapLibre (free tiles, **no Mapbox token**) · Recharts |
| Packaging | Docker · docker-compose (api · web · redis; chroma cut, never landed — docs/04 §G) |

---

## Live data sources (all free-tier)

| Source | Signal | Key required |
|---|---|---|
| **AISStream** | Live AIS vessel positions (WebSocket) | Yes |
| **GDELT 2.0 DOC** | Geopolitical / kinetic news volume | No |
| **EIA API v2** | Brent/WTI spot baseline, fundamentals | Yes |
| **Alpha Vantage** | Intraday crude quotes (cached — 25 req/day cap) | Yes |
| **OpenSanctions** | Vessel / entity sanctions screening | Yes |
| **Open-Meteo Marine** | Sea state (wave height) on routes | No |
| **FRED** | Freight / shipping-stress proxy indices | Yes |

Full endpoints, auth, rate limits, and gotchas are documented in `docs/02_data_sources_and_schemas.md`.

---

## The three engines

1. **Risk** — sigmoid + weighted features returning a per-feature contribution breakdown (drives the explainability bar).
2. **Scenario cascade** — 5 steps, every assumption exposed as an adjustable parameter.
3. **Reroute (MCDM)** — multi-criteria ranking constrained by a crude-grade compatibility matrix (a hard input, not a tiebreaker).

All constants, weights, and assumptions live in `docs/04_model_assumptions_and_constants.md`.

---

## Quickstart

### Prerequisites

- Docker + Docker Compose
- An AISStream API key (free-tier) — this is the only key Phase 1 actually calls. GDELT needs no key. EIA and Alpha Vantage are now wired backend-side (`PriceService`, live via `GET /scenario/{corridor}` and `GET /reroute/{corridor}`) but optional — the app runs fully without them, falling back to a static Brent baseline (`BRENT_FALLBACK_USD_BBL`). OpenSanctions is now wired live (Phase 3, vessel screening in risk + Logistics agent node); FRED key is optional. NVIDIA_API_KEY enables agent narration via NVIDIA NIM (Phase 3, `GET /recommendation/{corridor}`); narration stubs if unset.

### 1. Configure environment

```bash
cp backend/.env.example backend/.env
# then fill in your keys:
```

```
AISSTREAM_API_KEY=
EIA_API_KEY=
ALPHAVANTAGE_API_KEY=
OPENSANCTIONS_API_KEY=
FRED_API_KEY=
NVIDIA_API_KEY=
LLM_MODEL=nvidia/llama-3.1-nemotron-70b-instruct
AGENT_MODE=graph
# GDELT and Open-Meteo need no key
```

> Never commit `backend/.env`. It is gitignored.

### 2. Run everything (one command)

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend (map) | http://localhost:3000 |
| API | http://localhost:8000 |
| Health check | http://localhost:8000/health |
| Vessel stream | ws://localhost:8000/ws/vessels |
| Corridor risk | http://localhost:8000/risk/hormuz |
| AIS coverage state | http://localhost:8000/coverage |
| Scenario cascade | http://localhost:8000/scenario/hormuz |
| Reroute ranking | http://localhost:8000/reroute/hormuz |
| Agent recommendation | http://localhost:8000/recommendation/hormuz |

Open **http://localhost:3000**: the map opens on the Strait of Hormuz with a live corridor risk percentage. **AISStream has no terrestrial receivers in the Persian Gulf or on the India west coast** (empirically verified — see "AIS coverage reality" in `docs/03`), so the Hormuz frame shows no vessel dots and the risk panel's density feature honestly badges "AIS: no terrestrial coverage in corridor". Pan/zoom the map southeast to the **Singapore Strait** (the live subscribed box inside the Malacca corridor) to see real vessels streaming. `GET /coverage` shows the per-box coverage state.

---

## Repo structure

```
lodestar/
  backend/
    app/
      main.py            # FastAPI app, /health, mounts /ws
      config.py          # env keys, corridor constants
      models.py          # Pydantic: Vessel, RiskScore, Scenario, RerouteOption, AgentRecommendation
      ingestion/         # aisstream.py, dead_reckoning.py, density.py, gdelt.py (Phase 1); prices.py (EIA + Alpha Vantage, Phase 2); weather.py (Open-Meteo Marine, Phase 2); freight.py (FRED, Phase 2); sanctions.py (OpenSanctions, Phase 3, live -- wired into GET /risk/{corridor})
      engine/            # risk.py (Phase 1); scenario.py, reroute.py (Phase 2, wired live via /scenario and /reroute)
      agents/            # graph.py (LangGraph, default) + sequential.py (fallback) + market/logistics/macro/orchestrator nodes + llm_client.py (NVIDIA NIM)
      rag/               # cut Phase 3 -- no corpus (docs/04 §G); not present
      api/               # routes.py, ws.py
    data/                # corridors.json, ais_boxes.json (AIS multi-box subscription config); crude_grades.json (Phase 2, Task 3); refineries.json, spr.json still pending (teammate-owned)
    tests/               # conftest.py + test_*.py (health, models, aisstream, coverage, dead_reckoning, density, gdelt, risk, routes, ws_vessels)
    requirements.txt  Dockerfile  .dockerignore  .env.example  pytest.ini
  scripts/               # committed diagnostics: diag_aisstream.py (subscription matrix), diag_relay.py (/ws/vessels end-to-end check)
  frontend/
    app/                 # page.tsx, layout.tsx
    components/          # MapDeck, RiskPanel, ScenarioCard, RerouteCard (ScenarioCard/RerouteCard now live-wired to /scenario and /reroute, Tasks 6-8; LatencyBadge still not yet built, Phase 3)
    lib/                 # types.ts, ws.ts
    package.json  Dockerfile  .dockerignore
  docs/                  # 01 strategy · 02 data sources · 03 build plan · 04 assumptions
  docker-compose.yml     # api · web (Phase 1); redis landed (Phase 2, caching); chroma cut -- never landed (docs/04 §G)
  README.md
```

---

## AIS pipeline observability (hop-by-hop logging)

The AIS data path from source to map has five hops, each instrumented with diagnostic logging:

| Hop | Where | Log tag | What it proves |
|-----|-------|---------|----------------|
| **(a)** Socket open | `aisstream.py` → `run()` | `[AIS hop-a]` | WebSocket connected to AISStream |
| **(b)** Subscription sent | `aisstream.py` → `_consume()` | `[AIS hop-b]` | Correct payload (masked key, bbox) sent within 3s |
| | | `[AIS hop-b-raw]` | Full, unmasked subscribe JSON actually written to the socket (post-`ws.send`) |
| **(c)** Positions received | `aisstream.py` → `_consume()` loop | `[AIS hop-c]` | First vessel logged loudly; every 50th summarized |
| | | `[AIS hop-c-raw]` | Raw frame (type + first 500 chars) logged **before** MessageType filtering — unconditionally for the first 20 messages after connect, and for any non-`PositionReport` message for the life of the connection |
| | | `[AIS hop-c-error]` | Full `traceback.format_exc()` for any exception parsing/handling a single message; the receive loop logs and continues instead of dying |
| **(d)** Relay broadcast | `ws.py` → `ws_vessels()` | `[WS hop-d]` | Vessel count per broadcast to each frontend client |
| **(e)** Frontend received | `ws.ts` → `useVesselStream()` | `[WS hop-e]` | Browser console: first message + periodic counts |
| Task lifecycle | `main.py` → `_log_task_result()` | `[AIS-TASK]` | Fires when the AIS task exits (exception, cancel, or clean) |

**To diagnose a dead pipeline:** check `docker compose logs api` for hops a–d. If hop-a never appears, the container can’t reach AISStream. If hop-b appears but `[AIS hop-c-raw]` never does, the server isn’t sending anything (bad key, empty bbox, or the connection was silently dropped). If `[AIS hop-c-error]` fires repeatedly, a schema mismatch is breaking parsing — read the traceback. If `[AIS-TASK]` logs an exception, the background task died. Open browser DevTools console for hop-e.

**`BoundingBoxes` schema (confirmed):** AISStream requires triple nesting — a list of **one or more** boxes, each box being a list of exactly **two** `[lat, lon]` points: `[[[lat_min, lon_min], [lat_max, lon_max]], ...]`. The `[lat, lon]` point order was verified empirically (2026-07-05 diagnostic matrix: Dover in lat-lon streams instantly, axes-swapped gets nothing). `AISStreamClient._subscribe_payload()` asserts this shape and raises loudly before sending if it's ever malformed. The subscription is **multi-box** — all boxes in `backend/data/ais_boxes.json` go into one subscribe message, and every incoming frame is attributed to its containing box(es) in the per-box `CoverageMonitor` (`[AIS hop-b]` logs carry a `SENTINEL-MULTIBOX-20260705` image-freshness marker).

**AIS coverage states:** a subscribed box with zero frames for a rolling window reports `NO_TERRESTRIAL_COVERAGE` via `GET /coverage`; a corridor risk feature backed by an uncovered box is excluded from the risk sum (weights renormalized) and badged in the UI instead of reading a fake zero. This is by design: as of 2026-07-05 AISStream has **no receivers in the Persian Gulf or on the India west coast** (see the full evidence in `docs/03`). Diagnostic scripts: `scripts/diag_aisstream.py` (subscription matrix, app must be down — single-session key) and `scripts/diag_relay.py`.

### Phase 1 AIS Evidence (Live Feed Status)

A core design principle of Lodestar is transparency around data limitations. AISStream's terrestrial-receiver model has a real, documented coverage gap in the Persian Gulf and along India's own coast. Rather than silently reporting zero vessels (which a black-box model might misinterpret as "no disruption" or "zero traffic"), Lodestar is architected to explicitly distinguish "no disruption detected" from "no visibility available." This is a critical, resilience-relevant distinction.

When a coverage gap is detected, the density feature is explicitly flagged as `NO_TERRESTRIAL_COVERAGE`, clearly badged in the UI, and excluded from the math (weights renormalized) so it does not poison the risk score.

To defend the platform's integrity on demo day and prove the pipeline is alive despite these gaps, we ran a controlled diagnostic matrix on the live feed:

| Corridor / Region | Status | Evidence | Action |
|---|---|---|---|
| **Strait of Hormuz** | 🔴 `NO_TERRESTRIAL_COVERAGE` | 0 frames in 120s | Excluded from risk density math; badged in UI. System correctly identifies sensor gap. |
| **India West Coast** | 🔴 `NO_TERRESTRIAL_COVERAGE` | 0 frames in 180s (no filter) | Confirms coverage void. Excluded from math; badged in UI. |
| **Singapore Strait (Malacca)** | 🟢 `COVERED` | 44+ frames instantly | Secondary demo view to prove the pipeline is live and rendering moving vessels. |
| **Dover Strait (Control)** | 🟢 `COVERED` | 50+ frames instantly | Positive control to verify the backend connector is perfectly healthy. |

The AIS background task is pinned to `app.state.ais_task` (preventing GC) and has a `done_callback` that logs any unhandled exception. The receive loop wraps each message in try/except so one bad message cannot kill the entire loop.

The backend also logs a `[STARTUP]` line with the masked API key and corridor bbox on boot — verify this first.

---

## Model assumptions & limitations (read this)

Lodestar's scenario engine is a **transparent, assumption-driven what-if tool** — not a claim of predictive accuracy. Every assumption is exposed and adjustable in the UI, and enumerated in `docs/04_model_assumptions_and_constants.md`.

Known constraints, handled explicitly:

- **AIS coverage** — terrestrial receivers reach ~15–20 nm offshore; deep-ocean and "dark fleet" vessels drop out. Stale positions (>2h) are dead-reckoned and flagged `signal_lost`, never silently dropped. **Regional coverage voids are handled explicitly:** AISStream has no receivers in the Persian Gulf / India west coast (verified 2026-07-05, `docs/03`), so those boxes report `NO_TERRESTRIAL_COVERAGE` and the density risk feature is excluded (weights renormalized) rather than reading a fake zero.
- **AIS task lifecycle** — the background task is pinned to `app.state.ais_task` (prevents GC) with a done-callback that logs any unhandled exception. The receive loop wraps each message in try/except so a single bad message cannot kill ingestion.
- **API key guard** — if `AISSTREAM_API_KEY` is empty, the backend logs a loud `[STARTUP] ✗` error and the AIS client refuses to connect (instead of silently retrying forever).
- **Price latency** — EIA spot prices publish weekly; intraday precision falls back to (cached) Alpha Vantage.
- **Chokepoint throughput** — not a live API; treated as a cited config constant, not a feed.
- **GDELT rate limits** — GDELT enforces ~1 req/5s; the connector uses a 120s TTL in-memory cache and respects `Retry-After` headers on 429 responses, serving the last good cached value while rate-limited.
- **GDELT window** — only the most recent 90 days are queryable.
- **Reroute landed cost** — includes an illustrative price differential + freight-per-day proxy (not a live feed), labeled `ASSUMPTION`/`STUB` in `crude_grades.json` and `reroute.py`.
- **Freight-stress feature (`X_freight`)** — uses FRED's deep-sea freight PPI (`WPU301301`) as a live substitute for BCTI/BDI, which are not available on FRED (verified 2026-07-10) — labeled in `docs/02` §7 and `freight.py`.

---

## Acknowledgments

Authoritative reference sources include PPAC, EIA, IEA, and RBI. Public feeds courtesy of AISStream, GDELT, EIA, Alpha Vantage, OpenSanctions, Open-Meteo, and FRED.

*Built for the ET AI Hackathon 2.0 (PS2).*