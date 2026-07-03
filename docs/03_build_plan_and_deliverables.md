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

## Backend
| Task | Owner | Rubric | Status |
|---|---|---|---|
| FastAPI skeleton + `/health` + typed Pydantic models | You | Tech | ✅ |
| AISStream WS client + dead-reckoning + `/ws/vessels` relay | You | Tech/Innov | ✅ |
| AIS pipeline hop-by-hop diagnostic logging (a–e) + empty-key guard | You | Tech | ✅ |
| AIS task pinning (GC fix) + done-callback + raw-message logging + receive-loop exception hardening | You | Tech | ✅ |
| GDELT connector (TimelineVol, corridor bbox) + TTL cache (120s) + 429/Retry-After handling | You | Innov/Tech | ✅ |
| EIA + Alpha Vantage (cached) price connectors | You/teammate | Tech | ✅ (`PriceService` live via `/scenario`, `/reroute` — Task 4) |
| Open-Meteo + FRED connectors | Teammate | Scale | ⬜ |
| OpenSanctions vessel screening | You | Innov | ⬜ |
| Risk engine (sigmoid + weighted features + per-feature breakdown) | You | Innov/Tech | 🟨 (kinetic + density live, sanctions/weather/freight stubbed at 0 pending Phase 2) |
| Scenario cascade engine (5 steps, all sliders) | You | Business | ✅ (engine done Task 2; `GET /scenario/{corridor}` wired live Task 4) |
| Reroute MCDM (grade_match matrix) | You | Business | ✅ (engine done Task 3; `GET /reroute/{corridor}` wired live Task 4) |
| LangGraph orchestration (4 agents) | You | Tech/Innov | ⬜ |
| Chroma RAG over policy/geopolitics docs | Teammate | Innov | ⬜ |

## Frontend
| Task | Owner | Rubric | Status |
|---|---|---|---|
| Next.js + deck.gl + MapLibre base | You/teammate | UX | ✅ |
| Live vessel layer (Scatterplot + Path + Trips dead-reckoning) | You | UX/Tech | 🟨 (Scatterplot done; Path/Trips interpolation is Phase 2 polish) |
| Frontend WS hop-e console logging (vessel stream diagnostics) | You | Tech | ✅ |
| Corridor risk polygons (color by P) | Teammate | UX | ⬜ |
| Risk panel w/ stacked feature-contribution bar | You | Innov/UX | ✅ |
| Scenario sliders + live cascade readout | You | Business/UX | ⬜ |
| Reroute ranked-list card (executable plan) | You | Business | 🟨 (hardcoded, not yet MCDM-driven) |
| Latency badge (signal→recommendation) | You | Business | ⬜ |
| Refinery + SPR markers | Teammate | UX | ⬜ |

## Packaging
| Task | Owner | Status |
|---|---|---|
| docker-compose (api, web, chroma, redis) | You | 🟨 (api+web done; chroma/redis land with Phase 2/3 RAG + caching) |
| `.env.example` + README run steps | Teammate | ⬜ |
| Clean-machine run verification | Teammate (QA) | ⬜ |

## Data (delegate-friendly)
| Task | Owner | Status |
|---|---|---|
| `refineries.json`, `spr.json`, `corridors.json`, `crude_grades.json` curated + source-verified | Teammate | ⬜ |
| RAG corpus: 10–20 public PDFs/articles (PPAC, EIA, IEA, ORF) | Teammate | ⬜ |

## Cut-list (drop in this order if behind)
1. Malacca + Bab-el-Mandeb depth (keep code path, Hormuz only) ✂️ first
2. FRED freight feed → static stub
3. OpenSanctions live → pre-screened static list
4. LangGraph → keep agents but run sequential if graph is flaky
5. Chroma RAG → cut entirely, keep facts inline
**Never cut:** live AIS, explainable risk score, adjustable scenario, ranked reroute, latency badge.
