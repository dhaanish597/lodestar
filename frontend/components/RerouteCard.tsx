// frontend/components/RerouteCard.tsx
"use client";

import { useEffect, useState } from "react";
import type { RerouteOption } from "@/lib/types";
import { useDebounce } from "@/lib/useDebounce";

export default function RerouteCard({ apiUrl, disruptionFactor }: { apiUrl: string; disruptionFactor: number }) {
  const [reroutes, setReroutes] = useState<RerouteOption[]>([]);
  const debouncedDisruption = useDebounce(disruptionFactor, 250);

  useEffect(() => {
    let cancelled = false;
    async function fetchReroutes() {
      try {
        const resp = await fetch(`${apiUrl}/reroute/hormuz?disruption_factor=${debouncedDisruption}`);
        if (resp.ok && !cancelled) {
          setReroutes(await resp.json());
        }
      } catch {
        // network hiccup, next slider move retries
      }
    }
    fetchReroutes();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, debouncedDisruption]);

  const leaderScore = reroutes[0]?.score ?? 0;

  return (
    <div className="panel">
      <h2>Ranked reroute options</h2>
      <ol style={{ paddingLeft: 18, fontSize: 14 }}>
        {reroutes.map((r, i) => (
          <li key={r.source_grade} style={{ marginBottom: 10 }}>
            <strong>
              {r.source_grade} ({r.origin})
            </strong>{" "}
            — score {r.score.toFixed(4)}
            {i > 0 && (
              <span style={{ opacity: 0.6 }}> (Δ {(r.score - leaderScore).toFixed(4)} vs. leader)</span>
            )}
            <div style={{ background: "#1c2330", borderRadius: 4, overflow: "hidden", height: 6, marginTop: 4 }}>
              <div
                style={{
                  width: `${leaderScore > 0 ? Math.max((r.score / leaderScore) * 100, 0) : 0}%`,
                  background: i === 0 ? "#00ff9d" : "#00c8ff",
                  height: "100%",
                }}
              />
            </div>
            <div style={{ opacity: 0.8, marginTop: 2 }}>
              ${r.landed_cost_usd_bbl.toFixed(2)}/bbl · {r.voyage_days}d voyage · grade_match {r.grade_match} ·{" "}
              {r.best_fit_refineries.join(", ")}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
