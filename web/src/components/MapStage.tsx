"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type {
  GeoJSONSource,
  LngLatBoundsLike,
  MapLayerMouseEvent,
  Map as MlMap,
  Marker,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import type { AisVessel } from "@/lib/aperium/client";
import type { Vessel } from "@/lib/feed/types";
import type { Geography } from "@/lib/geographies";
import { aisInGeography, sameShip, selectGeography, type ShipRef } from "@/store/tidemark";
import { useTidemark } from "./TidemarkProvider";

/** OpenFreeMap vector basemap: OpenStreetMap data, no API key. Attribution is rendered in HudToggle. */
const STYLE_URL = "https://tiles.openfreemap.org/styles/dark";
const WORKER_URL = "/maplibre/maplibre-gl-worker.mjs"; // copied by scripts/copy-maplibre-worker.mjs
const FONT = ["Noto Sans Regular"];
const COLORS = { land: "#211e19", water: "#0b1820", accent: "#f2a541", teal: "#8fd3ee", positive: "#8fd19e", text: "#e8eef3" };

/** Dash patterns cycled to animate the lanes (MapLibre "animate a line" technique). */
const DASH_SEQUENCE = [
  [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
  [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5],
];

type MapLibre = typeof import("maplibre-gl");
type Bounds = readonly [number, number, number, number];
type Padding = { top: number; right: number; bottom: number; left: number };

function lanesData(g: Geography): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: (["outbound", "inbound"] as const).map((dir) => ({
      type: "Feature",
      properties: { dir },
      geometry: { type: "LineString", coordinates: g.lanes[dir].map((p) => [...p]) },
    })),
  };
}

function gatesData(g: Geography): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: g.gates.map((l) => l.map((p) => [...p])) } },
    ],
  };
}

function portsData(g: Geography, counts: Record<string, number> | undefined): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: g.ports.map((p) => {
      const [[s, w], [n, e]] = p.bounds_lat_lon;
      const count = counts?.[p.id];
      return {
        type: "Feature",
        properties: { id: p.id, label: `${p.name.toUpperCase()}${count != null ? ` · ${count}` : ""}` },
        geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
      };
    }),
  };
}

/**
 * Padding that keeps the framed bbox clear of the glass overlays. The outcome card sits
 * bottom-left, so try reserving its width (left) or its height (bottom) and keep whichever
 * lets the map zoom in further.
 */
function overlayPaddings(container: HTMLElement): Padding[] {
  const c = container.getBoundingClientRect();
  const shell = container.closest(".shell") ?? document;
  const rect = (sel: string) => {
    const r = shell.querySelector(sel)?.getBoundingClientRect();
    return r && r.width > 0 && r.right > c.left && r.left < c.right && r.bottom > c.top && r.top < c.bottom ? r : null;
  };
  const top = rect(".ov-top");
  const panel = rect(".hud-panel");
  const card = rect(".outcome");
  const toggle = rect(".toggle");
  const base: Padding = {
    top: (top ? top.bottom - c.top : 0) + 16,
    right: (panel ? c.right - panel.left : 0) + 24,
    bottom: (toggle && toggle.top > c.top + c.height / 2 ? c.bottom - toggle.top : 0) + 16,
    left: 24,
  };
  if (!card) return [base];
  return [
    { ...base, left: card.right - c.left + 16 },
    { ...base, bottom: Math.max(base.bottom, c.bottom - card.top + 16) },
  ];
}

function frame(map: MlMap, bbox: Bounds, animate: boolean) {
  const bounds: LngLatBoundsLike = [[bbox[0], bbox[1]], [bbox[2], bbox[3]]];
  const { clientWidth: w, clientHeight: h } = map.getContainer();
  const cameras = overlayPaddings(map.getContainer())
    .filter((p) => w - p.left - p.right > 120 && h - p.top - p.bottom > 120)
    .map((padding) => map.cameraForBounds(bounds, { padding }))
    .filter((cam) => cam != null)
    .sort((a, b) => (b.zoom ?? 0) - (a.zoom ?? 0));
  const best = cameras[0] ?? map.cameraForBounds(bounds, { padding: 24 });
  if (!best) return;
  if (animate) map.flyTo({ ...best, duration: 1200, essential: false });
  else map.jumpTo(best);
}

