"use client";

import DeckGL from "@deck.gl/react";
import { ScatterplotLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMemo, useRef, useEffect, useState } from "react";
import type { Vessel } from "@/lib/types";

const MAPLIBRE_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

const INITIAL_VIEW = {
  longitude: 56.25,
  latitude: 26.3,
  zoom: 6,
  pitch: 0,
  bearing: 0,
};

export default function MapDeck({ vessels }: { vessels: Vessel[] }) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  // Camera opens on Malacca/Singapore (the live demo spine) but is pannable — with multi-box AIS
  // subscriptions (see docs/03 "AIS coverage reality"), real vessels arrive
  // from other boxes too, but Hormuz/India are currently voids.
  const [viewState, setViewState] = useState(INITIAL_VIEW);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    mapRef.current = new maplibregl.Map({
      container: mapContainer.current,
      style: MAPLIBRE_STYLE,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
      zoom: INITIAL_VIEW.zoom,
      interactive: false, // deck.gl's controller drives the camera; maplibre just renders tiles
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
        // getRadius is in meters — at corridor zoom levels 400 m is < 1 px,
        // so without a pixel floor real vessels render invisibly.
        radiusMinPixels: 4,
        radiusMaxPixels: 16,
        getFillColor: (v) => (v.signal_lost ? [255, 140, 0, 200] : [0, 200, 255, 200]),
        pickable: true,
      }),
    ],
    [vessels]
  );

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={mapContainer} style={{ position: "absolute", top: "0", right: "0", bottom: "0", left: "0" }} />
      <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10, background: "rgba(15, 19, 28, 0.9)", padding: "8px 12px", borderRadius: 4, border: "1px solid #333", color: "#fff", display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: "12px", opacity: 0.8 }}>Verify live data: Malacca Strait</span>
        <button
          onClick={() => {
            const next = { ...INITIAL_VIEW, longitude: 103.8, latitude: 1.25, zoom: 7 };
            setViewState(next);
            mapRef.current?.jumpTo({ center: [next.longitude, next.latitude], zoom: next.zoom });
          }}
          style={{ background: "#00aaff", color: "#000", border: "none", padding: "4px 8px", borderRadius: 4, cursor: "pointer", fontSize: "12px", fontWeight: "bold" }}
        >
          View Live
        </button>
      </div>
      <DeckGL
        viewState={viewState}
        controller={true}
        onViewStateChange={({ viewState: vs }) => {
          const next = vs as typeof INITIAL_VIEW;
          setViewState(next);
          mapRef.current?.jumpTo({
            center: [next.longitude, next.latitude],
            zoom: next.zoom,
            bearing: next.bearing,
            pitch: next.pitch,
          });
        }}
        layers={layers}
        style={{ position: "absolute", top: "0", right: "0", bottom: "0", left: "0" }}
      />
    </div>
  );
}
