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

  return (
    <div className="panel">
      <h2>Ranked reroute options</h2>
      <ol style={{ paddingLeft: 18, fontSize: 14 }}>
        {reroutes.map((r) => (
          <li key={r.source_grade} style={{ marginBottom: 10 }}>
            <strong>
              {r.source_grade} ({r.origin})
            </strong>{" "}
            — score {r.score.toFixed(2)}
            <div style={{ opacity: 0.8 }}>
              ${r.landed_cost_usd_bbl.toFixed(2)}/bbl · {r.voyage_days}d voyage · grade_match {r.grade_match} ·{" "}
              {r.best_fit_refineries.join(", ")}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