export function MapStage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState<{ map: MlMap; ml: MapLibre } | null>(null);
  const geography = useTidemark(selectGeography);
  const geographyRef = useRef(geography);
  useEffect(() => {
    geographyRef.current = geography;
  }, [geography]);

  // Create the map once. maplibre-gl touches `window`, so load it client-side only.
  useEffect(() => {
    let disposed = false;
    let map: MlMap | null = null;
    (async () => {
      const ml = await import("maplibre-gl");
      if (disposed || !containerRef.current) return;
      ml.setWorkerUrl(WORKER_URL);
      const { bbox } = geographyRef.current;
      map = new ml.Map({
        container: containerRef.current,
        style: STYLE_URL,
        bounds: [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
        attributionControl: false,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        maxPitch: 0,
        renderWorldCopies: false,
      });
      map.touchZoomRotate.disableRotation();
      map.keyboard.disableRotation();
      map.on("load", () => {
        if (disposed || !map) return;
        addOverlayLayers(map);
        frame(map, geographyRef.current.bbox, false);
        setReady({ map, ml });
      });
    })();
    return () => {
      disposed = true;
      map?.remove();
    };
  }, []);

  return (
    <div className="map" ref={containerRef} role="region" aria-label={`Map of the ${geography.name}`}>
      {ready && <MapSync map={ready.map} />}
      {ready && <ShipMarkers map={ready.map} ml={ready.ml} />}
    </div>
  );
}

function addOverlayLayers(map: MlMap) {
  // Retint the basemap toward the HUD palette: warm land, deep blue water.
  map.setPaintProperty("background", "background-color", COLORS.land);
  map.setPaintProperty("water", "fill-color", COLORS.water);
  if (map.getLayer("water_name")) map.setPaintProperty("water_name", "text-color", "rgba(232,238,243,0.45)");

  const empty: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
  map.addSource("ports", { type: "geojson", data: empty, promoteId: "id" });
  map.addSource("gates", { type: "geojson", data: empty });
  map.addSource("lanes", { type: "geojson", data: empty });

  const selected = ["boolean", ["feature-state", "selected"], false] as const;
  map.addLayer({
    id: "ports-fill",
    type: "fill",
    source: "ports",
    paint: { "fill-color": COLORS.positive, "fill-opacity": ["case", [...selected], 0.2, 0.06] },
  });
  map.addLayer({
    id: "ports-line",
    type: "line",
    source: "ports",
    paint: {
      "line-color": COLORS.positive,
      "line-width": ["case", [...selected], 1.8, 1],
      "line-dasharray": [3, 2],
      "line-opacity": 0.7,
    },
  });
  map.addLayer({
    id: "gates",
    type: "line",
    source: "gates",
    paint: { "line-color": COLORS.text, "line-dasharray": [1, 3], "line-width": 1, "line-opacity": 0 },
  });
  for (const dir of ["inbound", "outbound"] as const) {
    map.addLayer({
      id: `lane-${dir}`,
      type: "line",
      source: "lanes",
      filter: ["==", ["get", "dir"], dir],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": dir === "outbound" ? COLORS.accent : COLORS.teal,
        "line-opacity": dir === "outbound" ? 0.85 : 0.4,
        "line-width": 3,
        "line-dasharray": DASH_SEQUENCE[0],
      },
    });
  }
  map.addLayer({
    id: "ports-label",
    type: "symbol",
    source: "ports",
    layout: {
      "text-field": ["get", "label"],
      "text-font": FONT,
      "text-size": 10,
      "text-letter-spacing": 0.08,
      "text-anchor": "bottom-left",
      "text-offset": [0, -0.2],
    },
    paint: { "text-color": "rgba(232,238,243,0.9)", "text-halo-color": "rgba(0,0,0,0.75)", "text-halo-width": 1.2 },
  });
}

