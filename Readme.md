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

Live feeds are consumed by specialized agents (running in parallel), which call **deterministic engines** to do the math. An orchestrator synthesizes the result and FastAPI streams a **typed payload** over WebSocket to a deck.gl + MapLibre frontend.

```
feeds → specialized agents (parallel) → deterministic engines (math)
      → orchestrator (synthesis + policy citations via RAG)
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
| RAG | Chroma over public policy/geopolitics documents |
| Frontend | Next.js · deck.gl · MapLibre (free tiles, **no Mapbox token**) · Recharts |
| Packaging | Docker · docker-compose (api · web now; chroma · redis land with Phase 2/3 RAG + caching) |

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
- An AISStream API key (free-tier) — this is the only key Phase 1 actually calls. GDELT needs no key. EIA, Alpha Vantage, OpenSanctions, and FRED keys are accepted in `.env` but their connectors are Phase 2 work not yet wired; the app runs fully without them (those risk features are `STUB → 0.0`).

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

Open **http://localhost:3000** and you should see live tankers moving in the Strait of Hormuz with a live corridor risk percentage.

---

## Repo structure

```
lodestar/
  backend/
    app/
      main.py            # FastAPI app, /health, mounts /ws
      config.py          # env keys, corridor constants
      models.py          # Pydantic: Vessel, RiskScore, Scenario, RerouteOption
      ingestion/         # aisstream.py, dead_reckoning.py, density.py, gdelt.py (Phase 1); eia, alphavantage, openmeteo, fred, sanctions land with Phase 2
      engine/            # risk.py (Phase 1); scenario.py, reroute.py land with Phase 2
      agents/            # Phase 3: graph.py + market/logistics/macro/orchestrator (not yet present)
      rag/               # Phase 3: store.py, ingest.py (not yet present)
      api/               # routes.py, ws.py
    data/                # corridors.json (Phase 1); refineries.json, spr.json, crude_grades.json land with Phase 2
    tests/               # conftest.py + test_*.py (Phase 1: health, models, aisstream, dead_reckoning, density, gdelt, risk, routes, ws_vessels)
    requirements.txt  Dockerfile  .dockerignore  .env.example  pytest.ini
  frontend/
    app/                 # page.tsx, layout.tsx
    components/          # MapDeck, RiskPanel, ScenarioCard, RerouteCard (Phase 1: hardcoded scenario/reroute; ScenarioSliders/LatencyBadge are Phase 2/3)
    lib/                 # types.ts, ws.ts
    package.json  Dockerfile  .dockerignore
  docs/                  # 01 strategy · 02 data sources · 03 build plan · 04 assumptions
  docker-compose.yml     # api · web (Phase 1); chroma · redis land with Phase 2/3
  README.md
```

---

## Model assumptions & limitations (read this)

Lodestar's scenario engine is a **transparent, assumption-driven what-if tool** — not a claim of predictive accuracy. Every assumption is exposed and adjustable in the UI, and enumerated in `docs/04_model_assumptions_and_constants.md`.

Known constraints, handled explicitly:

- **AIS coverage** — terrestrial receivers reach ~15–20 nm offshore; deep-ocean and "dark fleet" vessels drop out. Stale positions (>2h) are dead-reckoned and flagged `signal_lost`, never silently dropped.
- **Price latency** — EIA spot prices publish weekly; intraday precision falls back to (cached) Alpha Vantage.
- **Chokepoint throughput** — not a live API; treated as a cited config constant, not a feed.
- **GDELT window** — only the most recent 90 days are queryable.

---

## Acknowledgments

Authoritative reference sources include PPAC, EIA, IEA, and RBI. Public feeds courtesy of AISStream, GDELT, EIA, Alpha Vantage, OpenSanctions, Open-Meteo, and FRED.

*Built for the ET AI Hackathon 2.0 (PS2).*