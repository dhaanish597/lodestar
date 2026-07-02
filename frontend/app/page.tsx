// frontend/app/page.tsx
"use client";

import MapDeck from "@/components/MapDeck";
import RiskPanel from "@/components/RiskPanel";
import ScenarioCard from "@/components/ScenarioCard";
import RerouteCard from "@/components/RerouteCard";
import { useVesselStream } from "@/lib/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/vessels";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Page() {
  const vessels = useVesselStream(WS_URL);

  return (
    <main style={{ display: "grid", gridTemplateColumns: "1fr 380px", width: "100vw", height: "100vh" }}>
      <MapDeck vessels={vessels} />
      <aside style={{ overflowY: "auto", padding: 16, background: "#0f131c" }}>
        <RiskPanel apiUrl={API_URL} />
        <ScenarioCard />
        <RerouteCard />
      </aside>
    </main>
  );
}
