"use client";

import { useEffect, useState } from "react";
import type { Vessel } from "./types";

export function useVesselStream(url: string): Vessel[] {
  const [vessels, setVessels] = useState<Vessel[]>([]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(url);
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as Vessel[];
          setVessels(data);
        } catch {
          // ignore malformed frame
        }
      };
      socket.onclose = () => {
        if (!cancelled) setTimeout(connect, 2000);
      };
      socket.onerror = () => socket?.close();
    }

    connect();
    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [url]);

  return vessels;
}
