"use client";

import { useShallow } from "zustand/react/shallow";
import { getLocation, LOCATIONS } from "@/config/locations";
import { signed, utcClock, utcHourMinute } from "@/lib/format";
import { ScenarioSelect } from "./ScenarioSelect";
import { Segmented } from "./Segmented";
import { useTidemark, useTidemarkActions } from "./TidemarkProvider";

const LOCATION_ITEMS = LOCATIONS.map((l) => ({ id: l.id, label: l.short }));

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
  const { locationId, clock, lastTopic } = useTidemark(
    useShallow((s) => ({ locationId: s.locationId, clock: s.clock, lastTopic: s.lastTopic })),
  );
  const { switchLocation } = useTidemarkActions();
  return (
    <>
      <Segmented
        items={LOCATION_ITEMS}
        value={locationId}
        onChange={switchLocation}
        label="Monitored location"
        className="pills"
      />
      <div className="ticker" aria-live="off">
        {utcClock(clock)} · {lastTopic}
      </div>
    </>
  );
}

export function OutcomeCard() {
  const { outlook, scenarioId, locationId, flow } = useTidemark(
    useShallow((s) => ({ outlook: s.outlook, scenarioId: s.scenarioId, locationId: s.locationId, flow: s.flow })),
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
          {flow.flow_mbd.toFixed(1)} mb/d observed · {getLocation(locationId).name}
        </span>
      </div>
    </section>
  );
}

export function HudToggle() {
  const { hudVisible, toggleHud, tile } = useTidemark(
    useShallow((s) => ({ hudVisible: s.hudVisible, toggleHud: s.toggleHud, tile: s.tile })),
  );
  const attribution = `${tile.provider} · ${utcHourMinute(tile.captured_at)} · CLOUD ${tile.cloud_pct}% · ${tile.gsd_m} m/px`;
  return (
    <div className="toggle">
      <span className="attribution">{attribution}</span>
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
