// frontend/components/RiskPanel.tsx
"use client";

import { useEffect, useState } from "react";
import type { RiskScore } from "@/lib/types";

const FEATURE_LABELS: Record<string, string> = {
  kinetic: "Kinetic news (GDELT)",
  density: "Vessel density anomaly (AIS)",
  sanctions: "Sanctions exposure (OpenSanctions)",
  weather: "Sea state (Open-Meteo)",
  freight: "Freight stress (FRED)",
};

export default function RiskPanel({ apiUrl }: { apiUrl: string }) {
  const [risk, setRisk] = useState<RiskScore | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const resp = await fetch(`${apiUrl}/risk/hormuz`);
        if (resp.ok && !cancelled) {
          setRisk(await resp.json());
        }
      } catch {
        // network hiccup, retry on next tick
      }
    }
    poll();
    const interval = setInterval(poll, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [apiUrl]);

  if (!risk) {
    return <div className="panel">Loading corridor risk…</div>;
  }

  return (
    <div className="panel">
      <h2 style={{ textTransform: "capitalize" }}>{risk.corridor.replace(/_/g, " ")} — Disruption Probability</h2>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ fontSize: "2.5rem", fontWeight: 700 }}>{(risk.probability * 100).toFixed(1)}%</div>
        {risk.feature_states?.density === "NO_TERRESTRIAL_COVERAGE" && (
          <div style={{
            fontSize: 10,
            fontWeight: "bold",
            color: "#00ff9d",
            background: "rgba(0, 255, 157, 0.1)",
            border: "1px solid rgba(0, 255, 157, 0.5)",
            borderRadius: 4,
            padding: "4px 8px",
            letterSpacing: 0.5,
          }}>
            AIS: NO TERRESTRIAL RECEIVERS IN REGION<br />KINETIC SIGNAL LIVE
          </div>
        )}
      </div>
      <div style={{ marginTop: 12 }}>
        {Object.entries(risk.contributions).map(([feature, contribution]) => {
          const state = risk.feature_states?.[feature];
          const excluded = state === "NO_TERRESTRIAL_COVERAGE" || state === "WARMING_UP";
          return (
            <div key={feature} style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 12, opacity: 0.8 }}>
                {FEATURE_LABELS[feature] ?? feature}
                {state === "STUB" ? " — STUB" : ""}
              </div>
              {excluded ? (
                <div
                  style={{
                    fontSize: 11,
                    color: "#ffb04d",
                    background: "#2a2116",
                    border: "1px solid #5c4520",
                    borderRadius: 4,
                    padding: "2px 6px",
                    display: "inline-block",
                  }}
                >
                  {state === "NO_TERRESTRIAL_COVERAGE"
                    ? "KNOWN SENSOR GAP: EXCLUDED FROM ALGORITHM"
                    : "AIS: WARMING UP — EXCLUDED FROM SCORE"}
                </div>
              ) : (
                <div style={{ background: "#1c2330", borderRadius: 4, overflow: "hidden", height: 8 }}>
                  <div
                    style={{
                      width: `${Math.min(contribution / risk.weights[feature], 1) * 100}%`,
                      background: "#00c8ff",
                      height: "100%",
                    }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
