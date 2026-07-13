# 04 — Model Assumptions & Constants (the defensibility artifact)

> Every number on screen traces here. The dossier rendered some weights/formulas as images we could not read, so where a value was not legible we set a **calibrated default labelled `ASSUMPTION`** and made it adjustable in the UI. Show this file (or its UI mirror) to the jury when they ask "is this real?"

## A. Risk Score — interpretable, not a black box
Disruption probability for corridor *c* at time *t*:

```
P(c,t) = sigmoid( β0 + Σ wi · Xi )
```

- **`β0 = -3.0`** → with all `Xi = 0`, `sigmoid(-3.0) ≈ 4.74%` resting/background probability. (dossier-stated)
- All `Xi` normalized to `[0,1]`; weights sum to 1.0.
- **Weights (ASSUMPTION — calibrated defaults, adjustable in UI):**

| Feature | Weight | Why this rank |
|---|---|---|
| `X_kinetic` (GDELT) | **0.40** | Kinetic events tracked the Jan–Feb 2026 Hormuz flow collapse most directly → highest weight (dossier ranks it highest). |
| `X_density` (AIS anomaly) | **0.25** | Physical evidence of rerouting / refusal to transit. |
| `X_sanctions` (OFAC/EU) | **0.15** | Structural off-take barrier (Rosneft/Lukoil wind-down stranded volumes). |
| `X_weather` (Open-Meteo) | **0.10** | Transit delays, anchorage, port-approach congestion. |
| `X_freight` (FRED WPU301301) | **0.10** | Systemic tonnage-stress proxy. |

- **Explainability requirement:** the UI must show the per-feature contribution `wi·Xi` as a stacked bar, not just the final %. This is the single biggest "is it real" credibility win.
- **Phase 1–3 implementation status:** `X_kinetic`, `X_density`, `X_weather`, `X_freight` live (Phase 1–2); `X_sanctions` is now live-wired (Phase 3) — state-aware (LIVE when AIS-covered and keyed, STUB when unkeyed), inherits WARMING_UP/NO_TERRESTRIAL_COVERAGE. See `backend/app/engine/risk.py`, `backend/app/ingestion/sanctions.py`, and §H for agent/LLM wiring.
- **`X_density` substitution:** Phase 1 computes `X_density` from a short in-memory rolling window (`DensityTracker`, `backend/app/ingestion/density.py`) rather than the 30-day MA baseline documented in `docs/02_data_sources_and_schemas.md` §10 — a live demo can't accumulate 30 days of history. `ASSUMPTION`, revisit if a persistent store is added.
- **Feature coverage states + weight renormalization:** every feature now carries a provenance state (`LIVE` / `STUB` / `WARMING_UP` / `NO_TERRESTRIAL_COVERAGE`), returned in `RiskScore.feature_states`. Features in `WARMING_UP` or `NO_TERRESTRIAL_COVERAGE` are **excluded from the risk sum and the remaining weights renormalized to sum to 1.0** (`backend/app/engine/risk.py`) — a sensor with no coverage must never read as a genuine 0 ("all clear"). `STUB` features keep the original semantics (value pinned to 0, weight retained) so the resting probability stays anchored at `sigmoid(β0) ≈ 4.74%`.
- **`COVERAGE_WINDOW_SECONDS = 600`** (`backend/app/ingestion/coverage.py`): a subscribed AIS box that receives zero frames for a full 10-minute rolling window is declared `NO_TERRESTRIAL_COVERAGE`. `ASSUMPTION`, empirically calibrated 2026-07-05: every covered box in the diagnostic matrix (docs/03 "AIS coverage reality") produced its first frame in <1s; Hormuz and the entire Gulf produced zero frames in 2–5+ minutes across repeated runs, so 10 silent minutes is a conservative void signal.

## B. Macroeconomic Cascade (supply gap → GDP)
All steps are deterministic and assumption-driven. Each assumption is a **labelled, adjustable slider** in the Scenario panel.

**Anchor constants (sourced):**
- India crude import dependence ≈ **90%** (FY26).
- India refinery throughput ≈ **21.4 MMT/month** (Apr 2026); imports ≈ **19.3 MMT/month** ≈ **~4.7 mb/d**.
- India share of crude transiting Hormuz: peaked **55%** (Jan 2026); model default **45%** (`ASSUMPTION`, adjustable 30–60%).
- Hormuz baseline crude+condensate flow ≈ **14.6–20 mb/d** (config constant w/ citation, not a feed).

