"use client";

import { memo } from "react";
import { useShallow } from "zustand/react/shallow";
import { getLocation, VIEWBOX, type LocationConfig } from "@/config/locations";
import { polylinePath, toPercent, toViewBox } from "@/lib/geo";
import type { VesselView } from "@/store/tidemark";
import { useTidemark } from "./TidemarkProvider";

const VB = `${VIEWBOX.x} ${VIEWBOX.y} ${VIEWBOX.width} ${VIEWBOX.height}`;

/**
 * Stylized imagery stand-in. Replace with a tiled imagery layer (e.g. MapLibre
 * + Sentinel-2) once a provider is chosen; lanes, gates and vessels become map layers.
 */
const Basemap = memo(function Basemap({ loc }: { loc: LocationConfig }) {
  const { land, lake, gates, labels, lanes } = loc.geometry;
  return (
    <>
      <defs>
        <filter id="tm-sat" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={3} seed={7} />
          <feColorMatrix type="saturate" values="0" />
          <feComponentTransfer>
            <feFuncA type="table" tableValues="0 0.22" />
          </feComponentTransfer>
          <feComposite in2="SourceGraphic" operator="in" />
        </filter>
        <filter id="tm-sea" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.012 0.03" numOctaves={2} seed={3} />
          <feColorMatrix type="saturate" values="0" />
          <feComponentTransfer>
            <feFuncA type="table" tableValues="0 0.10" />
          </feComponentTransfer>
          <feComposite in2="SourceGraphic" operator="in" />
        </filter>
        <radialGradient id="tm-vignette" cx="50%" cy="50%" r="70%">
          <stop offset="55%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.65" />
        </radialGradient>
        <linearGradient id="tm-land" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2E2A23" />
          <stop offset="100%" stopColor="#242019" />
        </linearGradient>
      </defs>
      <rect x={VIEWBOX.x} y={VIEWBOX.y} width={VIEWBOX.width} height={VIEWBOX.height} fill="#0B1820" />
      <rect x={VIEWBOX.x} y={VIEWBOX.y} width={VIEWBOX.width} height={VIEWBOX.height} fill="#FFF" filter="url(#tm-sea)" />
      <g fill="url(#tm-land)" stroke="#3A3428" strokeWidth={0.8}>
        {land.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      <g fill="#FFF" filter="url(#tm-sat)">
        {land.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      {lake && <path d={lake} fill="#0B1820" stroke="#3A3428" strokeWidth={0.8} />}
      <Lanes inbound={polylinePath(lanes.inbound)} outbound={polylinePath(lanes.outbound)} gates={gates} />
      <g fontStyle="italic" fill="#F3EFE6" letterSpacing={1.5} style={{ fontFamily: "var(--display)" }}>
        {labels.map((l) => (
          <text key={l.text} x={l.x} y={l.y} fontSize={l.size} fillOpacity={l.opacity}>
            {l.text}
          </text>
        ))}
      </g>
      <rect x={VIEWBOX.x} y={VIEWBOX.y} width={VIEWBOX.width} height={VIEWBOX.height} fill="url(#tm-vignette)" />
    </>
  );
});

function Lanes({ inbound, outbound, gates }: { inbound: string; outbound: string; gates: string }) {
  const { view, ratio } = useTidemark(useShallow((s) => ({ view: s.view, ratio: s.flow.ratio })));
  const flowEmph = view === "flow";
  // Laden lane width tracks observed flow.
  const outW = (1.5 + 5 * Math.max(0.05, ratio)) * (flowEmph ? 1 : 0.6);
  return (
    <>
      <path
        className="lane"
        d={inbound}
        fill="none"
        strokeLinecap="round"
        style={{ stroke: "var(--teal)", strokeOpacity: flowEmph ? 0.4 : 0.2, strokeWidth: outW * 0.5 }}
      />
      <path
        className="lane"
        d={outbound}
        fill="none"
        strokeLinecap="round"
        style={{ stroke: "var(--accent)", strokeOpacity: flowEmph ? 0.85 : 0.35, strokeWidth: outW }}
      />
      <path
        className="gates"
        d={gates}
        stroke="#E8EEF3"
        strokeDasharray="2 5"
        style={{ strokeOpacity: view === "vessels" ? 0.4 : 0 }}
      />
    </>
  );
}

function VesselMarker({ v, loc, selected, emphasized }: { v: VesselView; loc: LocationConfig; selected: boolean; emphasized: boolean }) {
  const selectVessel = useTidemark((s) => s.selectVessel);
  const { left, top } = toPercent(toViewBox(loc, v.position.lon, v.position.lat));
  const dark = v.ais === "dark";
  const base = v.direction === "outbound" ? "var(--accent)" : "var(--ballast)";
  const size = selected ? 13 : emphasized ? 10 : 6;
  return (
    <button
      type="button"
      className="vessel"
      data-jumped={v.jumped}
      aria-label={`${v.name}, ${v.vesselClass}${dark ? ", AIS dark" : ""}`}
      aria-pressed={selected}
      onClick={() => selectVessel(v.mmsi)}
      style={{ left: `${left}%`, top: `${top}%`, opacity: emphasized ? 1 : 0.7 }}
    >
      <span
        className="vessel-dot"
        style={{
          width: size,
          height: size,
          background: dark ? "transparent" : base,
          borderColor: selected ? "#FFF" : dark ? "var(--alert)" : base,
          boxShadow: selected ? "0 0 0 6px rgba(255,255,255,0.18)" : "none",
        }}
      />
    </button>
  );
}

export function MapStage() {
  const { locationId, vessels, order, selected, view } = useTidemark(
    useShallow((s) => ({
      locationId: s.locationId,
      vessels: s.vessels,
      order: s.vesselOrder,
      selected: s.selectedMmsi,
      view: s.view,
    })),
  );
  const loc = getLocation(locationId);
  return (
    <div className="mapbox">
      <svg viewBox={VB} className="map-svg" role="img" aria-label={`Satellite imagery of the ${loc.name} with shipping lanes`}>
        <Basemap loc={loc} />
      </svg>
      {/* Remount markers on location change so they don't glide across the map. */}
      <div key={locationId}>
        {order.map((mmsi) =>
          vessels[mmsi] ? (
            <VesselMarker
              key={mmsi}
              v={vessels[mmsi]}
              loc={loc}
              selected={selected === mmsi}
              emphasized={view === "vessels"}
            />
          ) : null,
        )}
      </div>
    </div>
  );
}
