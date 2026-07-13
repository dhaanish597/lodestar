# Phase 3 (Agents) — Evidence-Based Verification Report

**Date:** 2026-07-13
**Scope:** `docs/superpowers/plans/2026-07-12-phase3-agents.md`, all 10 required tasks + final whole-branch review fix round.
**Method:** Every claim below is backed by raw command output, raw HTTP responses, or raw log lines, pasted verbatim — per this project's explicit instruction that a summary sentence is not evidence.

---

## 1. Full test suite output (post-build, fresh)

Rebuilt Docker images `--no-cache`, restarted the stack, confirmed the container filesystem was not stale (`docker-compose exec api grep` for post-fix symbols in `llm_client.py`/`sanctions.py`/`logistics_reading.py`/`graph.py` — all present). Ran the full suite locally (the actual test invocation — `Dockerfile` never `COPY`s `tests/` into the image, confirmed by `0 items collected` when run inside the container):

```
$ cd backend && python -m pytest --ignore=tests/test_gdelt.py -v
...
collected 108 items

tests/test_agent_parity.py::test_graph_and_sequential_produce_identical_engine_output PASSED
tests/test_aisstream.py::test_store_upsert_and_snapshot_returns_latest_per_mmsi PASSED
[... 108 lines, all PASSED — full raw output in session transcript ...]
tests/test_ws_vessels.py::test_ws_vessels_streams_current_snapshot PASSED

================== 108 passed, 1 warning in 64.96s (0:01:04) ==================
```

The one warning is a pre-existing, unrelated `PendingDeprecationWarning` from `starlette`'s multipart parser — not introduced by this phase.

`tests/test_gdelt.py` reconfirmed broken, same pre-existing cause (unrelated to this phase, `gdelt.py` was refactored to a Redis-backed poller in an earlier phase and the test still imports the old `GdeltCache` class):

```
$ cd backend && python -m pytest tests/test_gdelt.py -v
...
ImportError while importing test module 'tests\test_gdelt.py'.
tests\test_gdelt.py:5: in <module>
    from app.ingestion.gdelt import GdeltCache
E   ImportError: cannot import name 'GdeltCache' from 'app.ingestion.gdelt'
=========================== short test summary info ===========================
ERROR tests/test_gdelt.py
1 error in 0.74s
```

## 2. Graph vs. sequential parity

**Deterministic proof (mocked HTTP boundary, identical fixed input, `hormuz`/`disruption_factor=0.5`/`substitution_rate=0.2`/`hormuz_share=0.45`)** — this is the rigorous version: it eliminates the wall-clock/AIS-warmup confound a live two-process comparison has (see below).

```
=== FIELD-BY-FIELD DIFF (engine fields only) ===
x_kinetic: MATCH
brent_price_usd_bbl: MATCH
market_volatility_label: MATCH
price_spike_detected: MATCH
x_density: MATCH
density_state: MATCH
x_sanctions: MATCH
sanctions_state: MATCH
x_weather: MATCH
scenario: MATCH
risk: MATCH
reroutes: MATCH

All engine fields identical: True
```

Full side-by-side payloads (both paths, identical mocked deps, `risk.py`'s `datetime` frozen so `RiskScore.timestamp` doesn't confound the comparison):

```json
=== GRAPH RESULT (excerpt) ===
"risk": {"probability": 0.04742587317756678, "contributions": {"kinetic": 0.0, "density": 0.0, "sanctions": 0.0, "weather": 0.0, "freight": 0.0}, "feature_states": {"kinetic": "LIVE", "density": "WARMING_UP", "sanctions": "WARMING_UP", "weather": "LIVE", "freight": "STUB"}}
"reroutes": [{"source_grade": "Urals", "score": 0.7991, ...}, {"source_grade": "Bonny Light", "score": 0.5221, ...}, ...]

=== SEQUENTIAL RESULT (excerpt) ===
"risk": {"probability": 0.04742587317756678, "contributions": {"kinetic": 0.0, "density": 0.0, "sanctions": 0.0, "weather": 0.0, "freight": 0.0}, "feature_states": {"kinetic": "LIVE", "density": "WARMING_UP", "sanctions": "WARMING_UP", "weather": "LIVE", "freight": "STUB"}}
"reroutes": [{"source_grade": "Urals", "score": 0.7991, ...}, {"source_grade": "Bonny Light", "score": 0.5221, ...}, ...]
```
(Full JSON for both — 12 fields each — captured verbatim in the session transcript; every field byte-identical.)

**Live-server proof (two real Docker containers, same image, one `AGENT_MODE=graph` (default) on port 8000, one `AGENT_MODE=sequential` on port 8001, identical query params):**

