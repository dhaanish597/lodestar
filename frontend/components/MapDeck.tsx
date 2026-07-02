"use client";

import DeckGL from "@deck.gl/react";
import { ScatterplotLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMemo, useRef, useEffect } from "react";
import type { Vessel } from "@/lib/types";

const MAPLIBRE_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

const HORMUZ_VIEW = {
  longitude: 56.25,
  latitude: 26.3,
  zoom: 7,
  pitch: 0,
  bearing: 0,
};

export default function MapDeck({ vessels }: { vessels: Vessel[] }) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    mapRef.current = new maplibregl.Map({
      container: mapContainer.current,
      style: MAPLIBRE_STYLE,
      center: [HORMUZ_VIEW.longitude, HORMUZ_VIEW.latitude],
      zoom: HORMUZ_VIEW.zoom,
      interactive: false,
    });
    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  const layers = useMemo(
    () => [
      new ScatterplotLayer<Vessel>({
        id: "vessels",
        data: vessels,
        getPosition: (v) => [v.lon, v.lat],
        getRadius: 400,
        getFillColor: (v) => (v.signal_lost ? [255, 140, 0, 200] : [0, 200, 255, 200]),
        pickable: true,
      }),
    ],
    [vessels]
  );

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={mapContainer} style={{ position: "absolute", top: "0", right: "0", bottom: "0", left: "0" }} />
      <DeckGL
        viewState={HORMUZ_VIEW}
        controller={false}
        layers={layers}
        style={{ position: "absolute", top: "0", right: "0", bottom: "0", left: "0" }}
      />
    </div>
  );
}
