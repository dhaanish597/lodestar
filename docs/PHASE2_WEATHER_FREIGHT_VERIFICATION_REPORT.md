# Phase 2 — Weather + Freight Connectors Verification Report — 2026-07-10T22:20:00+05:30

Scope: verification for `docs/superpowers/plans/2026-07-10-weather-freight-risk-wiring.md` (Tasks 1–5), plus a light re-check of Phase 1's prior 9-check baseline against the currently running system (user chose "light re-check" over a full cold `down -v` rebuild + 10-min GDELT burst, given the same-week `PHASE1_VERIFICATION_REPORT.md` already carried strong raw evidence).

## Summary

| # | Check | Result |
|---|---|---|
| 1 | Full backend test suite (host) | PASS — 77/77 (excludes pre-existing, unrelated broken `test_gdelt.py`) |
| 2 | Stack builds and starts | PASS (after a build-cache gotcha, see below) |
| 3 | `/health` | PASS |
| 4 | `/coverage` | PASS — matches Phase 1 baseline (Hormuz/India-west-coast void, Malacca/Singapore covered) |
| 5 | `/risk/hormuz` — weather live | PASS — real Open-Meteo wave-height reading, correctly below threshold |
| 6 | `/risk/hormuz` — freight live | PASS — real FRED WPU301301 reading, nonzero stress value |
| 7 | `/risk/hormuz` — sanctions still honest STUB | PASS |
| 8 | `/scenario/hormuz`, `/reroute/hormuz` — no regression | PASS |
| 9 | Backend logs — connector fetch lines, no errors/429s | PASS |
| 10 | Frontend serves | PASS (200); full DOM/screenshot check blocked by a tooling port conflict, see note |

**Phase 2 weather/freight exit condition (risk engine visibly 4-of-5 live, no regression to scenario/reroute): PASS.**

## Evidence

### 1. Full backend test suite (host, not container — see gotcha below)

```
======================= 77 passed, 1 warning in 30.27s ========================
```
The 1 warning is a pre-existing, unrelated `PendingDeprecationWarning` from `starlette.formparsers` (`import multipart` vs `python_multipart`), not from any code touched this session.