```
$ curl -s "http://localhost:8000/recommendation/hormuz?disruption_factor=0.5&substitution_rate=0.2&hormuz_share=0.45"
{"corridor":"hormuz","risk":{...,"probability":0.050397904443587445,...,"feature_states":{"kinetic":"LIVE","density":"NO_TERRESTRIAL_COVERAGE","sanctions":"NO_TERRESTRIAL_COVERAGE","weather":"LIVE","freight":"LIVE"}},"scenario":{...},"reroutes":[{"source_grade":"Urals","score":0.7977,...},...],"agent_mode":"graph"}

$ curl -s "http://localhost:8001/recommendation/hormuz?disruption_factor=0.5&substitution_rate=0.2&hormuz_share=0.45"
{"corridor":"hormuz","risk":{...,"probability":0.050397904443587445,...,"feature_states":{"kinetic":"LIVE","density":"WARMING_UP","sanctions":"WARMING_UP","weather":"LIVE","freight":"LIVE"}},"scenario":{...},"reroutes":[{"source_grade":"Urals","score":0.7977,...},...],"agent_mode":"sequential"}
```

Field-by-field diff of the two full live payloads:
```
.agent_mode: GRAPH='graph'  SEQUENTIAL='sequential'
.density_state: GRAPH='NO_TERRESTRIAL_COVERAGE'  SEQUENTIAL='WARMING_UP'
.risk.feature_states.density: GRAPH='NO_TERRESTRIAL_COVERAGE'  SEQUENTIAL='WARMING_UP'
.risk.feature_states.sanctions: GRAPH='NO_TERRESTRIAL_COVERAGE'  SEQUENTIAL='WARMING_UP'
.risk.timestamp: GRAPH='2026-07-13T06:50:14.931389Z'  SEQUENTIAL='2026-07-13T06:51:03.578962Z'
.sanctions_state: GRAPH='NO_TERRESTRIAL_COVERAGE'  SEQUENTIAL='WARMING_UP'
```

**Honest explanation of the density/sanctions difference**: this is *not* a graph-vs-sequential logic bug — both containers run the identical `compute_logistics_reading()` function. It's an artifact of comparing two independently-started processes: the `sequential`-mode container's AIS subscription had been running less than `COVERAGE_WINDOW_SECONDS` (15s) when the request landed, so its `CoverageMonitor` correctly reports `WARMING_UP`; the longer-running `graph`-mode container had already crossed that window with zero Hormuz frames (the real, previously-documented AIS coverage gap), so it correctly reports `NO_TERRESTRIAL_COVERAGE`. Every other field — `probability` (identical down to the 15th decimal), every `contributions` value, the full `scenario` block, and all 6 `reroutes` entries with exact scores — matches exactly between the two live processes despite this. The deterministic mocked test above (§2, top) is the controlled version that removes this confound entirely and proves `density_state`/`sanctions_state` also match when given identical input.

## 3. Narration-matches-engine proof

`NVIDIA_API_KEY` is still empty (user has not yet added a key — confirmed: `grep -c '^NVIDIA_API_KEY=.\+' backend/.env` → `0`), so no live narrated example exists yet; every live narration field today is the honest STUB string (see §4/§6 raw payloads above — `"recommendation_narration":"STUB — LLM narration unavailable, NVIDIA_API_KEY not configured."`). This is the correct, honest behavior, not a gap.

To prove narration *would* cite the real numbers once a key is added, this is a direct capture of the **exact prompt text** `run_orchestrator_node()` hands to the LLM, with a stub LLM client that records the prompt instead of calling out, next to the independently-computed real engine output for the same inputs:

```
=== compute_risk() RAW OUTPUT (engine, deterministic) ===
probability=0.0573512009373495
contributions={'kinetic': 0.168, 'density': 0.025, 'sanctions': 0.0075, 'weather': 0.0, 'freight': 0.0}

=== rank_reroutes() RAW OUTPUT (engine, deterministic), top 2 ===
[0] Urals: score=0.7991 landed_cost=101.8 grade_match=1.0
[1] Bonny Light: score=0.5221

=== EXACT user_prompt handed to the LLM by run_orchestrator_node() ===
Corridor risk: 5.7% (kinetic=0.168, density=0.025, sanctions=0.007, weather=0.000, freight=0.000)
Top-ranked alternative: Urals (Russia), score 0.7991, landed cost $101.80/bbl, grade_match 1.0, 25.0d voyage.
Runner-up: Bonny Light, score 0.5221.

=== result['risk']['probability'] as returned in AgentState ===
0.0573512009373495
=== Matches independently-computed compute_risk().probability? ===
True
```

