// frontend/components/ScenarioCard.tsx
"use client";

import { useEffect, useState } from "react";
import type { Scenario, ScenarioInputs } from "@/lib/types";
import { useDebounce } from "@/lib/useDebounce";

const SLIDER_CONFIG: { key: keyof ScenarioInputs; label: string; min: number; max: number; step: number }[] = [
  { key: "disruption_factor", label: "Disruption", min: 0, max: 1, step: 0.01 },
  { key: "substitution_rate", label: "Substitution rate", min: 0, max: 1, step: 0.01 },
  { key: "hormuz_share", label: "Hormuz share of imports", min: 0.3, max: 0.6, step: 0.01 },
  { key: "spr_fill_pct", label: "SPR fill", min: 0, max: 1, step: 0.01 },
  { key: "cpi_sensitivity", label: "CPI sensitivity", min: 0.3, max: 0.4, step: 0.01 },
  { key: "cad_sensitivity", label: "CAD sensitivity", min: 0.2, max: 0.5, step: 0.01 },
];

export default function ScenarioCard({
  apiUrl,
  inputs,
  onChange,
}: {
  apiUrl: string;
  inputs: ScenarioInputs;
  onChange: (next: ScenarioInputs) => void;
}) {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const debouncedInputs = useDebounce(inputs, 250);

  useEffect(() => {
    let cancelled = false;
    async function fetchScenario() {
      const params = new URLSearchParams(
        Object.fromEntries(Object.entries(debouncedInputs).map(([k, v]) => [k, String(v)]))
      );
      try {
        const resp = await fetch(`${apiUrl}/scenario/hormuz?${params}`);
        if (resp.ok && !cancelled) {
          setScenario(await resp.json());
        }
      } catch {
        // network hiccup, next slider move retries
      }
    }
    fetchScenario();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, debouncedInputs]);

  return (
    <div className="panel">
      <h2>Scenario — macro cascade</h2>
      {SLIDER_CONFIG.map(({ key, label, min, max, step }) => (
        <div key={key} style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, opacity: 0.8, display: "flex", justifyContent: "space-between" }}>
            <span>{label}</span>
            <span>{inputs[key].toFixed(2)}</span>
          </label>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={inputs[key]}
            onChange={(e) => onChange({ ...inputs, [key]: Number(e.target.value) })}
            style={{ width: "100%" }}
          />
        </div>
      ))}
      {!scenario ? (
        <div>Loading cascade…</div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, fontSize: 14, lineHeight: 1.8 }}>
          <li>Supply gap: {scenario.supply_gap_mbd.toFixed(2)} mb/d</li>
          <li>Refinery utilization drop: {(scenario.utilization_drop_pct * 100).toFixed(1)}%</li>
          <li>SPR + commercial days cover: {scenario.days_cover_remaining.toFixed(1)} days</li>
          <li>Crude price rise: +{scenario.crude_price_rise_pct.toFixed(1)}%</li>
          <li>CPI impact: +{scenario.cpi_delta_pp.toFixed(2)} pp</li>
          <li>GDP drag: {scenario.gdp_drag_bps.toFixed(1)} bps</li>
          <li>CAD widening: {(scenario.cad_widening_pct_gdp * 100).toFixed(2)}% of GDP</li>
        </ul>
      )}
    </div>
  );
}
