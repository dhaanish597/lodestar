// frontend/components/RiskPanel.tsx
"use client";

import { useEffect, useState } from "react";
import type { RiskScore } from "@/lib/types";

const FEATURE_LABELS: Record<string, string> = {
  kinetic: "Kinetic news (GDELT)",
  density: "Vessel density anomaly (AIS)",
  sanctions: "Sanctions exposure — STUB",
  weather: "Sea state — STUB",
  freight: "Freight stress — STUB",
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
      <h2>Strait of Hormuz — Disruption Probability</h2>
      <div style={{ fontSize: "2.5rem", fontWeight: 700 }}>{(risk.probability * 100).toFixed(1)}%</div>
      <div style={{ marginTop: 12 }}>
        {Object.entries(risk.contributions).map(([feature, contribution]) => (
          <div key={feature} style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 12, opacity: 0.8 }}>{FEATURE_LABELS[feature] ?? feature}</div>
            <div style={{ background: "#1c2330", borderRadius: 4, overflow: "hidden", height: 8 }}>
              <div
                style={{
                  width: `${Math.min(contribution / risk.weights[feature], 1) * 100}%`,
                  background: "#00c8ff",
                  height: "100%",
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
