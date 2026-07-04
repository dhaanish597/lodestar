// frontend/app/page.tsx
"use client";

import { useState } from "react";
import MapDeck from "@/components/MapDeck";
import RiskPanel from "@/components/RiskPanel";
import ScenarioCard from "@/components/ScenarioCard";
import RerouteCard from "@/components/RerouteCard";
import { useVesselStream } from "@/lib/ws";
import type { ScenarioInputs } from "@/lib/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/vessels";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const DEFAULT_SCENARIO_INPUTS: ScenarioInputs = {
  disruption_factor: 0.3,
  substitution_rate: 0.2,
  hormuz_share: 0.45,
  spr_fill_pct: 0.64,
  cpi_sensitivity: 0.35,
  cad_sensitivity: 0.35,
};

export default function Page() {
  const vessels = useVesselStream(WS_URL);
  const [scenarioInputs, setScenarioInputs] = useState<ScenarioInputs>(DEFAULT_SCENARIO_INPUTS);

  return (
    <main style={{ display: "grid", gridTemplateColumns: "1fr 380px", width: "100vw", height: "100vh" }}>
      <MapDeck vessels={vessels} />
      <aside style={{ overflowY: "auto", padding: 16, background: "#0f131c" }}>
        <RiskPanel apiUrl={API_URL} />
        <ScenarioCard apiUrl={API_URL} inputs={scenarioInputs} onChange={setScenarioInputs} />
        <RerouteCard apiUrl={API_URL} disruptionFactor={scenarioInputs.disruption_factor} />
      </aside>
    </main>
  );
}
