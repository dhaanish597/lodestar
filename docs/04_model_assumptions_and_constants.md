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
| `X_freight` (BCTI) | **0.10** | Systemic tonnage-stress proxy. |

- **Explainability requirement:** the UI must show the per-feature contribution `wi·Xi` as a stacked bar, not just the final %. This is the single biggest "is it real" credibility win.
- **Phase 1 implementation status:** `X_kinetic` and `X_density` are live; `X_sanctions`, `X_weather`, `X_freight` are `STUB → 0.0` pending Phase 2 connectors (OpenSanctions, Open-Meteo, FRED respectively). See `backend/app/engine/risk.py`.
- **`X_density` substitution:** Phase 1 computes `X_density` from a short in-memory rolling window (`DensityTracker`, `backend/app/ingestion/density.py`) rather than the 30-day MA baseline documented in `docs/02_data_sources_and_schemas.md` §10 — a live demo can't accumulate 30 days of history. `ASSUMPTION`, revisit if a persistent store is added.

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
utilization_drop_pct = supply_gap / india_total_crude_throughput_mbd
```
`ASSUMPTION`: OMCs at ~100% baseline utilization; unmitigated gap degrades output linearly (no instant substitution).

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