`5.7%` in the prompt is `0.0573512009373495` rounded (`{risk.probability:.1%}`); `kinetic=0.168` matches `contributions['kinetic']` exactly; the reroute figures (`Urals`, `0.7991`, `$101.80/bbl`, `grade_match 1.0`) match `rank_reroutes()`'s independently-computed output exactly. The LLM literally cannot narrate a different number than what's in this prompt — it only ever sees the real, already-computed values.

## 4. OpenSanctions proof — all three states, raw

**Live key verification** (done earlier this session, before any Phase 3 code existed, to confirm the key that changed mid-session actually works):
```
POST https://api.opensanctions.org/match/default
status: 200
body: {"responses":{"q1":{"status":200,"results":[],"total":{"value":0,"relation":"eq"},"query":{"id":null,"schema":"Vessel","properties":{}}}},"limit":5}
```
Confirmed the `Vessel` schema accepts `mmsi` directly (not just `imo`):
```
mmsi query status: 200
{"responses":{"q1":{"status":200,"results":[],"total":{"value":0,"relation":"eq"},"query":{"id":null,"schema":"Vessel","properties":{"mmsi":["273456789"]}}}},"limit":5}
```

**STUB state** (no key) and **LIVE state** (key + flagged vessel, mocked HTTP) and **coverage-inherited state** (key present, but no AIS-observed fleet) — all three, raw pytest:
```
$ cd backend && python -m pytest tests/test_sanctions.py::test_no_key_returns_zero_without_request tests/test_sanctions.py::test_flagged_ratio_computed_from_topics tests/test_logistics_reading.py::test_uncovered_ais_voids_sanctions_without_calling_the_api tests/test_routes.py::test_risk_hormuz_sanctions_live_screens_observed_fleet tests/test_routes.py::test_risk_hormuz_sanctions_inherits_coverage_void_state -v
...
tests/test_sanctions.py::test_no_key_returns_zero_without_request PASSED [ 20%]
tests/test_sanctions.py::test_flagged_ratio_computed_from_topics PASSED  [ 40%]
tests/test_logistics_reading.py::test_uncovered_ais_voids_sanctions_without_calling_the_api PASSED [ 60%]
tests/test_routes.py::test_risk_hormuz_sanctions_live_screens_observed_fleet PASSED [ 80%]
tests/test_routes.py::test_risk_hormuz_sanctions_inherits_coverage_void_state PASSED [100%]
======================== 5 passed, 1 warning in 7.41s =========================
```

**Live production state, real request, right now**: Hormuz's real, previously-documented AIS coverage gap means the *actual current* `/risk/hormuz` state is the coverage-inherited one, not a plain STUB — this is the more sophisticated, more honest of the two degraded states, and it's what's actually live:
```
$ curl -s http://localhost:8000/risk/hormuz
{"corridor":"hormuz",...,"features":{"kinetic":0.0,"density":0.0,"sanctions":0.0,"weather":0.0,"freight":0.38343927384969534},"contributions":{"kinetic":0.0,"density":0.0,"sanctions":0.0,"weather":0.0,"freight":0.0639065456416159},"feature_states":{"kinetic":"LIVE","density":"NO_TERRESTRIAL_COVERAGE","sanctions":"NO_TERRESTRIAL_COVERAGE","weather":"LIVE","freight":"LIVE"}}
```

## 5. RAG status proof — cut, documented

Raw diff (Task 9, commit `acc1155`):
```diff
diff --git a/docs/03_build_plan_and_deliverables.md b/docs/03_build_plan_and_deliverables.md
-| Chroma RAG over policy/geopolitics docs | Teammate | Innov | ⬜ |
+| Chroma RAG over policy/geopolitics docs | Teammate | Innov | ✂️ (cut Phase 3 — corpus never materialized, ... policy facts kept inline in agent system prompts instead, docs/04 §G) |

diff --git a/docs/04_model_assumptions_and_constants.md
+## G. RAG — cut this phase
+
+Chroma RAG over PPAC/EIA/IEA/ORF policy documents was cut for Phase 3 per
+the build plan's own cut-list (#5). The corpus (10-20 public PDFs/articles)
+never materialized — confirmed empty by directory search across the repo
+on 2026-07-12, no PDFs anywhere. ...

diff --git a/Readme.md
-| RAG | Chroma over public policy/geopolitics documents |
+| RAG | Cut Phase 3 — corpus never materialized (docs/04 §G); policy facts kept inline in agent prompts instead |
```
(Full diff: `git show acc1155 -- docs/03_build_plan_and_deliverables.md docs/04_model_assumptions_and_constants.md Readme.md`.)

## 6. Latency measurement