/** Keeps map layers in step with the store: geography, view emphasis, flow, ports. */
function MapSync({ map }: { map: MlMap }) {
  const { geography, view, ratio, counts, selectedPortId, hudVisible, selectPort } = useTidemark(
    useShallow((s) => ({
      geography: selectGeography(s),
      view: s.view,
      ratio: s.flow.ratio,
      counts: s.collector.metrics?.by_port,
      selectedPortId: s.selectedPortId,
      hudVisible: s.hudVisible,
      selectPort: s.selectPort,
    })),
  );
  const framed = useRef<{ geographyId: string; hudVisible: boolean } | null>(null);

  // Geography geometry + camera. Re-frame on a new geography, or when overlays appear/disappear.
  useEffect(() => {
    (map.getSource("lanes") as GeoJSONSource).setData(lanesData(geography));
    (map.getSource("gates") as GeoJSONSource).setData(gatesData(geography));
    const offset = geography.laneOffsetPx ?? 0;
    map.setPaintProperty("lane-outbound", "line-offset", offset);
    map.setPaintProperty("lane-inbound", "line-offset", offset);
    const prev = framed.current;
    if (prev && (prev.geographyId !== geography.id || prev.hudVisible !== hudVisible)) {
      // Wait a frame so overlays have mounted/unmounted before measuring them.
      const id = requestAnimationFrame(() => frame(map, geography.bbox, true));
      framed.current = { geographyId: geography.id, hudVisible };
      return () => cancelAnimationFrame(id);
    }
    framed.current = { geographyId: geography.id, hudVisible };
  }, [map, geography, hudVisible]);

  // Port geofences + live counts.
  useEffect(() => {
    const counted = counts ? Object.fromEntries(Object.entries(counts).map(([k, m]) => [k, m.active_vessels])) : undefined;
    (map.getSource("ports") as GeoJSONSource).setData(portsData(geography, counted));
  }, [map, geography, counts]);

  useEffect(() => {
    if (!selectedPortId) return;
    map.setFeatureState({ source: "ports", id: selectedPortId }, { selected: true });
    return () => {
      if (map.getSource("ports")) map.setFeatureState({ source: "ports", id: selectedPortId }, { selected: false });
    };
  }, [map, selectedPortId, geography]);

  // Clicking a geofence opens it in the Ports view.
  useEffect(() => {
    const onClick = (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id;
      if (typeof id === "string") selectPort(id);
    };
    const enter = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const leave = () => {
      map.getCanvas().style.cursor = "";
    };
    map.on("click", "ports-fill", onClick);
    map.on("mouseenter", "ports-fill", enter);
    map.on("mouseleave", "ports-fill", leave);
    return () => {
      map.off("click", "ports-fill", onClick);
      map.off("mouseenter", "ports-fill", enter);
      map.off("mouseleave", "ports-fill", leave);
    };
  }, [map, selectPort]);

  // View emphasis; the laden lane's width tracks observed flow.
  useEffect(() => {
    const flowEmph = view === "flow";
    const width = (1.5 + 5 * Math.max(0.05, ratio)) * (flowEmph ? 0.75 : 0.45);
    map.setPaintProperty("lane-outbound", "line-width", width);
    map.setPaintProperty("lane-inbound", "line-width", width * 0.5);
    map.setPaintProperty("lane-outbound", "line-opacity", flowEmph ? 0.85 : 0.35);
    map.setPaintProperty("lane-inbound", "line-opacity", flowEmph ? 0.4 : 0.2);
    map.setPaintProperty("gates", "line-opacity", view === "vessels" ? 0.5 : 0);
    map.setPaintProperty("ports-line", "line-opacity", view === "ports" ? 0.9 : view === "vessels" ? 0.6 : 0.4);
    map.setPaintProperty("ports-label", "text-opacity", view === "ports" || view === "vessels" ? 1 : 0);
  }, [map, view, ratio]);

  // Animate the lane dashes; respect reduced motion.
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let step = 0;
    const timer = setInterval(() => {
      step = (step + 1) % DASH_SEQUENCE.length;
      map.setPaintProperty("lane-outbound", "line-dasharray", DASH_SEQUENCE[step]);
      map.setPaintProperty("lane-inbound", "line-dasharray", DASH_SEQUENCE[step]);
    }, 90);
    return () => clearInterval(timer);
  }, [map]);

  return null;
}

