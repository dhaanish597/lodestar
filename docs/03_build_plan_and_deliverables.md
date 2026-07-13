# 03 — Build Plan & Deliverables (living tracker)

> Update the status column as we go. Full rationale, architecture, and delegation live in the HTML build plan. Legend: ⬜ todo · 🟨 in progress · ✅ done · ✂️ cut.

## Submission artifacts (the 4 things judged)
| # | Artifact | Format | Owner | Status |
|---|---|---|---|---|
| 1 | Working prototype | Public GitHub + one-command run | You | ⬜ |
| 2 | Detailed document | PDF | Teammate (writing) | ⬜ |
| 3 | Demo video | MP4/MKV <50MB or Drive link, 3–4 min | Teammate (media) | ⬜ |
| 4 | Architecture diagram | In doc + deck | Teammate (from SVG) | ⬜ |

## The spine (must run live on stage)
Real Hormuz AIS → corridor risk score (explainable) → macro cascade (visible sliders) → ranked executable reroute plan → on the map → signal→recommendation latency badge.

## AIS coverage reality (empirical, 2026-07-05) — why the multi-box design exists

AISStream is a volunteer terrestrial-receiver network (~15–20 nm line-of-sight). We ran a controlled
diagnostic matrix (`scripts/diag_aisstream.py`, app fully down, strictly sequential single-session runs)
to separate two hypotheses for zero Hormuz frames: H1 "the subscription silently expects a different
coordinate order" vs H2 "there are no receivers feeding the region". Raw results:

| Case | Box | Order | Filter | Duration | Frames | First frame |
|---|---|---|---|---|---|---|
| A | Worldwide `[[-90,-180],[90,180]]` | — | PositionReport | 30s (early-stop 100) | **100** | t=0.0s |
| B | Dover Strait `[[50.5,0.5],[51.5,2.0]]` | lat-lon | PositionReport | 120s | **39** | t=0.0s |
| C | Dover Strait, axes swapped | lon-lat | PositionReport | 120s | 0 | — |
| D | Hormuz `[[25.2732,55.1647],[27.3713,57.3419]]` | lat-lon | PositionReport | 120s | 0 | — |
| E | Hormuz, axes swapped | lon-lat | PositionReport | 120s | 0 | — |
| F | Entire Gulf + Gulf of Oman `[[20,48],[30,65]]` | lat-lon | **none** | 180s | 0 | — |
| G | India west coast `[[19.5,68.5],[23.5,73.0]]` | lat-lon | **none** | 180s | 0 | — |
| H | Singapore Strait `[[1.0,103.3],[1.6,104.4]]` | lat-lon | PositionReport | 120s | **11** | t=0.0s |

**Conclusion:** B live + C dead proves the server requires `[lat, lon]` — exactly what the app already
sends, so H1 is falsified. D/E/F/G all zero (F and G with *no* message-type filter, over the entire
Gulf) proves the Persian Gulf, Gulf of Oman, **and the India west coast** are AISStream coverage
voids — H2 confirmed. Coverage is Europe/US/SE-Asia-skewed (A samples: USA, Netherlands, France; H: Singapore).

**Design response** (all config-driven via `backend/data/ais_boxes.json`):
1. **Multi-box single subscription** — Hormuz (kept: costs nothing, lights up if a receiver appears),
   India west coast (same rationale), Singapore Strait (live; inside the named Malacca corridor).
2. **Per-box coverage state** (`backend/app/ingestion/coverage.py`): zero frames for a rolling
   `COVERAGE_WINDOW_SECONDS = 600` window → `NO_TERRESTRIAL_COVERAGE`. The corridor's density feature
   is then **excluded from the risk sum with weights renormalized** and the UI badge reads
   "AIS: no terrestrial coverage in corridor" — never a silent fake zero. `GET /coverage` exposes state.
