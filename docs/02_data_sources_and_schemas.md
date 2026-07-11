# 02 — Data Sources & Schemas (implementation-ready)

> Extracted from the Gemini dossier and turned into build tasks. Every feed below is **free-tier reachable**. Anything stubbed is labelled `STUB →` with the real source to swap in. Keys live in `.env` only.

## 0. Env keys needed
```
AISSTREAM_API_KEY=        # free, https://aisstream.io
EIA_API_KEY=              # free, https://www.eia.gov/opendata/
ALPHAVANTAGE_API_KEY=     # free, 25 req/day
OPENSANCTIONS_API_KEY=    # free (non-commercial), https://www.opensanctions.org
FRED_API_KEY=             # free, https://fred.stlouisfed.org/docs/api/
# GDELT, Open-Meteo: no key
```

## 1. AISStream.io — live AIS (the showpiece)
- **Transport:** WebSocket `wss://stream.aisstream.io/v0/stream`
- **Auth:** API key inside the first JSON message (NOT a header).
- **Critical:** subscription JSON must be sent **within 3s** of connect or the socket is dropped.
- **Free tier:** bounding-box monitoring is fine; MMSI filtering capped at **50 MMSI/connection** (we filter by bbox, not MMSI, so this doesn't bite us).
- **Subscribe payload (Hormuz):**
```json
{
  "APIKey": "<KEY>",
  "BoundingBoxes": [[[25.2732, 55.1647], [27.3713, 57.3419]]],
  "FilterMessageTypes": ["PositionReport"]
}
```
- **PositionReport fields we use:** `UserID` (MMSI), `Latitude`, `Longitude`, `Sog` (speed kn), `Cog` (course), `TrueHeading`, `NavigationalStatus` (0=underway,1=anchor,15=undefined), `Timestamp` (UTC s), `Valid`.
- **Gotchas:**
  - Terrestrial receivers → ~15–20 nm offshore line-of-sight; deep-ocean vessels drop out.
  - **Coverage voids are real and regional** — empirically verified 2026-07-05 (`scripts/diag_aisstream.py`, results table in docs/03 "AIS coverage reality"): the **entire Persian Gulf + Gulf of Oman produced zero frames of any message type**, while Dover/Europe boxes stream instantly. There are simply no volunteer receivers feeding AISStream there. Coordinate order `[lat, lon]` was verified correct (Dover in lat-lon → data; axes swapped → nothing), so this is a data-availability property, not a payload bug.
  - `BoundingBoxes` accepts **multiple boxes in one subscription** — we subscribe to all boxes in `backend/data/ais_boxes.json` in a single message (Hormuz kept despite the void; it costs nothing and lights up if a receiver ever appears).
  - **Coverage-state rule:** per subscribed box, if zero frames arrive for a full rolling window (`COVERAGE_WINDOW_SECONDS = 600`, `backend/app/ingestion/coverage.py`), that box reports `NO_TERRESTRIAL_COVERAGE`; a corridor risk feature backed by an uncovered box is **excluded from the risk sum with weights renormalized** and badged in the UI — never a silent zero. `GET /coverage` exposes per-box state.
  - "Dark fleet" turns transponders off in kinetic zones.
  - **Dead-reckoning rule:** if `now_utc - Timestamp > 2h`, extrapolate position from last `Sog`+`TrueHeading`, render it, and flag the vessel `signal_lost=true` in the risk engine. (Becomes a deck.gl `TripsLayer` interpolation on the frontend.)
- **Backend task:** persistent async WS client (multi-box subscription from `ais_boxes.json`) → in-memory ring buffer of latest position per MMSI, with per-box frame attribution into `CoverageMonitor` → relay to frontend over our own `/ws/vessels`. Reconnect with backoff; resend subscription (and restart the coverage warm-up clock) on every reconnect.

## 2. EIA API v2 — fundamentals + benchmark spot (baseline, not intraday)
- **Base:** `https://api.eia.gov/v2/`
- **Auth:** `?api_key=<KEY>`
- **Free:** unlimited non-commercial.
- **Brent + WTI daily spot:**
  `GET /v2/petroleum/pri/spt/data/?api_key=<KEY>&frequency=daily&data[]=value&facets[series][]=DCOILBRENTEU&facets[series][]=DCOILWTICO&sort[0][column]=period&sort[0][direction]=desc&length=60`
- **Gotcha:** spot prices publish in **weekly batches (~Tuesdays)** → up to 1 week lag. Use for historical baselining/trend only; intraday falls back to Alpha Vantage.
- **Note:** Hormuz throughput is **not** a live API — it's in static EIA/Vortexa special reports. Treat chokepoint baseline flow as a config constant (`~14.6–20 mb/d`) with a citation, not a feed.
- **Implementation note:** `backend/app/ingestion/prices.py` implements the EIA connector as `EiaCache`, one leg of the `PriceService` orchestrator's fallback chain: Alpha Vantage (preferred, intraday-ish) → EIA (weekly baseline) → static `BRENT_FALLBACK_USD_BBL` constant if both are unset or unreachable. `EiaCache` carries a 3600s (1-hour) TTL, so it never fires directly on a page load.

## 3. GDELT 2.0 DOC API — geopolitical early warning (no key)
- **Base:** `https://api.gdeltproject.org/api/v2/doc/doc`
- **Auth:** none.
- **Window:** only the **last 90 days** are queryable (older startdatetime → empty).
- **Corridor kinetic volume (timeseries):**
  `GET ?query=(Hormuz OR "Red Sea") (attack OR strike OR sanction OR disruption)&mode=TimelineVol&timespan=72h&format=json`
- **Geographic narrowing:** add `bbox=25.27,55.16,27.37,57.34` for Hormuz.
- **Noise control:** prefer a `theme` filter (e.g. `theme=CRISISLEX_CRISISLEXREC`) and/or LLM relevance filtering on returned text.
- **Response:** `timeline[].data[]` → `{date, value}` article-volume points. We MinMax-scale this into the risk feature `X_kinetic`.
- **Rate limits:** GDELT enforces ~1 request per 5 seconds; exceeding this returns HTTP 429.
- **Implementation note:** `backend/app/ingestion/gdelt.py` implements exactly this query (`mode=TimelineVol`, `timespan=72h`, `bbox=25.27,55.16,27.37,57.34`) and MinMax-scales the latest timeline point into `[0,1]` — confirmed matching the documented query/timespan/bbox above. Theme filtering (`theme=CRISISLEX_CRISISLEXREC`) is not yet applied — `STUB →` noise-reduction improvement, Phase 2. The connector uses a `GdeltCache` class with a 120s TTL: on a 429, it reads the `Retry-After` header, backs off, and serves the last good cached value. The `/risk/hormuz` endpoint polls frequently; the cache ensures at most 1 real GDELT request per 2 minutes.

## 4. OpenSanctions — vessel / entity screening
- **Base:** `https://api.opensanctions.org/match/default`
- **Auth:** header `Authorization: ApiKey <KEY>`
- **Free:** non-commercial/academic.
- **Match-by-example (FollowTheMoney schema):**
```json
{ "queries": { "q1": { "schema": "Vessel", "properties": { "imo": ["9123456"] } } } }
```
- **Response:** ranked candidates → `score`, `id`, `caption`, `properties.topics` (e.g. `"sanction"`).
- **Gotchas:** fuzzy matching → high false positives on bare names; **always pass IMO/MMSI** for exact match. Use `exclude_dataset` to drop irrelevant lists.
- **Use:** for each observed MMSI in a corridor, screen → `X_sanctions = flagged_vessels / observed_fleet`.

## 5. Alpha Vantage — intraday-ish crude quotes (rate-limited)
- **Base:** `https://www.alphavantage.co/query`
- **Auth:** `?apikey=<KEY>`
- **Free:** **25 requests/day** — hard cap.
- **Brent / WTI:** `?function=BRENT&interval=daily&apikey=<KEY>` (also `WTI`).
- **Mandatory caching:** query once/hour (or once/day), cache in Redis/memory, serve cached to clients. Never call on page load.
- **Implementation note:** `backend/app/ingestion/prices.py` implements this connector as `AlphaVantageCache`, the preferred leg of the `PriceService` orchestrator's fallback chain (Alpha Vantage → EIA → static `BRENT_FALLBACK_USD_BBL`). Its mandatory 1-hour TTL guarantees at most ~24 real Alpha Vantage calls/day regardless of frontend poll frequency — safely under the 25/day free-tier cap — and it never fires directly on a page load.

## 6. Open-Meteo Marine — sea state on routes (no key)
- **Base:** `https://marine-api.open-meteo.com/v1/marine`
- **Free:** 10,000 req/day.
- **Query:** `?latitude=26.0&longitude=56.0&hourly=wave_height,wind_wave_direction,swell_wave_period`
- **Use:** `X_weather = 1` if `wave_height_max ≥ threshold` (default 4.0 m) in the corridor, else 0. Units metric by default.
- **Implementation note:** `backend/app/ingestion/weather.py` implements this connector as a per-corridor `WeatherCache`, keyed on the corridor bbox's center point (`WeatherService._bbox_center()`), so Hormuz and any other subscribed corridor get independent forecasts rather than sharing one lat/lon. Each `WeatherCache` carries a 1800s (30-min) TTL — hourly forecast data doesn't move fast enough to justify calling on every 10s frontend poll. `WAVE_HEIGHT_THRESHOLD_M = 4.0` is the flag threshold: forecast max `wave_height` at/above it sets `X_weather = 1`, else `0`.

## 7. FRED — freight / war-risk proxy (key, free)
- **Base:** `https://api.stlouisfed.org/fred/series/observations`
- **Use:** Baltic Clean Tanker Index (BCTI) / Baltic Dry Index (BDI) as systemic shipping-stress proxy. `X_freight = pct_deviation(current, 90d_baseline)`.
- BCTI/BDI confirmed unavailable on FRED (verified 2026-07-10) — rather than falling back to a static-stub series, a live substitute series was wired in instead. See the implementation note below for detail.
- **Implementation note:** `backend/app/ingestion/freight.py` confirmed live, 2026-07-10, via a direct query against FRED's series-search API that neither BCTI nor BDI exists as a FRED series — the Baltic Exchange doesn't license them to FRED. The connector substitutes `FREIGHT_SERIES_ID = "WPU301301"` ("Producer Price Index by Commodity: Transportation Services: Deep Sea Water Transportation of Freight", monthly, BLS via FRED), verified reachable with real data through 2026-05, as the nearest defensible live proxy for systemic ocean-freight cost. Because the series is monthly rather than daily, `N_BASELINE_MONTHS = 3` adapts this doc's literal "90-day baseline" language to "the 3 monthly prints preceding the latest one." `FREIGHT_STRESS_SCALE_PCT = 15.0` maps the resulting pct deviation from baseline onto the risk engine's `[0,1]` feature convention (a ≥15% deviation reads as full freight stress, `X_freight = 1.0`). `FreightCache` carries a 3600s (1-hour) TTL.

## 8. Port congestion — Portcast / Safecube (paywalled)
- `STUB →` historical average anchorage wait per discharge port (Sikka/Jamnagar, Mumbai, Kochi, Vizag, Paradip). Feeds `CongestionPenalty` in the reroute MCDM. TODO: swap to Portcast `GET /schedules/port?code=INDMB` on trial key.

## 9. Geodata constants (corridors → bounding boxes)
```json
{
  "hormuz":      { "bbox": [25.2732, 55.1647, 27.3713, 57.3419] },
  "bab_el_mandeb": { "bbox": [11.5, 43.0, 13.2, 43.6] , "note": "approx; ~12.5N Djibouti/Eritrea↔Yemen" },
  "malacca":     { "bbox": [1.0, 100.0, 6.0, 104.0], "note": "approx; true shape is a multi-point polygon" }
}
```
Hormuz is the demo spine. Bab-el-Mandeb + Malacca are "breadth = future work" — wire the same code path, don't deepen.

## 10. Feed → risk-feature map (quick reference)
| Feature | Source | Normalization |
|---|---|---|
| `X_kinetic` | GDELT TimelineVol (corridor bbox) | MinMax of article volume |
| `X_density` | AISStream | 1 if tanker count drops ≥ Nσ below 30-day MA |
| `X_sanctions` | OpenSanctions | flagged / observed fleet |
| `X_weather` | Open-Meteo | 1 if wave_height_max ≥ 4.0 m |
| `X_freight` | FRED (WPU301301, substitutes unavailable BCTI/BDI) | % deviation vs 90-day baseline |

**Implementation note (`X_density`):** Phase 1 substitutes a short in-memory rolling window (`DensityTracker`, `backend/app/ingestion/density.py`, default 20 samples) for the 30-day MA baseline above — a live demo can't accumulate 30 days of history. `ASSUMPTION`, revisit if a persistent store is added. Cross-referenced in `04_model_assumptions_and_constants.md` §A.

**Coverage-state note (`X_density`):** the vessel count feeding `X_density` is now per-corridor (`VesselStore.snapshot_in_bbox`), and the feature carries an explicit state (`LIVE` / `WARMING_UP` / `NO_TERRESTRIAL_COVERAGE`) from `CoverageMonitor`. When the corridor's AIS box is uncovered — Hormuz's empirical state as of 2026-07-05 — the feature is excluded from the risk sum with the remaining weights renormalized, the rolling baseline is not fed coverage-void zeros, and the UI badge says "AIS: no terrestrial coverage in corridor". See docs/03 "AIS coverage reality" and docs/04 §A.

Risk model + scenario/reroute math live in `04_model_assumptions_and_constants.md`.
