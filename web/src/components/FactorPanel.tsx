"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  fetchCustom,
  fetchFactors,
  type ChokepointId,
  type CpiCustom,
  type CpiFactors,
  type CustomParams,
  type Factor,
  type RegionId,
} from "@/lib/aperium/cpi";

type Vals = Record<string, number | boolean>;
interface Choke { on: boolean; source: "live" | "manual"; fraction: number; bypass: number }

const pct = (n: number | null | undefined, d = 2) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(d)}%`);
const idx = (n: number | null | undefined) => (n == null ? "—" : n.toFixed(1));

function Slider({ f, value, onChange }: { f: Factor; value: number; onChange: (v: number) => void }) {
  return (
    <label className="fp-ctl" title={f.reason ?? undefined}>
      <span className="row"><span>{f.label}</span><span className="mono">{value}{f.unit ? ` ${f.unit}` : ""}</span></span>
      <input type="range" min={f.min ?? 0} max={f.max ?? 1} step={f.step ?? 0.01} value={value} disabled={!f.available}
        onChange={(e) => onChange(Number(e.target.value))} />
      {!f.available && f.reason && <span className="caption">{f.reason}</span>}
    </label>
  );
}

function Toggle({ f, value, onChange }: { f: Factor; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="fp-ctl">
      <span className="row">
        <span>{f.label}</span>
        <input type="checkbox" checked={value && f.available} disabled={!f.available} onChange={(e) => onChange(e.target.checked)} />
      </span>
      {!f.available && f.reason && <span className="caption">{f.reason}</span>}
    </label>
  );
}

export function FactorPanel() {
  const [cat, setCat] = useState<CpiFactors | null>(null);
  const [vals, setVals] = useState<Vals>({});
  const [chokes, setChokes] = useState<Record<string, Choke>>({});
  const [region, setRegion] = useState<RegionId | "all">("national");
  const [res, setRes] = useState<CpiCustom | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    fetchFactors(ac.signal)
      .then((c) => {
        setVals(Object.fromEntries(c.factors.filter((f) => f.default != null).map((f) => [f.id, f.default as number | boolean])));
        setChokes(Object.fromEntries(c.chokepoints.map((k) => [k.id, {
          on: k.id === "hormuz", source: "manual", fraction: k.default_fraction, bypass: k.default_bypass_mbd }])));
        setCat(c);
      })
      .catch((e) => !ac.signal.aborted && setErr(String(e.message ?? e)));
    return () => ac.abort();
  }, []);

  // Only send values that differ from the catalog default; the backend fills in the rest from config.
  const params = useMemo<CustomParams | null>(() => {
    if (!cat) return null;
    const p: CustomParams = { region, chokepoints: cat.chokepoints.filter((k) => chokes[k.id]?.on).map((k) => k.id).join(",") };
    for (const f of cat.factors) if (f.kind !== "locked" && vals[f.id] !== f.default && vals[f.id] !== undefined) p[f.id] = vals[f.id];
    for (const k of cat.chokepoints) {
      const c = chokes[k.id];
      if (!c?.on) continue;
      p[`${k.id}_fraction`] = c.fraction;
      p[`${k.id}_bypass_mbd`] = c.bypass;
      if (k.id === "hormuz" && c.source === "live") p.hormuz_source = "live";
    }
    return p;
  }, [cat, vals, chokes, region]);

  useEffect(() => {
    if (!params) return;
    const ac = new AbortController();
    const t = setTimeout(() => {
      fetchCustom(params, ac.signal)
        .then((r) => { setRes(r); setErr(null); })
        .catch((e) => !ac.signal.aborted && setErr(String(e.message ?? e)));
    }, 150);
    return () => { clearTimeout(t); ac.abort(); };
  }, [params]);

  if (!cat) {
    return <div className="glass fp-card" role={err ? "alert" : "status"}>{err ?? "Loading factors…"}</div>;
  }
  const f = (id: string) => cat.factors.find((x) => x.id === id);
  const set = (id: string) => (v: number | boolean) => setVals((s) => ({ ...s, [id]: v }));
  const num = (id: string) => (vals[id] as number) ?? 0;
  const patch = (id: ChokepointId, p: Partial<Choke>) => setChokes((s) => ({ ...s, [id]: { ...s[id], ...p } }));
  const sliders = ["gasoline_share", "release_mbd", "release_scale", "sensitivity_central", "pass_through", "lag_days", "days", "baseline_transits"];
  const main = res?.regions[0];
  const cur = main?.months?.current_month;
  const nxt = main?.months?.next_month;
  const pumpNote = (m: { elevated_pump_days: number; days_in_month: number }) =>
    `${Math.round(m.elevated_pump_days)} of ${m.days_in_month} days at elevated pump prices`;
  const maxAbs = Math.max(0.0001, ...(main?.contributions.map((c) => Math.abs(c.current_month_pct)) ?? []));

  return (
    <div className="fp">
      <section className="glass fp-card panel" aria-label="Factors">
        <Link href="/" className="src-link">← Back to map</Link>
        <h1 className="heading">CPI factors</h1>
        {f("eia_move") && <Toggle f={f("eia_move")!} value={!!vals.eia_move} onChange={set("eia_move")} />}
        {f("release") && <Toggle f={f("release")!} value={!!vals.release} onChange={set("release")} />}
        {sliders.map((id) => f(id) && <Slider key={id} f={f(id)!} value={num(id)} onChange={set(id)} />)}
        <p className="caption">Locked on: BLS anchor, crude response, pump pass-through.</p>

        <h2 className="heading">Chokepoints</h2>
        {cat.chokepoints.map((k) => {
          const c = chokes[k.id];
          if (!c) return null;
          return (
            <div key={k.id} className="fp-choke">
              <label className="row">
                <span>{k.name} <span className="caption">{k.flow_mbd} mb/d</span></span>
                <input type="checkbox" checked={c.on} onChange={(e) => patch(k.id, { on: e.target.checked })} />
              </label>
              {c.on && (
                <>
                  {k.id === "hormuz" && (
                    <select value={c.source} onChange={(e) => patch(k.id, { source: e.target.value as Choke["source"] })} aria-label="Hormuz source">
                      <option value="manual">Manual</option>
                      <option value="live" disabled={!k.live_available}>Live AIS{k.live_available ? "" : " (unavailable)"}</option>
                    </select>
                  )}
                  {k.id === "hormuz" && !k.live_available && k.live_reason && <span className="caption">{k.live_reason}</span>}
                  <label className="fp-ctl"><span className="row"><span>Disrupted</span><span className="mono">{Math.round(c.fraction * 100)}%</span></span>
                    <input type="range" min={0} max={1} step={0.05} value={c.fraction} disabled={c.source === "live"}
                      onChange={(e) => patch(k.id, { fraction: Number(e.target.value) })} /></label>
                  <label className="fp-ctl"><span className="row"><span>Bypass</span><span className="mono">{c.bypass} mb/d</span></span>
                    <input type="range" min={0} max={25} step={0.1} value={c.bypass}
                      onChange={(e) => patch(k.id, { bypass: Number(e.target.value) })} /></label>
                </>
              )}
            </div>
          );
        })}

        <label className="fp-ctl"><span>Region</span>
          <select value={region} onChange={(e) => setRegion(e.target.value as RegionId | "all")}>
            {cat.regions.map((r) => <option key={r.id} value={r.id}>{r.name}{r.baseline_status === "unavailable" ? " (no data)" : ""}</option>)}
            <option value="all">Compare all</option>
          </select></label>
      </section>

      <section className="fp-out panel" aria-live="polite">
        {err && <div className="glass fp-card" role="alert">{err}</div>}
        {res && main && (
          <>
            <div className="glass fp-card panel">
              <div className="caption">Energy CPI nowcast, {main.name}{main.baseline.nowcast_period ? ` (${main.baseline.nowcast_period})` : ""}</div>
              <div className="num" style={{ fontSize: 40 }}>{idx(main.baseline.nowcast_cpi_energy)}</div>
              <div className="rows">
                <div className="row"><span>Month over month</span><span className="mono">{pct(main.baseline.nowcast_mom_pct)}</span></div>
                {cur ? (
                  <>
                    <div className="row"><span>Shock, {cur.period} (central)</span><span className="mono">{pct(cur.central.energy_cpi_shock_pct)}</span></div>
                    <div className="row"><span>Range, {cur.period} (low – high)</span><span className="mono">{pct(cur.low.energy_cpi_shock_pct)} – {pct(cur.high.energy_cpi_shock_pct)}</span></div>
                    <div className="row total"><span>With shock, {cur.period}</span><span className="mono">{idx(cur.central.energy_cpi_index)}</span></div>
                    <div className="caption">{pumpNote(cur)}</div>
                    {nxt && (
                      <>
                        <div className="row"><span>Shock, {nxt.period} (central)</span><span className="mono">{pct(nxt.central.energy_cpi_shock_pct)}</span></div>
                        <div className="row"><span>Range, {nxt.period} (low – high)</span><span className="mono">{pct(nxt.low.energy_cpi_shock_pct)} – {pct(nxt.high.energy_cpi_shock_pct)}</span></div>
                        <div className="row total"><span>With shock, {nxt.period}</span><span className="mono">{idx(nxt.central.energy_cpi_index)}</span></div>
                        <div className="caption">{pumpNote(nxt)}</div>
                      </>
                    )}
                  </>
                ) : <div className="caption">No baseline data for this region.</div>}
                <div className="row"><span>Net supply loss</span><span className="mono">{res.supply.net_supply_loss_mbd} mb/d</span></div>
              </div>
              {res.supply.overlap_warning && (
                <div className="fp-warn" role="alert">
                  Overlap: Hormuz flow also transits other selected chokepoints, so losses may double count. Lower bound
                  (largest single net loss after release): {res.supply.net_supply_loss_lower_bound_mbd} mb/d.
                </div>
              )}
              {res.supply.chokepoints.filter((k) => k.status !== "ok").map((k) => <div key={k.id} className="fp-warn">{k.name}: {k.reason}</div>)}
              {main.contributions.length > 0 && (
                <div className="bars">
                  <div className="caption">Contributions, current month (energy CPI %, central)</div>
                  {main.contributions.map((c) => (
                    <div key={c.id}>
                      <div className="row"><span>{c.label}</span><span className="mono">{pct(c.current_month_pct, 3)}</span></div>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${(Math.abs(c.current_month_pct) / maxAbs) * 100}%`,
                          background: c.current_month_pct < 0 ? "var(--teal)" : "var(--accent)" }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {res.regions.length > 1 && (
              <div className="glass fp-card">
                <table className="fp-table">
                  <thead><tr><th>Region</th><th>Status</th><th>Nowcast</th><th>MoM</th><th>Shock {main.months?.current_month.period ?? "now"}</th><th>Shock {main.months?.next_month.period ?? "next"}</th></tr></thead>
                  <tbody>
                    {res.regions.map((r) => (
                      <tr key={r.id}>
                        <td>{r.name}</td><td>{r.baseline.status}</td>
                        <td className="mono">{idx(r.baseline.nowcast_cpi_energy)}</td>
                        <td className="mono">{pct(r.baseline.nowcast_mom_pct)}</td>
                        <td className="mono">{pct(r.months?.current_month.central.energy_cpi_shock_pct)}</td>
                        <td className="mono">{pct(r.months?.next_month.central.energy_cpi_shock_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="glass fp-card">
              <div className="caption">Uncalibrated estimate (calibrated: false). As of {res.as_of_utc}.</div>
              <ul className="fp-list">{res.assumptions.map((a, i) => <li key={i} className="caption">{a}</li>)}</ul>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