/* ── Ships ─────────────────────────────────────────────── */

interface ShipView {
  ref: ShipRef;
  lngLat: [number, number];
  kind: "laden" | "ballast" | "ais";
  dark: boolean;
  stale: boolean;
  label: string;
}

function simShip(v: Vessel): ShipView {
  return {
    ref: { source: "sim", mmsi: v.mmsi },
    lngLat: [v.position.lon, v.position.lat],
    kind: v.direction === "outbound" ? "laden" : "ballast",
    dark: v.ais === "dark",
    stale: false,
    label: `${v.name}, ${v.vesselClass}, simulated${v.ais === "dark" ? ", AIS dark" : ""}`,
  };
}

function aisShip(v: AisVessel): ShipView {
  return {
    ref: { source: "ais", mmsi: v.mmsi },
    lngLat: [v.longitude, v.latitude],
    kind: "ais",
    dark: false,
    stale: v.stale,
    label: `${v.name || `MMSI ${v.mmsi}`}, live AIS${v.stale ? ", stale" : ""}`,
  };
}

const keyOf = (r: ShipRef) => `${r.source}:${r.mmsi}`;

/**
 * Ships as MapLibre HTML markers (real buttons: focusable, labelled). Hover or keyboard
 * focus previews a ship in the info panel; click/tap pins it in the Vessels view.
 */
function ShipMarkers({ map, ml }: { map: MlMap; ml: MapLibre }) {
  const { sim, order, ais, selected, hovered, view, selectShip, hoverShip } = useTidemark(
    useShallow((s) => ({
      sim: s.vessels,
      order: s.vesselOrder,
      ais: s.ais.vessels,
      selected: s.selected,
      hovered: s.hovered,
      view: s.view,
      selectShip: s.selectShip,
      hoverShip: s.hoverShip,
    })),
  );
  const aisHere = useTidemark(useShallow((s) => aisInGeography(s).map((v) => v.mmsi)));
  const markers = useRef(new Map<string, { marker: Marker; el: HTMLButtonElement }>());

  useEffect(() => {
    const ships = [
      ...order.flatMap((m) => (sim[m] ? [simShip(sim[m])] : [])),
      ...aisHere.flatMap((m) => (ais[m] ? [aisShip(ais[m])] : [])),
    ];
    const live = new Set<string>();
    for (const ship of ships) {
      const key = keyOf(ship.ref);
      live.add(key);
      let entry = markers.current.get(key);
      if (!entry) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "ship";
        el.innerHTML = '<span class="ship-dot"></span>';
        const ref = ship.ref;
        el.addEventListener("pointerenter", (e) => {
          if (e.pointerType === "mouse") hoverShip(ref);
        });
        el.addEventListener("pointerleave", (e) => {
          if (e.pointerType === "mouse") hoverShip(null);
        });
        el.addEventListener("focus", () => hoverShip(ref));
        el.addEventListener("blur", () => hoverShip(null));
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          hoverShip(null);
          selectShip(ref);
        });
        entry = { el, marker: new ml.Marker({ element: el }).setLngLat(ship.lngLat).addTo(map) };
        markers.current.set(key, entry);
      } else {
        entry.marker.setLngLat(ship.lngLat);
      }
      const { el } = entry;
      el.dataset.kind = ship.kind;
      el.dataset.dark = String(ship.dark);
      el.dataset.stale = String(ship.stale);
      el.dataset.emphasis = view === "vessels" || ship.kind === "ais" ? "on" : "off";
      el.dataset.hovered = String(sameShip(hovered, ship.ref));
      el.setAttribute("aria-pressed", String(sameShip(selected, ship.ref)));
      el.setAttribute("aria-label", ship.label);
    }
    for (const [key, entry] of markers.current) {
      if (!live.has(key)) {
        entry.marker.remove();
        markers.current.delete(key);
      }
    }
  }, [ml, map, sim, order, ais, aisHere, selected, hovered, view, selectShip, hoverShip]);

  useEffect(() => {
    const all = markers.current;
    return () => {
      for (const { marker } of all.values()) marker.remove();
      all.clear();
    };
  }, []);

  return null;
}
