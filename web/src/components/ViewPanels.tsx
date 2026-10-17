"use client";

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { DEFAULT_MODEL_PARAMS } from "@/config/model";
import { getScenario } from "@/config/scenarios";
import { NAV_STATUS } from "@/lib/aperium/client";
import { signed } from "@/lib/format";
import { forecastSupply } from "@/lib/model";
import { aisInGeography, selectGeography, type CollectorState, type ShipRef, type ViewId } from "@/store/tidemark";
import { Segmented } from "./Segmented";
import { useTidemark } from "./TidemarkProvider";

const VIEWS: { id: ViewId; label: string }[] = [
  { id: "flow", label: "Flow" },
  { id: "vessels", label: "Vessels" },
  { id: "ports", label: "Ports" },
  { id: "supply", label: "Supply" },
  { id: "cpi", label: "CPI" },
  { id: "connect", label: "API/MCP" },
];
const PANEL_ID = "hud-panel";
const TAB_PREFIX = "hud-tab";

export function ViewTabs() {
  const { view, setView } = useTidemark(useShallow((s) => ({ view: s.view, setView: s.setView })));
  return (
    <Segmented
      items={VIEWS}
      value={view}
      onChange={setView}
      label="HUD layer"
      size="lg"
      className="hud hud-tabs"
      idPrefix={TAB_PREFIX}
      controls={PANEL_ID}
    />
  );
}

export function ViewPanel() {
  const { view, hovered } = useTidemark(useShallow((s) => ({ view: s.view, hovered: s.hovered })));
  return (
    <div id={PANEL_ID} role="tabpanel" aria-labelledby={`${TAB_PREFIX}-${view}`} className="hud glass hud-panel">
      {/* Hovering or focusing a ship previews it here, whatever the view. */}
      {hovered ? <ShipPreview ship={hovered} /> : <ViewContent view={view} />}
    </div>
  );
}

function ViewContent({ view }: { view: ViewId }) {
  return (
    <>
      {view === "flow" && <FlowPanel />}
      {view === "vessels" && <VesselsPanel />}
      {view === "ports" && <PortsPanel />}
      {view === "supply" && <SupplyPanel />}
      {view === "cpi" && <CpiPanel />}
      {view === "connect" && <ConnectPanel />}
    </>
  );
}

/* ── Flow ─────────────────────────────────────────────── */

const SPARK_W = 280;
const SPARK_H = 48;

function sparkline(history: number[]) {
  const min = Math.min(...history);
  const max = Math.max(...history);
  const pad = Math.max(0.02, (max - min) * 0.3);
  const lo = Math.min(min, 1) - pad;
  const hi = Math.max(max, 1) + pad;
  const y = (q: number) => (SPARK_H - ((q - lo) / (hi - lo)) * SPARK_H).toFixed(1);
  const n = history.length - 1;
  return {
    path: history.map((q, i) => `${i ? "L" : "M"}${((i / n) * SPARK_W).toFixed(1)},${y(q)}`).join(" "),
    baselineY: y(1),
  };
}

