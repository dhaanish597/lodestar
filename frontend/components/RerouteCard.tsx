// frontend/components/RerouteCard.tsx
"use client";

import type { RerouteOption } from "@/lib/types";

// HARDCODED — proves the UI pipe end to end. Phase 2 replaces this with a live
// GET /reroute/{corridor} ranked by the MCDM engine (docs/04 §C).
const HARDCODED_REROUTES: RerouteOption[] = [
  {
    source_grade: "Urals",
    origin: "Russia",
    api_gravity: 31.0,
    sulfur_pct: 1.3,
    landed_cost_usd_bbl: 78.5,
    voyage_days: 25,
    grade_match: 1.0,
    congestion_penalty: 0.1,
    score: 0.81,
    best_fit_refineries: ["RIL Jamnagar", "Nayara Vadinar"],
  },
  {
    source_grade: "Bonny Light",
    origin: "W. Africa",
    api_gravity: 35.0,
    sulfur_pct: 0.2,
    landed_cost_usd_bbl: 84.0,
    voyage_days: 27,
    grade_match: 1.0,
    congestion_penalty: 0.15,
    score: 0.74,
    best_fit_refineries: ["PSU refiners"],
  },
  {
    source_grade: "Merey",
    origin: "Venezuela",
    api_gravity: 16.0,
    sulfur_pct: 2.5,
    landed_cost_usd_bbl: 61.0,
    voyage_days: 47,
    grade_match: 0.0,
    congestion_penalty: 0.2,
    score: 0.22,
    best_fit_refineries: ["RIL Jamnagar (coking only)"],
  },
];

export default function RerouteCard() {
  return (
    <div className="panel">
      <h2>Ranked reroute options (hardcoded, Phase 2 wires the MCDM engine)</h2>
      <ol style={{ paddingLeft: 18, fontSize: 14 }}>
        {HARDCODED_REROUTES.map((r) => (
          <li key={r.source_grade} style={{ marginBottom: 10 }}>
            <strong>
              {r.source_grade} ({r.origin})
            </strong>{" "}
            — score {r.score.toFixed(2)}
            <div style={{ opacity: 0.8 }}>
              ${r.landed_cost_usd_bbl}/bbl · {r.voyage_days}d voyage · grade_match {r.grade_match} ·{" "}
              {r.best_fit_refineries.join(", ")}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
