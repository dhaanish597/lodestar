# CLAUDE.md — Lodestar

> Auto-read by Claude Code at the start of every session. This file governs **how** to work.
> The `docs/` folder is the **source of truth** for domain facts, schemas, and constants.

---

## 0. READ THIS FIRST, EVERY SESSION

Before proposing a plan or writing any code, **read every file in `docs/`**:

- `docs/01_brief_and_strategy.md` — the problem, the operating principles, what to avoid.
- `docs/02_data_sources_and_schemas.md` — exact endpoints, auth, rate limits, gotchas, feed→feature map.
- `docs/03_build_plan_and_deliverables.md` — repo structure, the living build tracker, delegation, cut-list.
- `docs/04_model_assumptions_and_constants.md` — every model constant, weight, and assumption.

Rules for `docs/`:

- If new files appear in `docs/`, read those too. When in doubt, re-read the relevant doc.
- Re-read the relevant doc **before starting each build phase**.
- `docs/` wins over your own memory for any domain fact (endpoints, schemas, constants, crude-grade/refinery facts). This file (`CLAUDE.md`) wins for conventions and process.
- Never invent an endpoint, constant, or assumption. If it isn't in `docs/`, ask or mark it `STUB →` with a TODO.

### UPDATE THE DOCS AFTER EVERY ITERATION (non-negotiable)

At the end of **every** prompt/iteration, before you consider the task done, update the docs so they always reflect the true state of the codebase:

- `docs/03_build_plan_and_deliverables.md` — move every task you touched in the status column (⬜ → 🟨 → ✅ → ✂️). This is the living tracker; it must never lag the code.
- `docs/02_data_sources_and_schemas.md` — if you added/changed a connector, endpoint, auth, rate-limit handling, or the feed→feature map, reflect it here.
- `docs/04_model_assumptions_and_constants.md` — if you added/changed any constant, weight, threshold, or assumption, record it here (with its source or a TODO).
- `docs/01_brief_and_strategy.md` — update only if scope or a strategic decision actually changed.
- `README.md` — keep the run steps, env keys, service URLs, repo structure, and assumptions/limitations section current so a clean-machine `docker compose up` always matches reality.
- Add new `docs/` files if a new subsystem needs documenting, and note them in the tracker.

Do this as part of the same iteration — an untracked change is an incomplete change. Summarize what you updated at the end of your response.

---

## 1. What we're building (one line)

An anticipatory decision tool that ingests **live** maritime (AIS), commodity-price, and geopolitical signals, scores disruption probability per shipping corridor, simulates scenarios with **explicit, adjustable assumptions**, and generates executable crude-procurement rerouting recommendations on a live map. **Depth on Strait of Hormuz × India is the spine.** We are a *decision tool*, not a dashboard.

---

## 2. Operating principles (apply every time)

1. **Real data over mocks.** Live public feeds are the whole competitive edge. Never fabricate a feed when a real free source exists. If you must stub, label it `STUB →` and leave a TODO to swap in the real source.
2. **Defensibility first.** Assume industrial-software experts (Octave / Hexagon) will ask "is this real / how did you validate this?" Every number on screen must trace to a source or a stated assumption. Model assumptions are **visible and adjustable**, never hidden.
3. **Ship, don't gold-plate.** A working thin slice end-to-end beats one perfect component. **Vertical slices > horizontal layers.** Nothing in a later phase starts until the current phase's exit test passes.
4. **Map work to the rubric.** Innovation 25 · Business Impact 25 · Technical Excellence 20 · Scalability 15 · UX 15. When proposing anything, note which criterion it serves.
5. **Production-grade signals.** Last edition's jury penalized "thin LLM wrappers." Favor real multi-agent orchestration, clean repo structure, Dockerization, typed APIs, and measurable outputs.
6. **No secrets in code.** API keys come from `.env` / environment variables only. Never hardcode, never commit. `.env` is gitignored — keep it that way.

---

## 3. Tech stack (fixed — don't re-litigate)

- **Backend:** Python + FastAPI; agent orchestration with LangGraph; WebSockets for live AIS.
- **RAG:** Chroma over geopolitical/commodity/policy docs.
- **Frontend:** Next.js + deck.gl + **MapLibre** (free tiles — **no Mapbox token**). Charts via Recharts.
- **Packaging:** Docker + docker-compose (api · web · chroma · redis). One-command local run for the demo.

---

## 4. The spine (must run live on stage)

Real Hormuz AIS → corridor risk score (explainable) → macro cascade (visible sliders) → ranked executable reroute plan → on the map → signal→recommendation latency badge.

---

## 5. The three engines — DETERMINISTIC on purpose

Policymakers need auditability, not a black box. **LLM/agents reason about and narrate the outputs; they never replace the math.**

1. **Risk** — sigmoid + weighted features, returns a **per-feature contribution breakdown** (drives the stacked bar; interpretability is a scoring point).
2. **Scenario cascade** — 5 steps, **every assumption exposed as an adjustable parameter** wired to a slider. No hidden constants.
3. **Reroute (MCDM)** — constrained by the `grade_match` matrix (API gravity + sulfur). Grade compatibility is a **hard input**, not a tiebreaker.

Constants and weights for all three live in `docs/04_model_assumptions_and_constants.md`.

---

## 6. Repo structure

Follow §04 of `docs/03_build_plan_and_deliverables.md` exactly (`backend/app/{ingestion,engine,agents,rag,api}`, `frontend/{app,components,lib}`, `docker-compose.yml`, `README.md`). A legible monorepo + typed contracts + one-command run are themselves Technical Excellence points.

---

## 7. Conventions

- **Complete, runnable files** — never fragments. Put the file path as a header comment when showing code.
- **Typed contracts everywhere** — Pydantic on the backend (`Vessel`, `RiskScore`, `Scenario`, `RerouteOption`), typed payloads over the wire. Define the contract once; everything builds against it.
- **Plan before big changes.** Propose a short plan and wait for approval before large multi-file work.
- **Commit in logical chunks** with clear messages. `.env` and secrets never enter git.
- **Stubs are always labelled** `STUB →` with a TODO naming the real source.
- **AISStream specifics:** subscribe within 3s of connect; reconnect with backoff and resend subscription; dead-reckoning rule — if a position is >2h stale, extrapolate and flag `signal_lost` in the risk engine.
- **Rate limits:** Alpha Vantage is 25 req/day — cache (once/hour), never call on page load. GDELT only covers the last 90 days.

---

## 8. Build phases (exit tests)

- **P1 Spine:** real tankers move on the map and a corridor shows a live %.
- **P2 Engines:** dragging the disruption-% slider changes the cascade and re-ranks reroutes.
- **P3 Agents:** the orchestrator emits a cited, agent-narrated recommendation; latency badge shows a real number.
- **P4 Package:** `docker compose up` runs the whole system from a clean checkout.

---

## 9. Cut-list (degrade in THIS order if behind — don't improvise)

1. Malacca + Bab-el-Mandeb depth → keep the code path, Hormuz only.
2. FRED freight feed → static stub.
3. OpenSanctions live → pre-screened static list.
4. LangGraph → keep the agents but run them sequentially if the graph is flaky.
5. (See §12 of the build plan for the rest.)

---

## 10. What to avoid

- Generic "AI dashboard" framing — we are a decision tool.
- Overscoping — depth on Hormuz + India, not every corridor/refinery.
- Claiming predictive accuracy we can't show — the scenario engine is a transparent, assumption-driven what-if tool.
- Reproducing copyrighted source text — paraphrase and cite.