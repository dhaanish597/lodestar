"use client";

import { useEffect, useState, useRef } from "react";
import type { Vessel } from "./types";

export function useVesselStream(url: string): Vessel[] {
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const msgCount = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;
    msgCount.current = 0;

    function connect() {
      if (cancelled) return;
      console.log("[WS hop-e] Connecting to", url);
      socket = new WebSocket(url);

      socket.onopen = () => {
        console.log("[WS hop-e] ✓ WebSocket OPEN");
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as Vessel[];
          msgCount.current += 1;

          // --- HOP (e): frontend message received ---
          if (msgCount.current === 1) {
            const sample = data.length > 0 ? data[0] : null;
            console.log(
              `[WS hop-e] ✓ FIRST message: ${data.length} vessels`,
              sample ? `  first=[${sample.lat.toFixed(3)}, ${sample.lon.toFixed(3)}]` : "  (empty array)",
            );
          } else if (msgCount.current % 10 === 0) {
            console.log(`[WS hop-e] Message #${msgCount.current}: ${data.length} vessels`);
          }

          setVessels(data);
        } catch {
          // ignore malformed frame
        }
      };

      socket.onclose = () => {
        console.log("[WS hop-e] Socket closed, reconnecting in 2s…");
        if (!cancelled) setTimeout(connect, 2000);
      };

      socket.onerror = (err) => {
        console.error("[WS hop-e] Socket error", err);
        socket?.close();
      };
    }

    connect();
    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [url]);

  return vessels;
}