3. To add/remove a box: edit `ais_boxes.json` (bbox is `[lat_min, lon_min, lat_max, lon_max]`,
   `corridor` links it to a corridor's risk features or `null`) and restart the api service.

## Backend
| Task | Owner | Rubric | Status |
|---|---|---|---|
| FastAPI skeleton + `/health` + typed Pydantic models | You | Tech | ✅ |
| AISStream WS client + dead-reckoning + `/ws/vessels` relay | You | Tech/Innov | ✅ |
| AIS pipeline hop-by-hop diagnostic logging (a–e) + empty-key guard | You | Tech | ✅ |
| AIS task pinning (GC fix) + done-callback + raw-message logging + receive-loop exception hardening | You | Tech | ✅ |
| AIS hop-b-raw (full subscribe payload post-send) + hop-c-raw (pre-filter raw frame, first 20 msgs + all non-PositionReport) + hop-c-error (`traceback.format_exc()`, loop never dies) + BoundingBoxes triple-nesting assertion | You | Tech | ✅ |
| AIS coverage-void root-cause (diagnostic matrix A–H, `scripts/diag_aisstream.py` + `scripts/diag_relay.py`) | You | Tech | ✅ |
| Config-driven multi-box AIS subscription (`ais_boxes.json`) + per-box `CoverageMonitor` + `GET /coverage` | You | Tech/Innov | ✅ |
| Risk feature coverage states (`feature_states`, weight renormalization on `NO_TERRESTRIAL_COVERAGE`/`WARMING_UP`) + UI badge | You | Innov/Tech | ✅ |
| GDELT connector (TimelineVol, corridor bbox) + TTL cache (120s) + 429/Retry-After handling | You | Innov/Tech | ✅ |
| EIA + Alpha Vantage (cached) price connectors | You/teammate | Tech | ✅ (`PriceService` live via `/scenario`, `/reroute` — Task 4; concurrency-safety verified 2026-07-12 — a live 8-concurrent-request test found the TTL cache was **not** race-safe [8 concurrent requests → 8 real Alpha Vantage calls], fixed with `asyncio.Lock` double-checked locking, re-verified live at 1 real call per burst) |
| Open-Meteo + FRED connectors | Teammate | Scale | ✅ (live — Open-Meteo Marine wave height; FRED WPU301301 substitutes unavailable BCTI/BDI, docs/02 §7; concurrency-safety fixed 2026-07-12 — both `WeatherCache` and `FreightCache` had the same check-then-fetch-then-set race found in `PriceService`'s caches, closed with the identical `asyncio.Lock` double-checked-locking pattern, docs/02 §6–7) |
| OpenSanctions vessel screening | You | Innov | ✅ (live — SanctionsService screens observed AIS fleet by MMSI, backend/app/ingestion/sanctions.py; wired into both GET /risk/{corridor} and the Logistics agent node so risk score and narration agree; inherits AIS coverage-void state when there's no fleet to screen) |
| Risk engine (sigmoid + weighted features + per-feature breakdown) | You | Innov/Tech | ✅ (all five features live: kinetic/density/weather/freight/sanctions; sanctions state-aware — LIVE when AIS-covered and keyed, STUB when unkeyed, inherits WARMING_UP/NO_TERRESTRIAL_COVERAGE when there's no observed fleet) |
| Scenario cascade engine (5 steps, all sliders) | You | Business | ✅ (engine done Task 2; `GET /scenario/{corridor}` wired live Task 4) |
| Reroute MCDM (grade_match matrix) | You | Business | ✅ (engine done Task 3; `GET /reroute/{corridor}` wired live Task 4) |
| LangGraph orchestration (4 agents) | You | Tech/Innov | ✅ (Market Intelligence, Logistics & Maritime, Macroeconomic Strategist, Executive Orchestrator; AGENT_MODE=graph default, =sequential fallback calling the identical node functions; GET /recommendation/{corridor}) |
| Chroma RAG over policy/geopolitics docs | Teammate | Innov | ✂️ (cut Phase 3 — corpus never materialized, docs/03's own "RAG corpus: 10-20 PPAC/EIA/IEA/ORF" row below is still ⬜/empty on disk; policy facts kept inline in agent system prompts instead, docs/04 §G) |

## Frontend
| Task | Owner | Rubric | Status |
|---|---|---|---|
| Next.js + deck.gl + MapLibre base | You/teammate | UX | ✅ |
| Live vessel layer (Scatterplot + Path + Trips dead-reckoning) | You | UX/Tech | 🟨 (Scatterplot done; Path/Trips interpolation is Phase 2 polish) |
| Frontend WS hop-e console logging (vessel stream diagnostics) | You | Tech | ✅ |
| Corridor risk polygons (color by P) | Teammate | UX | ⬜ |
| Risk panel w/ stacked feature-contribution bar | You | Innov/UX | ✅ |
| Scenario sliders + live cascade readout | You | Business/UX | ✅ (live via Tasks 6 and 8 — `ScenarioCard` has 6 live sliders wired to `/scenario/hormuz`, debounced 250ms) |
| Reroute ranked-list card (executable plan) | You | Business | ✅ (`RerouteCard` fetches `/reroute/hormuz`, MCDM-ranked, debounced 250ms; now renders each option's live score as a numeric value + Δ-to-leader + proportional bar, not just final order, so the score-gap dynamic is visible on screen as the slider moves. A 201-point sweep of the full `disruption_factor` domain [verified 2026-07-12 against the real running API] found zero rank flips — Urals/Bonny Light/Merey/WTI/Liza/Mars keep a stable relative order at every point; `substitution_rate`/`hormuz_share` confirmed to have zero effect on this endpoint [not consumed by `rank_reroutes()` — macro-cascade-only params]. See docs/04 §C.) |
| Latency badge (signal→recommendation) | You | Business | ⬜ |
| Refinery + SPR markers | Teammate | UX | ⬜ |

## Packaging
| Task | Owner | Status |
|---|---|---|
| docker-compose (api, web, chroma, redis) | You | 🟨 (api+web+redis done; chroma lands with Phase 3 RAG) |
| `.env.example` + README run steps | Teammate | ⬜ |
| Clean-machine run verification | Teammate (QA) | ⬜ |

## Data (delegate-friendly)
| Task | Owner | Status |
|---|---|---|
| `refineries.json`, `spr.json`, `corridors.json`, `crude_grades.json` curated + source-verified | Teammate | 🟨 (`crude_grades.json` done — Task 3, source-verified per its `grade_match_rule` field; `refineries.json`/`spr.json` still ⬜, teammate-owned per docs/04 §D's delegated QA note) |
| RAG corpus: 10–20 public PDFs/articles (PPAC, EIA, IEA, ORF) | Teammate | ⬜ |

## Cut-list (drop in this order if behind)
1. Malacca + Bab-el-Mandeb depth (keep code path, Hormuz only) ✂️ first
2. FRED freight feed → static stub
3. OpenSanctions live → pre-screened static list
4. LangGraph → keep agents but run sequential if graph is flaky
5. Chroma RAG → cut entirely, keep facts inline ✂️ ACTUAL: cut 2026-07-12, see §G
**Never cut:** live AIS, explainable risk score, adjustable scenario, ranked reroute, latency badge.
