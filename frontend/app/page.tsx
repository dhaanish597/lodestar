"use client";

import MapDeck from "@/components/MapDeck";
import { useVesselStream } from "@/lib/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/vessels";

export default function Page() {
  const vessels = useVesselStream(WS_URL);

  return (
    <main style={{ width: "100vw", height: "100vh" }}>
      <MapDeck vessels={vessels} />
    </main>
  );
}