No prior latency baseline exists in the repo (`grep -rn latency docs/PHASE1_VERIFICATION_REPORT.md docs/PHASE2_WEATHER_FREIGHT_VERIFICATION_REPORT.md` → no matches) — the latency badge itself is still ⬜/not built (frontend, optional Task 11).

**Cold-cache, first request (real GDELT/EIA/AlphaVantage/Open-Meteo/FRED/NVIDIA-attempt network calls, freshly restarted container):**
```
$ time curl -s "http://localhost:8000/recommendation/hormuz?disruption_factor=0.5&..." → real 0m3.037s
$ time curl -s "http://localhost:8001/recommendation/hormuz?disruption_factor=0.5&..." (sequential mode) → real 0m3.873s
```

**Warm-cache, subsequent requests** (weather/freight/price TTL caches already populated — the realistic steady-state during a live demo):
```
=== /risk/hormuz (pre-agent baseline endpoint) x3 ===
real 0m0.092s / 0m0.077s / 0m0.076s
=== /recommendation/hormuz (graph, default) x3 ===
real 0m0.095s / 0m0.086s / 0m0.089s
```

**Assessment for the "seconds, not weeks" claim**: honestly, this is a mild regression from the pre-agent baseline (~80ms) on a cold cache (~3s), driven entirely by the sequential chain of live connector calls (GDELT/EIA/AlphaVantage/Open-Meteo/FRED, each with its own network round-trip) plus, once a key is added, an NVIDIA NIM call per node. On a warm cache it's indistinguishable from the baseline (~90ms) because every connector serves from its TTL cache. **This does not change the "seconds, not weeks" claim** — 3 seconds cold, under 100ms warm, both still land the demo's core message (a decision in seconds, not the weeks a manual process would take). Once `NVIDIA_API_KEY` is added, expect the cold-path number to grow further (4 real LLM calls, one per node) — that number isn't measured yet since no key exists to call with; re-measure after the key is added, before the actual demo.

## 7. Documentation updates

Task 9 diff (RAG cut) — see §5 above, full commit `acc1155`.

Task 10 diff (tracker sync — OpenSanctions/Risk-engine/LangGraph rows in `docs/03`, new `docs/04` §H, `Readme.md` env keys/repo-structure/service-table):
```diff
diff --git a/docs/03_build_plan_and_deliverables.md
-| OpenSanctions vessel screening | You | Innov | ⬜ |
+| OpenSanctions vessel screening | You | Innov | ✅ (live — SanctionsService screens observed AIS fleet by MMSI, ... wired into both GET /risk/{corridor} and the Logistics agent node so risk score and narration agree; inherits AIS coverage-void state when there's no fleet to screen) |
-| LangGraph orchestration (4 agents) | You | Tech/Innov | ⬜ |
+| LangGraph orchestration (4 agents) | You | Tech/Innov | ✅ (Market Intelligence, Logistics & Maritime, Macroeconomic Strategist, Executive Orchestrator; AGENT_MODE=graph default, =sequential fallback calling the identical node functions; GET /recommendation/{corridor}) |

diff --git a/docs/04_model_assumptions_and_constants.md
+## H. LLM wiring (Phase 3)
+
+Agent narration/classification uses NVIDIA NIM's OpenAI-compatible endpoint ...

diff --git a/Readme.md
+NVIDIA_API_KEY=            # free tier available, https://build.nvidia.com
+LLM_MODEL=nvidia/llama-3.1-nemotron-70b-instruct
+AGENT_MODE=graph
+| Agent recommendation | http://localhost:8000/recommendation/hormuz |
```
(Full diff: `git show d94aedc`.)

Final-review fix commit `97620cb` diff (dependency pinning, real parallel fan-out, README "parallel" wording correction, narration-label/comment/README polish): `git show 97620cb`.

---

## Known follow-ups (not blocking, disclosed)

1. **`backend/.env`'s `LLM_MODEL` line is stale.** It still reads `LLM_MODEL=claude-sonnet-5` (a pre-existing, never-wired hint from before this phase) instead of `nvidia/llama-3.1-nemotron-70b-instruct`. This is the real, gitignored `.env` — no code change touched it (correctly — agents only updated `.env.example`). Harmless today (`NVIDIA_API_KEY` is empty, so `LLMClient.has_key` is `False` regardless of `model`), but **when you add `NVIDIA_API_KEY`, also update this line**, or `LLMClient` will try to call NVIDIA's endpoint with an invalid model ID and every narration will silently degrade to the API-error STUB path instead of producing real text.
2. Cold-path latency with a real `NVIDIA_API_KEY` added is not yet measured (no key to test with). Re-measure before the demo.
3. Task 11 (frontend narration panel) is optional per the plan and not started — the agent pipeline is fully verified at the API level, not yet visible in the UI.
