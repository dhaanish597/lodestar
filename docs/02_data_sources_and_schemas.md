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
  - "Dark fleet" turns transponders off in kinetic zones.
  - **Dead-reckoning rule:** if `now_utc - Timestamp > 2h`, extrapolate position from last `Sog`+`TrueHeading`, render it, and flag the vessel `signal_lost=true` in the risk engine. (Becomes a deck.gl `TripsLayer` interpolation on the frontend.)
- **Backend task:** persistent async WS client → in-memory ring buffer of latest position per MMSI → relay to frontend over our own `/ws/vessels`. Reconnect with backoff; resend subscription on every reconnect.

## 2. EIA API v2 — fundamentals + benchmark spot (baseline, not intraday)
- **Base:** `https://api.eia.gov/v2/`
- **Auth:** `?api_key=<KEY>`
- **Free:** unlimited non-commercial.
- **Brent + WTI daily spot:**
  `GET /v2/petroleum/pri/spt/data/?api_key=<KEY>&frequency=daily&data[]=value&facets[series][]=DCOILBRENTEU&facets[series][]=DCOILWTICO&sort[0][column]=period&sort[0][direction]=desc&length=60`
- **Gotcha:** spot prices publish in **weekly batches (~Tuesdays)** → up to 1 week lag. Use for historical baselining/trend only; intraday falls back to Alpha Vantage.
- **Note:** Hormuz throughput is **not** a live API — it's in static EIA/Vortexa special reports. Treat chokepoint baseline flow as a config constant (`~14.6–20 mb/d`) with a citation, not a feed.

## 3. GDELT 2.0 DOC API — geopolitical early warning (no key)
- **Base:** `https://api.gdeltproject.org/api/v2/doc/doc`
- **Auth:** none.
- **Window:** only the **last 90 days** are queryable (older startdatetime → empty).
- **Corridor kinetic volume (timeseries):**
  `GET ?query=(Hormuz OR "Red Sea") (attack OR strike OR sanction OR disruption)&mode=TimelineVol&timespan=72h&format=json`
- **Geographic narrowing:** add `bbox=25.27,55.16,27.37,57.34` for Hormuz.
- **Noise control:** prefer a `theme` filter (e.g. `theme=CRISISLEX_CRISISLEXREC`) and/or LLM relevance filtering on returned text.
- **Response:** `timeline[].data[]` → `{date, value}` article-volume points. We MinMax-scale this into the risk feature `X_kinetic`.

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

## 6. Open-Meteo Marine — sea state on routes (no key)
- **Base:** `https://marine-api.open-meteo.com/v1/marine`
- **Free:** 10,000 req/day.
- **Query:** `?latitude=26.0&longitude=56.0&hourly=wave_height,wind_wave_direction,swell_wave_period`
- **Use:** `X_weather = 1` if `wave_height_max ≥ threshold` (default 4.0 m) in the corridor, else 0. Units metric by default.

## 7. FRED — freight / war-risk proxy (key, free)
- **Base:** `https://api.stlouisfed.org/fred/series/observations`
- **Use:** Baltic Clean Tanker Index (BCTI) / Baltic Dry Index (BDI) as systemic shipping-stress proxy. `X_freight = pct_deviation(current, 90d_baseline)`.
- If a clean BCTI series ID isn't retrievable on free tier → `STUB →` static 90-day series + TODO.

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
| `X_freight` | FRED (BCTI) / Alpha Vantage | % deviation vs 90-day baseline |

Risk model + scenario/reroute math live in `04_model_assumptions_and_constants.md`.