**Step 1 — Supply gap**
```
india_hormuz_volume = india_imports_mbd × hormuz_share
supply_gap          = india_hormuz_volume × disruption_factor × (1 − substitution_rate)
```
- `disruption_factor` slider 0–100% (Q1-2026 observed ~30%).
- `substitution_rate` slider 0–100% (how fast Russia/WAF/US backfill).

**Step 2 — Refinery run-rate impact**
```
utilization_drop_pct = supply_gap / india_imports_mbd
```
`ASSUMPTION`: OMCs at ~100% baseline utilization; unmitigated gap degrades output linearly (no instant substitution). Denominator uses `india_imports_mbd` rather than a separately-derived MMT/month throughput figure, to avoid inventing an unsourced unit conversion (`backend/app/engine/scenario.py`).

**Step 3 — SPR / buffer drawdown**
- Dedicated SPR Phase-I = **5.33 MMT (~39–40 Mbbl) ≈ 9.5 days** cover. Sites: Padur 2.50, Mangaluru 1.50, Vizag 1.33 MMT.
- Effective SPR fill **64%** (Mar 2026, 3.37 MMT) → real independent buffer < 9.5 days. (slider: SPR fill %)
- Plus OMC commercial ≈ **64.5 days** → total operational buffer ≈ **74 days** (below IEA's 90-day norm).
```
buffer_days           = SPR_DEDICATED_DAYS_AT_FULL_FILL × spr_fill_pct + OMC_COMMERCIAL_DAYS
days_cover_remaining  = buffer_days × (1 − utilization_drop_pct)
```
`ASSUMPTION` (revised post Task-2 review): `days_cover_remaining` shrinks `buffer_days` proportionally to
`utilization_drop_pct` (Step 2's fraction of unmet national demand), rather than dividing a fixed buffer
volume by the raw supply gap. The literal `buffer_volume / daily_supply_gap` form blows toward infinity as
the gap shrinks, producing a discontinuity where the metric *increases* for small disruption before
decreasing at high disruption — the opposite of the intended "buffer depleting" narrative. The revised
formula is monotonically decreasing across the full slider range and still anchors at the ~74-day baseline
above when `disruption_factor = 0`.

**Step 4 — Fuel price / CPI**
RBI rule of thumb (sourced): a sustained **10%** rise in the Indian crude basket lifts headline CPI by **+0.3 to +0.4 pp**.
```
crude_price_rise_pct = disruption_factor × price_sensitivity × 100
cpi_delta_pp          = (crude_price_rise_pct / 10) × cpi_sensitivity     # cpi_sensitivity slider 0.3–0.4
```
`PRICE_SENSITIVITY = 1.0` (`ASSUMPTION`, no doc precedent for this mechanism — `backend/app/engine/scenario.py`): derives `crude_price_rise_pct` directly from `disruption_factor` so one slider drives the whole 5-step cascade, instead of requiring a second independent "price rise" slider. Calibrated 1:1 as the simplest defensible default; `TODO` validate against a historical regression.

`BRENT_BASELINE_USD_BBL = 75.0` (`STUB → no cited source, arbitrary placeholder`, `backend/app/engine/scenario.py`): used only if the caller doesn't supply a live price (mirrors `prices.BRENT_FALLBACK_USD_BBL`, `backend/app/ingestion/prices.py`) — in practice `/scenario/{corridor}` always overrides this with `PriceService.get_brent_price()`'s live-or-fallback Brent quote.

Historical anchor: Apr 2026 basket hit **$114/bbl**; RBI noted CPI 3.5%→3.9% via fuel pass-through.

**Step 5 — GDP & CAD**
- **GDP:** a 10% crude rise shaves **~15 bps** off GDP growth (`ASSUMPTION` from dossier's 2019 Abqaiq anchor: ~20% spike → ~30 bps drag).
```
gdp_drag_bps = (crude_price_rise_pct / 10) × 15
```
- **CAD:** every **$10/bbl** rise widens CAD by **~0.3–0.4% of GDP** (`ASSUMPTION`, adjustable). 
```
cad_widening_pct_gdp = (crude_usd_increase / 10) × cad_sensitivity
```

## C. Procurement Reroute — MCDM ranking
```
Score(alt) = w_cost·norm(1/landed_cost)
           + w_time·norm(1/voyage_days)
           + w_grade·grade_match
           − w_cong·congestion_penalty
```
- `landed_cost` = spot (Alpha Vantage/EIA) + freight proxy (FRED BCTI) — Delivered Ex-Ship.
- `grade_match` ∈ {1.0 ideal, 0.5 needs blending, 0.0 incompatible API/sulfur}.
- Default weights (`ASSUMPTION`, adjustable): `w_cost 0.35, w_time 0.25, w_grade 0.30, w_cong 0.10`.

**Crude alternatives (grade × refinery compatibility):**
| Source / grade | API / sulfur | Class | Voyage to W. India | Best fit refineries |
|---|---|---|---|---|
| Russia — Urals | ~31° / ~1.3% | Medium sour | 22–28 d (35–40 d via Cape) | RIL Jamnagar, Nayara Vadinar |
| US — WTI | ~39° / ~0.25% | Light sweet | 40–45 d | IOCL, BPCL, HPCL |
| US — Mars | medium | Medium sour | 40–45 d | RIL, IOCL |
| W. Africa — Bonny Light | ~35° / <0.2% | Light sweet | 25–30 d (Cape) | PSU refiners (low desulf cost) |
| Venezuela — Merey | ~16° / high | Heavy sour | 45–50 d | RIL Jamnagar only (coking) |
| Guyana — Liza | medium | Medium sweet | 45–50 d | IOCL/BPCL |

**`grade_match` matrix is the defensibility centrepiece of the reroute engine** — it's why we beat a generic "cheapest barrel" recommender. A heavy-sour Merey cargo to a simple PSU refinery scores 0.0 even if it's cheapest.

**Live-recompute finding (verified 2026-07-12 against the running API):** every score recomputes correctly on every `disruption_factor` change (confirmed against real numbers, not mocked). A fine-grained sweep of `disruption_factor` across its full `[0.0, 1.0]` domain at 201 points (step 0.005) found **zero rank flips** — the order is Urals, Bonny Light, Merey, WTI, Liza, Mars at every sampled point, not just the two extremes checked in an earlier pass. Cost dominates the additive formula enough that `grade_match`/congestion never overturn the cost-driven ranking for this particular grade set and live Brent price level — the closest adjacent-score gap anywhere in the sweep was 0.0037 (at `disruption_factor≈0.97`), the widest 0.0062 (at `disruption_factor=0.0`), and it never crosses zero.

`GET /reroute/{corridor}` (`backend/app/api/routes.py`) only accepts `disruption_factor` as a query parameter — `rank_reroutes()` (`backend/app/engine/reroute.py`) never consumes `substitution_rate` or `hormuz_share`; those two only feed the separate macro cascade via `/scenario/{corridor}`. Confirmed live: passing `substitution_rate`/`hormuz_share` to `/reroute/hormuz` (including at their extreme values 0.0/1.0) returns a byte-identical response to omitting them entirely. So "sweep the reroute ranking across all three sliders" collapses to "sweep `disruption_factor`" for this endpoint — there is no realistic-bounds combination of the other two that can move it, because the endpoint doesn't read them.

This doesn't undermine the `grade_match` defensibility story above (Merey's score is honestly lower than it would be with `grade_match=1.0`, which is the actual claim), but it does mean a live demo cannot show the ranked list visibly *reordering* by dragging `disruption_factor` — only the scores/values and the gap between them changing (now visible on-screen as a live bar + Δ-to-leader in `RerouteCard.tsx`, not just the final order). Worth a weight-recalibration pass (e.g. raising `w_grade` relative to `w_cost`) if a visible reorder becomes a demo requirement.

## D. Reference entities (for map markers + reroute targets)
**Refineries (lat, lon, MMTPA):**
- RIL Jamnagar 22.34, 69.08 — 68.2 · Nayara Vadinar 22.28, 69.73 — 20
- IOCL Panipat 29.39, 76.97 — 15→25 · Paradip 20.27, 86.61 — 15 · Koyali 22.34, 73.18 — 13.7→18 · Haldia 22.03, 88.06 — 8 · Mathura 27.48, 77.67 — 8
- BPCL Kochi 9.97, 76.27 — 15.5 · Mumbai 19.05, 72.91 — 12 · Bina 24.18, 78.20 — 7.8
- HPCL Vizag 17.69, 83.21 — 15 · Mumbai 19.07, 72.87 — 9.5 · HMEL Bathinda 30.21, 74.95 — 11.3

**SPR sites (lat, lon, MMT):** Padur 13.30, 74.78 — 2.50 · Mangaluru 12.87, 74.84 — 1.50 · Vizag 17.69, 83.21 — 1.33

> Verify all coordinates and capacities against PPAC / Wikipedia before the deck — flagged as a delegated QA task.

## E. Reroute engine — implementation constants (Phase 2)
Two implementation-only constants in `backend/app/engine/reroute.py`, not yet itemized above:

- **`FREIGHT_PROXY_USD_BBL_PER_DAY = 0.10`** — `STUB → FRED BCTI/BDI freight proxy, docs/02 §7` (cut-list #2). `ASSUMPTION`: a ballpark tanker freight cost per voyage-day, applied uniformly across grades, added to landed cost as `FREIGHT_PROXY_USD_BBL_PER_DAY × grade.voyage_days`.
- **`CONGESTION_DISRUPTION_SENSITIVITY = 0.15`** — `STUB → Portcast, docs/02 §8`. `ASSUMPTION`: port congestion stress rises with corridor `disruption_factor` as buyers scramble for the same alternative barrels, scaled by a grade's relative voyage exposure (`voyage_days / 30`).

Grade compatibility (`grade_match`), API gravity/sulfur figures, voyage days, price differentials, and per-grade congestion baselines are **not** re-derived here — the authoritative, source-annotated values live in `backend/data/crude_grades.json`'s `grade_match_rule` field, which documents exactly which figures are sourced table midpoints (docs/04 §C) versus `ASSUMPTION` estimates within a qualitative range versus illustrative `STUB` placeholders pending live feeds. Read that field before citing any individual grade's numbers.

## F. Weather & freight connectors — implementation constants (Phase 2)

**`backend/app/ingestion/weather.py` (Open-Meteo Marine, docs/02 §6):**
- **`WAVE_HEIGHT_THRESHOLD_M = 4.0`** — `ASSUMPTION`. Forecast max `wave_height` at/above this flags `X_weather = 1` for the corridor; below it, `X_weather = 0`.
- **`WEATHER_CACHE_TTL_SECONDS = 1800.0`** — implementation-only (not a modeling constant). Bounds real Open-Meteo calls to once per 30 minutes per corridor against the frontend's 10s `/risk/{corridor}` poll; hourly forecast data doesn't change meaningfully faster than this window.

**`backend/app/ingestion/freight.py` (FRED, docs/02 §7):**
- **BCTI/BDI unavailability finding:** verified live 2026-07-10 via FRED's series-search API that neither the Baltic Clean Tanker Index nor the Baltic Dry Index exists as a FRED series — the Baltic Exchange doesn't license them to FRED. This is not a rate-limit or key issue; the series genuinely don't exist on the platform.
- **`FREIGHT_SERIES_ID = "WPU301301"`** — `STUB → substitutes BCTI/BDI, docs/02 §7`. "Producer Price Index by Commodity: Transportation Services: Deep Sea Water Transportation of Freight" (monthly, BLS via FRED), verified reachable with real data through 2026-05. `ASSUMPTION`: a PPI for deep-sea freight transport is a defensible systemic ocean-freight-cost proxy, though it is not a tanker spot index like BCTI.
- **`N_BASELINE_MONTHS = 3`** — `ASSUMPTION`. The series is monthly, not daily, so docs/02 §7's literal "90-day baseline" becomes "the 3 monthly prints preceding the latest one."
- **`FREIGHT_STRESS_SCALE_PCT = 15.0`** — `ASSUMPTION`. Maps pct deviation of the latest print from the `N_BASELINE_MONTHS` baseline onto the risk engine's `[0,1]` feature convention: a deviation at/beyond this magnitude reads as full freight stress (`X_freight = 1.0`).
- **`FREIGHT_CACHE_TTL_SECONDS = 3600.0`** — implementation-only. The underlying FRED series is monthly, so an hour of staleness is immaterial; this just bounds how often the risk endpoint's 10s frontend poll triggers a real FRED request.

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