function FlowPanel() {
  const { history, flow, outlook, loc } = useTidemark(
    useShallow((s) => ({ history: s.history, flow: s.flow, outlook: s.outlook, loc: selectGeography(s) })),
  );
  const spark = sparkline(history);
  const { chain } = outlook;
  return (
    <div className="panel">
      <h2 className="heading">Oil flow</h2>
      <div>
        <div className="num" style={{ fontSize: 44, letterSpacing: "-0.01em" }}>
          {flow.flow_mbd.toFixed(1)} <span className="unit">mb/d</span>
        </div>
        <svg viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} width="100%" height={SPARK_H} preserveAspectRatio="none" aria-hidden="true">
          <path d={`M0,${spark.baselineY} H${SPARK_W}`} stroke="rgba(232,238,243,0.3)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
          <path d={spark.path} fill="none" strokeWidth={1.8} vectorEffect="non-scaling-stroke" style={{ stroke: "var(--accent)" }} />
        </svg>
        <div className="caption">
          Last {history.length} events · dashed = {loc.baseMbd.toFixed(1)} mb/d baseline
        </div>
      </div>
      <div className="rows">
        <div className="row">
          <span>Transit gap</span>
          <span className="mono">{Math.max(0, chain.gapMbd).toFixed(2)} mb/d</span>
        </div>
        <div className="row">
          <span>{loc.bypassLabel}</span>
          <span className="mono">−{chain.bypassMbd.toFixed(2)} mb/d</span>
        </div>
        <div className="row total">
          <span>Net supply loss</span>
          <span className="mono" style={{ color: "var(--accent)" }}>
            {chain.netMbd.toFixed(2)} mb/d
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Vessels ──────────────────────────────────────────── */

function VesselsPanel() {
  const { vessels, selected, flow, aisCount, aisConnected } = useTidemark(
    useShallow((s) => ({
      vessels: s.vessels,
      selected: s.selected,
      flow: s.flow,
      aisCount: aisInGeography(s).filter((v) => !v.stale).length,
      aisConnected: s.ais.connected,
    })),
  );
  const list = Object.values(vessels);
  const outC = list.filter((v) => v.inCorridor && v.direction === "outbound").length;
  const inC = list.filter((v) => v.inCorridor && v.direction === "inbound").length;
  const darkC = list.filter((v) => v.ais === "dark").length;
  // Placeholder: 24h of laden loadings ≈ one day of observed flow.
  const laden24 = flow.flow_mbd;

  const stat = (value: string | number, label: string, color?: string) => (
    <div>
      <div className="num" style={{ fontSize: 34, color }}>
        {value}
      </div>
      <div className="caption">{label}</div>
    </div>
  );

  return (
    <div className="panel">
      <h2 className="heading">Vessels</h2>
      <div className="grid-2">
        {stat(outC, "Laden outbound")}
        {stat(inC, "Ballast inbound")}
        {stat(darkC, "AIS-dark, imagery only", "var(--alert)")}
        {stat(laden24.toFixed(1), "mb loaded, last 24h")}
      </div>
      <div className="row" style={{ fontSize: 12 }}>
        <span>
          <span className="dot" style={{ background: "var(--positive)", marginRight: 6 }} />
          Live AIS in port geofences
        </span>
        <span className="mono">{aisConnected === false ? "stream offline" : aisCount}</span>
      </div>
      {selected ? (
        <ShipDetail ship={selected} pinned />
      ) : (
        <p className="caption" style={{ margin: 0 }}>
          Hover a ship for details; click or tap to pin it here. Corridor counts and flow come from the simulated feed; green
          ships are live AIS from the collector.
        </p>
      )}
    </div>
  );
}

/* ── Ship detail (hover preview + pinned) ─────────────── */

function ShipPreview({ ship }: { ship: ShipRef }) {
  return (
    <div className="panel" aria-live="polite">
      <h2 className="heading">Vessel</h2>
      <ShipDetail ship={ship} />
      <p className="caption" style={{ margin: 0 }}>
        Click or tap the ship to pin it.
      </p>
    </div>
  );
}

function ago(seconds: number | null | undefined) {
  if (seconds == null) return "never";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

function ShipDetail({ ship, pinned = false }: { ship: ShipRef; pinned?: boolean }) {
  const { sim, ais, ports, clock, selectShip } = useTidemark(
    useShallow((s) => ({
      sim: ship.source === "sim" ? s.vessels[ship.mmsi] : undefined,
      ais: ship.source === "ais" ? s.ais.vessels[ship.mmsi] : undefined,
      ports: selectGeography(s).ports,
      clock: s.clock, // ms; ticks with the feed
      selectShip: s.selectShip,
    })),
  );
  const line = (text: string, color = "var(--text-soft)") => <div style={{ fontSize: 12, color }}>{text}</div>;
  const name = sim?.name ?? (ais ? ais.name || `MMSI ${ais.mmsi}` : "Vessel no longer tracked");

  return (
    <div className="inner-card">
      <div className="row" style={{ alignItems: "center" }}>
        <span style={{ fontWeight: 600, color: "var(--text)" }}>{name}</span>
        {pinned && (
          <button type="button" className="icon-btn" aria-label="Close vessel detail" onClick={() => selectShip(null)}>
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <path d="M1 1 L9 9 M9 1 L1 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>
      {sim && (
        <>
          {line(`${sim.vesselClass} · ${sim.laden ? "laden" : "ballast"} · ${sim.position.sog_kn.toFixed(1)} kn`)}
          {line(`${sim.cargo} → ${sim.destination}`)}
          {line(
            sim.ais === "dark" ? "AIS dark · tracked from imagery" : "AIS live",
            sim.ais === "dark" ? "var(--alert)" : "var(--positive)",
          )}
          <span className="source-tag">Simulated corridor traffic</span>
        </>
      )}
      {ais && (
        <>
          {line(`MMSI ${ais.mmsi}`)}
          {line(
            [
              ais.speed_knots != null ? `${ais.speed_knots.toFixed(1)} kn` : "speed n/a",
              ais.course != null ? `course ${Math.round(ais.course)}°` : null,
            ]
              .filter(Boolean)
              .join(" · "),
          )}
          {ais.nav_status != null && line(NAV_STATUS[ais.nav_status] ?? `Nav status ${ais.nav_status}`)}
          {line(`In ${ais.ports.map((id) => ports.find((p) => p.id === id)?.name ?? id).join(", ")}`)}
          {line(
            `Last position ${ago(Math.max(0, clock / 1000 - ais.observed_at))}${ais.stale ? " · stale" : ""}`,
            ais.stale ? "var(--accent)" : "var(--positive)",
          )}
          <span className="source-tag live">Live AIS · AISstream via collector</span>
        </>
      )}
    </div>
  );
}

/* ── Ports (AIS collector) ────────────────────────────── */

const STREAM_LABEL: Record<string, string> = {
  receiving: "receiving positions",
  subscribed: "subscribed, waiting for positions",
  awaiting_subscription: "subscribing",
  connecting: "connecting",
  reconnecting: "reconnecting",
  missing_api_key: "no AISstream key",
};

const PORT_STATUS: Record<string, { label: string; color: string }> = {
  fresh_observations: { label: "fresh", color: "var(--positive)" },
  stale_observations_only: { label: "stale only", color: "var(--accent)" },
  no_observed_vessels: { label: "none observed", color: "var(--text-muted)" },
};

function CollectorLine({ collector }: { collector: CollectorState }) {
  const { reachable, status } = collector;
  const [color, text] =
    reachable === null ? ["var(--ballast)", "Checking AIS collector…"]
    : !reachable ? ["var(--alert)", "AIS collector offline"]
    : status?.status === "receiving" ? ["var(--positive)", `AIS collector · last position ${ago(status.seconds_since_last_position)}`]
    : ["var(--accent)", `AIS collector · ${STREAM_LABEL[status?.status ?? ""] ?? status?.status}`];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-soft)" }} role="status">
      <span className="dot" style={{ background: color }} />
      {text}
    </div>
  );
}

function PortsPanel() {
  const { loc, collector, selected, selectPort } = useTidemark(
    useShallow((s) => ({
      loc: selectGeography(s),
      collector: s.collector,
      selected: s.selectedPortId,
      selectPort: s.selectPort,
    })),
  );
  // Ports belong to a geography in Postgres (`ports.geography_id`).
  const visible = loc.ports;
  const byPort = collector.metrics?.by_port;

  return (
    <div className="panel">
      <h2 className="heading">Port activity</h2>
      <CollectorLine collector={collector} />
      {collector.reachable === false && (
        <p className="caption" style={{ margin: 0 }}>
          Start it with <span className="mono">./dev.sh</span> from the repo root.
        </p>
      )}
      {collector.status?.status === "missing_api_key" && (
        <p className="caption" style={{ margin: 0 }}>
          Set <span className="mono">AISSTREAM_API_KEY</span> in <span className="mono">.env</span> and restart to collect live
          positions.
        </p>
      )}
      {visible.length === 0 ? (
        <p className="caption" style={{ margin: 0 }}>
          No port geofences are configured for the {loc.name}. Add rows to the <span className="mono">ports</span> table
          with <span className="mono">geography_id = &apos;{loc.id}&apos;</span>.
        </p>
      ) : (
        <ul className="port-list">
          {visible.map((p) => {
            const m = byPort?.[p.id];
            const st = m ? PORT_STATUS[m.data_status] : undefined;
            return (
              <li key={p.id}>
                <button type="button" className="port-row" aria-pressed={selected === p.id} onClick={() => selectPort(p.id)}>
                  <span className="row" style={{ alignItems: "baseline" }}>
                    <span style={{ fontWeight: 600, color: "var(--text)" }}>{p.name}</span>
                    {st && (
                      <span className="mono" style={{ fontSize: 11, color: st.color }}>
                        {st.label}
                      </span>
                    )}
                  </span>
                  {m ? (
                    <span className="port-stats">
                      <span>
                        <span className="num">{m.active_vessels}</span> active
                      </span>
                      <span>
                        <span className="num">{m.slow_vessels_under_1_knot}</span> &lt;1 kn
                      </span>
                      <span>
                        <span className="num">{m.reported_anchored}</span> anchored
                      </span>
                      <span>
                        <span className="num">{m.stale_vessels_in_area}</span> stale
                      </span>
                    </span>
                  ) : (
                    <span className="caption mono" style={{ fontSize: 11 }}>
                      {formatBounds(p.bounds_lat_lon)}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <p className="caption" style={{ margin: 0 }}>
        {collector.metrics?.note ?? "Observed activity only. Zero may mean no coverage."} Boxes are approximate discovery areas,
        not official anchorage boundaries.
      </p>
    </div>
  );
}

function formatBounds([[s, w], [n, e]]: readonly (readonly [number, number])[]) {
  return `${s.toFixed(2)}–${n.toFixed(2)}°N · ${w.toFixed(2)}–${e.toFixed(2)}°E`;
}

/* ── Supply ───────────────────────────────────────────── */

const FC_W = 280;
const FC_H = 140;

function SupplyPanel() {
  const { loc, scenarioId } = useTidemark(useShallow((s) => ({ loc: selectGeography(s), scenarioId: s.scenarioId })));
  const sc = getScenario(scenarioId);

  const fc = useMemo(() => {
    const f = forecastSupply(loc, sc);
    // Fixed 0–24 mb/d scale so locations compare visually, as in the prototype.
    const top = Math.max(24, loc.baseMbd + sc.sigmaMbd * 1.3);
    const X = (d: number) => ((d / 90) * FC_W).toFixed(1);
    const Y = (v: number) => (FC_H - (Math.max(0, Math.min(top, v)) / top) * FC_H).toFixed(1);
    const line = (pick: (p: (typeof f.points)[number]) => number) =>
      f.points.map((p, i) => `${i ? "L" : "M"}${X(p.day)},${Y(pick(p))}`).join(" ");
    const rev = [...f.points].reverse();
    return {
      transit: line((p) => p.transitMbd),
      withBypass: line((p) => p.withBypassMbd),
      band:
        line((p) => p.transitMbd + p.sigmaMbd) +
        " " +
        rev.map((p) => `L${X(p.day)},${Y(p.transitMbd - p.sigmaMbd)}`).join(" ") +
        " Z",
      base: `M0,${Y(loc.baseMbd)} H${FC_W}`,
      trough: f.troughMbd,
      cum: f.cumulativeLossMb,
    };
  }, [loc, sc]);

  return (
    <div className="panel">
      <h2 className="heading">Supply · next 90 days</h2>
      <svg
        viewBox={`0 0 ${FC_W} ${FC_H}`}
        width="100%"
        height={FC_H}
        preserveAspectRatio="none"
        role="img"
        aria-label={`90-day supply path for ${sc.name}, trough ${fc.trough.toFixed(1)} million barrels per day`}
      >
        <path d={fc.band} style={{ fill: "var(--accent)" }} fillOpacity={0.15} />
        <path d={fc.base} stroke="rgba(232,238,243,0.35)" strokeDasharray="3 4" fill="none" vectorEffect="non-scaling-stroke" />
        <path d={fc.withBypass} strokeWidth={1.6} fill="none" vectorEffect="non-scaling-stroke" style={{ stroke: "var(--teal)" }} />
        <path d={fc.transit} strokeWidth={2.2} fill="none" vectorEffect="non-scaling-stroke" style={{ stroke: "var(--accent)" }} />
      </svg>
      <div className="axis" aria-hidden="true">
        <span>Today</span>
        <span>D30</span>
        <span>D60</span>
        <span>D90</span>
      </div>
      <div className="legend">
        <span>
          <span className="swatch" style={{ background: "var(--accent)" }} />
          Transit
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--teal)" }} />
          With bypass
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--accent)", opacity: 0.3, height: 8 }} />
          80% band
        </span>
      </div>
      <div className="grid-2" style={{ gap: 12 }}>
        <div>
          <div className="num" style={{ fontSize: 30 }}>
            {fc.trough.toFixed(1)}
          </div>
          <div className="caption">Trough, mb/d</div>
        </div>
        <div>
          <div className="num" style={{ fontSize: 30 }}>
            {fc.cum.toFixed(0)}
          </div>
          <div className="caption">Barrels lost, mb</div>
        </div>
      </div>
    </div>
  );
}

/* ── CPI ──────────────────────────────────────────────── */

function CpiPanel() {
  const { outlook, loc } = useTidemark(useShallow((s) => ({ outlook: s.outlook, loc: selectGeography(s) })));
  const c = outlook.chain;
  const params = DEFAULT_MODEL_PARAMS;
  const motorPassThrough = params.components.find((k) => k.driver === "gasoline")?.passThrough1m ?? 0;

  const chain = [
    { label: "Net supply loss", note: `transit gap after ${loc.bypassLabel}`, val: `${c.netMbd.toFixed(2)} mb/d` },
    { label: "Brent", note: `${params.brentPctPerMbd}% per mb/d + risk premium`, val: `$${c.brentUsd.toFixed(1)}` },
    {
      label: "US gasoline, pump",
      note: `≈${(params.gasUsdPerBrentUsd * 100).toFixed(1)}¢/gal per $1/bbl · ~${Math.round(motorPassThrough * 100)}% in 30 days`,
      val: `${signed(c.gasPct * motorPassThrough, 1)}%`,
    },
    { label: "Energy CPI, 1 month", note: `${c.energyWeight.toFixed(1)}% of CPI basket`, val: `${signed(c.energyPct, 1)}%` },
    { label: "Headline CPI, 1 month", note: "direct contribution", val: `${signed(c.headlinePp, 2)} pp` },
  ];

  const maxPp = Math.max(0.01, ...c.components.map((k) => Math.abs(k.pp)));

  return (
    <div className="panel">
      <h2 className="heading">Flow → CPI transmission</h2>
      <ol className="chain">
        {chain.map((step, i) => {
          const last = i === chain.length - 1;
          return (
            <li key={step.label}>
              <span className="chain-rail" aria-hidden="true">
                <span className="dot" style={{ background: last ? "var(--accent)" : "rgba(232,238,243,0.6)" }} />
                <span className="line" style={{ opacity: last ? 0 : 1 }} />
              </span>
              <span className="chain-text">
                <span style={{ fontSize: 13 }}>{step.label}</span>
                <span className="note">{step.note}</span>
              </span>
              <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>
                {step.val}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="bars">
        <div style={{ fontSize: 12, color: "rgba(232,238,243,0.65)" }}>Contribution to headline, pp</div>
        {c.components.map((k) => (
          <div key={k.id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div className="row" style={{ fontSize: 12 }}>
              <span style={{ color: "var(--text)" }}>
                {k.name} <span style={{ color: "rgba(232,238,243,0.5)" }}>· wt {k.weight.toFixed(1)}</span>
              </span>
              <span className="mono">{signed(k.pp, 2)}</span>
            </div>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${(Math.abs(k.pp) / maxPp) * 100}%`, background: k.pp >= 0 ? "var(--accent)" : "var(--teal)" }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── API / MCP ────────────────────────────────────────── */

const MCP_TOOLS = ["get_flow_estimate", "list_vessels", "run_scenario", "get_energy_cpi_outlook"];

function ConnectPanel() {
  const slug = useTidemark((s) => selectGeography(s).slug);
  const endpoints: [string, string, string][] = [
    ["GET", `/v1/flow/${slug}`, "var(--teal)"],
    ["GET", "/v1/vessels?zone=corridor", "var(--teal)"],
    ["GET", "/v1/cpi/energy?horizon=1m", "var(--teal)"],
    ["POST", "/v1/scenarios/run", "var(--accent)"],
    ["WSS", "/v1/stream · flow.* vessel.* cpi.*", "var(--positive)"],
  ];
  const collectorEndpoints: [string, string][] = [
    ["GET", "/api/geographies"],
    ["GET", "/api/ports?geography="],
    ["GET", "/api/vessels?port="],
    ["GET", "/api/metrics"],
    ["GET", "/api/vessels/{mmsi}/history"],
    ["SSE", "/api/stream · snapshot, vessel"],
  ];
  return (
    <div className="panel" style={{ gap: 16 }}>
      <h2 className="heading">Build on this feed</h2>
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-soft)" }}>
        Every number on this screen is available to your systems and to AI agents.
      </p>
      <div className="section">
        <div className="section-title">
          <h3>MCP server</h3>
          <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--positive)" }}>
            <span className="dot" style={{ width: 6, height: 6, background: "var(--positive)" }} />
            online
          </span>
        </div>
        <div className="code-box">https://[your-host]/mcp</div>
        <div className="caption">Streamable HTTP · OAuth</div>
        <ul className="chips" aria-label="MCP tools">
          {MCP_TOOLS.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </div>
      <div className="section">
        <div className="section-title">
          <h3>API</h3>
          <span className="mono caption" style={{ fontSize: 11 }}>
            v1 · OpenAPI 3.1
          </span>
        </div>
        <dl className="endpoints">
          {endpoints.map(([method, path, color]) => (
            <div key={path}>
              <dt style={{ color }}>{method}</dt>
              <dd>{path}</dd>
            </div>
          ))}
        </dl>
        <div className="caption">Same events that drive this HUD, pushed in real time. Planned; mocked today.</div>
      </div>
      <div className="section">
        <div className="section-title">
          <h3>AIS collector</h3>
          <span className="mono caption" style={{ fontSize: 11 }}>
            live · FastAPI + Postgres
          </span>
        </div>
        <dl className="endpoints">
          {collectorEndpoints.map(([method, path]) => (
            <div key={path}>
              <dt style={{ color: method === "SSE" ? "var(--positive)" : "var(--teal)" }}>{method}</dt>
              <dd>{path}</dd>
            </div>
          ))}
        </dl>
        <div className="caption">Geographies, port geofences, port activity and live AIS ships come from here.</div>
      </div>
    </div>
  );
}