`tests/test_gdelt.py` was excluded (`--ignore`) — it fails to *collect* (`ImportError: cannot import name 'GdeltCache' from 'app.ingestion.gdelt'`), confirmed via `git log --oneline -1 -- tests/test_gdelt.py app/ingestion/gdelt.py` to predate this entire session (last touched at `bdee206`, the exact commit recorded as this session's starting point). `gdelt.py` was refactored to a Redis-backed poller at some point without updating its test file. **Flagged to the user as an out-of-scope, pre-existing repo defect — not fixed here.**

### 2. Stack build — a real gotcha hit and fixed during verification

`docker-compose up -d --build` completed and reported `api Built`, `web Built`, but the resulting `api` container's filesystem was **stale** — missing `weather.py`/`freight.py` entirely and running pre-Task-3 `routes.py`:

```
$ docker-compose exec -T api ls app/ingestion/
__init__.py  __pycache__  aisstream.py  coverage.py  dead_reckoning.py  density.py  gdelt.py  prices.py
# (weather.py, freight.py absent)
```

Root cause not fully isolated (Docker Desktop/BuildKit layer-cache reuse on this Windows host), but a hard fix confirmed it:

```
$ docker-compose build --no-cache api
$ docker-compose up -d --force-recreate api
$ docker-compose exec -T api ls app/ingestion/
__init__.py  __pycache__  aisstream.py  coverage.py  dead_reckoning.py  density.py  freight.py  gdelt.py  prices.py  weather.py
```

**Takeaway for future rebuilds on this environment:** if a `docker-compose up -d --build` doesn't seem to reflect a recent code change, don't trust it — confirm with `docker-compose exec <service> ls`/`grep` against the actual file, and use `--no-cache` + `--force-recreate` if it's stale.

### 3. `/health`

```json
{"status":"ok"}
```

### 4. `/coverage`

```json
{"hormuz":{"state":"NO_TERRESTRIAL_COVERAGE","frames":0,"last_frame_utc":null},"india_west_coast":{"state":"NO_TERRESTRIAL_COVERAGE","frames":0,"last_frame_utc":null},"malacca_singapore":{"state":"COVERED","frames":23,"last_frame_utc":"2026-07-10T16:47:09.739764+00:00"}}
```
Matches the documented, empirically-verified AIS coverage reality (docs/03) — no regression.

### 5–7. `/risk/hormuz` (post-fix, fresh container)

```json
{"corridor":"hormuz","timestamp":"2026-07-10T16:50:14.665763Z","probability":0.04978972032944846,"beta0":-3.0,"weights":{"kinetic":0.4,"density":0.25,"sanctions":0.15,"weather":0.1,"freight":0.1},"features":{"kinetic":0.0,"density":0.0,"sanctions":0.0,"weather":0.0,"freight":0.38343927384969534},"contributions":{"kinetic":0.0,"density":0.0,"sanctions":0.0,"weather":0.0,"freight":0.05112523651329271},"feature_states":{"kinetic":"LIVE","density":"NO_TERRESTRIAL_COVERAGE","sanctions":"STUB","weather":"LIVE","freight":"LIVE"}}
```
- `weather`: `feature_states.weather == "LIVE"`, `features.weather == 0.0` — correct: real Hormuz sea state is calm right now (see log line below, 0.62m, well under the 4.0m threshold).
- `freight`: `feature_states.freight == "LIVE"`, `features.freight == 0.383` — a genuine nonzero live reading (see log line below).
- `sanctions`: `feature_states.sanctions == "STUB"` — correctly still honest, `OPENSANCTIONS_API_KEY` remains unset.

### 8. `/scenario/hormuz`, `/reroute/hormuz` — no regression

```json
{"corridor":"hormuz","disruption_factor":0.3, ... ,"crude_price_rise_pct":30.0,"price_sensitivity":1.0,"brent_baseline_usd_bbl":69.56}
```
6 reroute options returned, sorted descending by score (0.7976 → 0.2044), `Merey` pinned at `grade_match: 0.0` as designed. Both endpoints behave identically to the pre-existing Phase 1/2 baseline — this session's changes didn't touch scenario/reroute code, and this confirms it.

### 9. Backend logs — connector fetch confirmation

```
api-1  | 2026-07-10 16:50:13,789 INFO [app.ingestion.weather] [OpenMeteo] wave_height_max=0.62m -> X_weather=0
api-1  | 2026-07-10 16:50:14,665 INFO [app.ingestion.freight] [FRED] WPU301301 latest=179.68 baseline=169.91 deviation=5.8% -> X_freight=0.383
```
No errors, no tracebacks, no 429s in the surrounding log window. The FRED numbers (latest 179.68, baseline avg 169.91) match the raw observations independently pulled straight from FRED during Task 2's design phase (179.679, 171.037, 168.470, 170.213 → avg 169.907), confirming the connector's math end-to-end against real data, not a mock.

### 10. Frontend

```
$ curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000/
HTTP 200
```

**Limitation, disclosed rather than glossed over:** a full browser screenshot of the Risk panel (confirming "Sea state (Open-Meteo)"/"Freight stress (FRED)" render without the STUB badge while "Sanctions exposure (OpenSanctions)" still shows it) was not captured — this session's browser preview tooling insists on starting its own dev server, which collided with the Docker-bound port 3000 rather than attaching to the already-running container. Reconfiguring ports to work around this was judged not worth the disruption for this check. In its place: Task 4's independent code reviewer traced the exact rendering conditional (`state === "STUB" ? " — STUB" : ""` in `RiskPanel.tsx`) against the live `feature_states` values confirmed in section 5–7 above (`weather: "LIVE"`, `freight: "LIVE"`, `sanctions: "STUB"`) and confirmed the logic produces the correct visible outcome. This is a code-level proof of the same claim, not a substitute screenshot — flagged as a real gap if a demo-day visual confirmation is later required.

## Deviations from the original prompt (flagged, not silently substituted)

- **Step 0 depth:** user explicitly chose "light re-check" over a full cold `docker-compose down -v` rebuild + sustained 10-minute GDELT-burst test, given the existing `docs/PHASE1_VERIFICATION_REPORT.md` (2026-07-09) already carried genuine raw evidence. This report's checks 3–9 constitute that light re-check.
- **Sanctions (OpenSanctions):** left as an honest `STUB`, not built — `OPENSANCTIONS_API_KEY` is empty in `backend/.env`, per explicit user direction and the project's own "never fake live data" rule.
- **Freight series:** FRED's BCTI/BDI are not available as FRED series (independently verified live on 2026-07-10) — substituted `WPU301301`, disclosed in `docs/02`/`docs/04`/`Readme.md`, not silently swapped in without explanation.
- **`tests/test_gdelt.py`:** pre-existing broken (uncollectable) test file, unrelated to this session's work, left unfixed and explicitly flagged above rather than silently excluded without comment.
