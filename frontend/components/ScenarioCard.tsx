// frontend/components/ScenarioCard.tsx
"use client";

import type { Scenario } from "@/lib/types";

// HARDCODED — proves the UI pipe end to end. Phase 2 replaces this with a live
// POST to a /scenario endpoint driven by slider state (see docs/04 §B).
const HARDCODED_SCENARIO: Scenario = {
  corridor: "hormuz",
  disruption_factor: 0.3,
  substitution_rate: 0.2,
  hormuz_share: 0.45,
  india_imports_mbd: 4.7,
  supply_gap_mbd: 0.51,
  utilization_drop_pct: 0.06,
  spr_fill_pct: 0.64,
  days_cover_remaining: 9.5,
  cpi_sensitivity: 0.35,
  cpi_delta_pp: 0.24,
  gdp_drag_bps: 8.1,
  cad_sensitivity: 0.35,
  cad_widening_pct_gdp: 0.17,
};

export default function ScenarioCard() {
  const s = HARDCODED_SCENARIO;
  return (
    <div className="panel">
      <h2>Scenario — 30% disruption (hardcoded, Phase 2 wires sliders)</h2>
      <ul style={{ listStyle: "none", padding: 0, fontSize: 14, lineHeight: 1.8 }}>
        <li>Supply gap: {s.supply_gap_mbd.toFixed(2)} mb/d</li>
        <li>Refinery utilization drop: {(s.utilization_drop_pct * 100).toFixed(1)}%</li>
        <li>SPR + commercial days cover: {s.days_cover_remaining.toFixed(1)} days</li>
        <li>CPI impact: +{s.cpi_delta_pp.toFixed(2)} pp</li>
        <li>GDP drag: {s.gdp_drag_bps.toFixed(1)} bps</li>
        <li>CAD widening: {(s.cad_widening_pct_gdp * 100).toFixed(2)}% of GDP</li>
      </ul>
    </div>
  );
}
