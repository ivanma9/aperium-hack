"use client";

import { useShallow } from "zustand/react/shallow";
import { signed, utcClock } from "@/lib/format";
import { selectGeography } from "@/store/tidemark";
import { ScenarioSelect } from "./ScenarioSelect";
import { Segmented } from "./Segmented";
import { useTidemark, useTidemarkActions } from "./TidemarkProvider";

export function Brand() {
  const { paused, togglePaused } = useTidemark(useShallow((s) => ({ paused: s.paused, togglePaused: s.togglePaused })));
  return (
    <div className="brand">
      <button
        type="button"
        className="glass pill-btn"
        aria-pressed={paused}
        aria-label={paused ? "Resume live feed" : "Pause live feed"}
        onClick={togglePaused}
      >
        <span className="dot" style={{ background: paused ? "var(--ballast)" : "var(--positive)" }} />
        {paused ? "Paused" : "Live"}
      </button>
      <h1 className="wordmark">Tidemark</h1>
      <span className="tagline">Energy flow intelligence</span>
    </div>
  );
}

export function LocationBar() {
  const { geographies, geographyId, clock, lastTopic } = useTidemark(
    useShallow((s) => ({ geographies: s.geographies, geographyId: s.geographyId, clock: s.clock, lastTopic: s.lastTopic })),
  );
  const { switchGeography } = useTidemarkActions();
  // Geographies come from the backend (Postgres `geographies` table).
  const items = geographies.map((g) => ({ id: g.id, label: g.short }));
  return (
    <>
      <Segmented
        items={items}
        value={geographyId}
        onChange={switchGeography}
        label="Monitored geography"
        className="pills"
      />
      <div className="ticker" aria-live="off">
        {utcClock(clock)} · {lastTopic}
      </div>
    </>
  );
}

export function OutcomeCard() {
  const { outlook, scenarioId, geography, flow } = useTidemark(
    useShallow((s) => ({ outlook: s.outlook, scenarioId: s.scenarioId, geography: selectGeography(s), flow: s.flow })),
  );
  const { runScenario } = useTidemarkActions();
  const pct = outlook.energy_pct;
  const color = pct > 0.05 ? "var(--accent)" : pct < -0.05 ? "var(--teal)" : "var(--text)";
  return (
    <section className="ov ov-bottom glass outcome" aria-label="Outcome">
      <h2 className="heading">US energy CPI, one-month outlook</h2>
      <div className="outcome-value" style={{ color }}>
        {signed(pct, 1)}%
      </div>
      <div className="outcome-meta">
        <span>
          Headline <span className="mono">{signed(outlook.headline_pp, 2)} pp</span>
        </span>
        <span>
          Core spillover <span className="mono">{signed(outlook.core_pp, 2)} pp</span>{" "}
          <span style={{ color: "rgba(232,238,243,0.55)" }}>builds over 6–12 mo</span>
        </span>
      </div>
      <div className="outcome-controls">
        <ScenarioSelect value={scenarioId} onChange={runScenario} />
        <span className="caption">
          {flow.flow_mbd.toFixed(1)} mb/d observed · {geography.name}
        </span>
      </div>
    </section>
  );
}

export function HudToggle() {
  const { hudVisible, toggleHud } = useTidemark(useShallow((s) => ({ hudVisible: s.hudVisible, toggleHud: s.toggleHud })));
  return (
    <div className="toggle">
      <MapAttribution />
      <button
        type="button"
        className="glass pill-btn hud-toggle"
        aria-pressed={!hudVisible}
        aria-label={hudVisible ? "Hide heads-up display" : "Show heads-up display"}
        onClick={toggleHud}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M1.5 8 C3.5 4.5 5.8 3 8 3 C10.2 3 12.5 4.5 14.5 8 C12.5 11.5 10.2 13 8 13 C5.8 13 3.5 11.5 1.5 8 Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
          />
          <circle cx="8" cy="8" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.3" />
          {hudVisible && <path d="M2.5 13.5 L13.5 2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />}
        </svg>
        {hudVisible ? "Hide HUD" : "Show HUD"}
      </button>
    </div>
  );
}

/** Required basemap credit (OpenFreeMap / OpenMapTiles / OpenStreetMap). Always visible. */
export function MapAttribution({ className = "" }: { className?: string }) {
  return (
    <span className={`attribution ${className}`}>
      <a href="https://openfreemap.org" target="_blank" rel="noreferrer">
        OpenFreeMap
      </a>{" "}
      <a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">
        © OpenMapTiles
      </a>{" "}
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
        © OpenStreetMap
      </a>
    </span>
  );
}
