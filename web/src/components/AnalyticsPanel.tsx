"use client";

import { useEffect, useState } from 'react';
import { ANALYTICS_VIEWS, duration, fetchAnalytics, type AnalyticsResult, type AnalyticsView, type Stay } from '@/lib/aperium/analytics';
import { selectGeography } from '@/store/tidemark';
import { useTidemark } from './TidemarkProvider';

const utc = (value: number | null) => value == null ? 'Unknown' : new Date(value * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
const words = (value: string) => value.replaceAll('_', ' ');

export function AnalyticsPanel() {
  const geography = useTidemark(selectGeography);
  const paused = useTidemark(s => s.paused);
  // Remount on geography changes, avoiding stale results from a previous location.
  return <ScopedAnalytics key={geography.id} geography={geography.id} ports={geography.ports} paused={paused} />;
}

function ScopedAnalytics({ geography, ports, paused }: { geography: string; ports: readonly { id: string; name: string }[]; paused: boolean }) {
  const [view, setView] = useState<AnalyticsView>('classification');
  const [hours, setHours] = useState(24);
  const port = useTidemark(s => s.selectedPortId) ?? '';
  const setPort = useTidemark(s => s.setAnalyticsPort);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<{ key: string; data: AnalyticsResult | null; error: string | null } | null>(null);
  const key = `${geography}:${port}:${hours}`;
  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await fetchAnalytics(geography, hours, port, controller.signal);
        if (!controller.signal.aborted) setState({ key, data, error: null });
      } catch (error) {
        if (!controller.signal.aborted) setState(previous => ({ key, data: previous?.key === key ? previous.data : null,
          error: error instanceof Error ? error.message : 'Analytics unavailable' }));
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 20_000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [geography, hours, port, key, paused, retry]);
  const current = state?.key === key ? state : null;
  return <div className="panel analytics-panel">
    <h2 className="heading">Observed AIS analytics</h2>
    <p className="caption">Real collected tracks · separate from scenario simulations</p>
    <div className="analytics-filters">
      <label>Area<select value={port} onChange={e => setPort(e.target.value || null)}><option value="">Entire geography</option>
        {ports.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <label>History<select value={hours} onChange={e => setHours(Number(e.target.value))}>
        {[1,6,24,72,168].map(h => <option key={h} value={h}>{h} hours</option>)}</select></label>
    </div>
    {port && <p className="caption">Highlighted on map: {ports.find(p => p.id === port)?.name} · Port discovery area</p>}
    <div className="analytics-tabs" role="group" aria-label="Analytics feature">
      {ANALYTICS_VIEWS.map(v => <button key={v.id} aria-pressed={view === v.id} onClick={() => setView(v.id)}>{v.label}</button>)}
    </div>
    {paused && <p role="status" className="caption">Updates paused. Displayed values are from the last refresh.</p>}
    {current?.error && <div className="analytics-notice" role="alert">{current.error}. {current.data && 'Showing the last successful response; values may be stale.'}
      <button onClick={() => setRetry(n => n+1)} disabled={paused}>Retry</button></div>}
    {!current && !paused && <p role="status">Loading observed analytics…</p>}
    {!current && paused && <p>No analytics loaded. Resume updates to fetch data.</p>}
    {current?.data && <AnalyticsContent data={current.data} view={view} />}
  </div>;
}

function Empty({ children }: { children: React.ReactNode }) { return <p className="analytics-notice">{children}</p>; }

function Stays({ rows, calls = false }: { rows: Stay[]; calls?: boolean }) {
  return <ul className="analytics-list">{rows.slice(0,100).map(row => <li key={row.id}>
    <div className="row"><strong className="mono">{row.mmsi}</strong><span>{duration(row.observed_seconds)} observed</span></div>
    <div>{row.boundary_id} · {row.reviewed_boundary ? 'Reviewed boundary' : 'Unreviewed boundary'}</div>
    <div className="caption">First seen {utc(row.first_seen_at)} · {row.entry_observed ? 'Entry observed' : 'Arrival time unknown'}</div>
    <div className="caption">{words(row.end_reason)} · Last seen {utc(row.last_seen_at)}</div>
    {calls && <div className="caption">Departure: {utc(row.departure_observed_at)} · Prior observed wait: {duration(row.observed_prior_wait_seconds)}</div>}
  </li>)}{rows.length>100 && <li className="caption">Showing 100 of {rows.length} events. Select a shorter history window for detail.</li>}</ul>;
}

export function AnalyticsContent({ data, view }: { data: AnalyticsResult; view: AnalyticsView }) {
  const q = data.quality;
  const gates = Object.entries(data.transit_counts);
  return <>
    <div className="analytics-quality" role="status">
      {words(q.observation_status)} · {q.observed_vessels} vessels observed · {q.unclassified_vessels} unclassified
      <div className="caption">Latest position {utc(q.latest_observed_at)} · Coverage completeness unverified</div>
      <div className="caption">{q.discontinuities} track discontinuities · Refreshed {utc(data.generated_at)}</div>
    </div>
    {view === 'classification' && <section aria-label="Vessel classification">
      <h3>Vessel classification</h3><p className="caption">AIS self-reported types; tanker does not establish crude, LNG, cargo quantity, or loaded status.</p>
      {data.classification.length === 0 ? <Empty>No vessel observations in this area and time window.</Empty> :
        <ul className="analytics-list">{data.classification.slice(0,100).map(v => <li key={v.mmsi}>
          <div className="row"><strong>{v.name || v.mmsi}</strong><span>{v.vessel_class}</span></div>
          <div className="caption mono">MMSI {v.mmsi} · AIS type {v.ship_type ?? 'unknown'} · {v.stale ? 'Stale position' : 'Recent position'}</div>
          <div className="caption">{v.source ? `Self-reported · updated ${utc(v.classification_updated_at)}` : 'Awaiting static AIS report'}</div>
        </li>)}</ul>}
      {data.classification.length>100 && <p className="caption">Showing the first 100 vessels. Narrow the area or time window for detail.</p>}
    </section>}
    {view === 'calls' && <section aria-label="Tanker port calls"><h3>Tanker port-call candidates</h3>
      <p className="caption">At least five minutes below 1 knot within a terminal polygon. Candidates are not verified berth service.</p>
      {!data.configuration.terminal_boundaries ? <Empty>Terminal boundaries not configured for this area. Port discovery boxes do not identify berths.</Empty> :
        data.port_calls.length ? <Stays rows={data.port_calls} calls /> : <Empty>No qualifying tanker terminal stays observed in this window.</Empty>}
    </section>}
    {view === 'waiting' && <section aria-label="Waiting times"><h3>Observed waiting times</h3>
      <p className="caption">Lower-bound stays in reviewed waiting anchorages. Missing intervals are excluded.</p>
      {!data.configuration.reviewed_waiting_boundaries ? <Empty>Reviewed waiting-area boundaries are required. Bunkering and service anchorages are not queues.</Empty> :
        data.waiting_times.length ? <Stays rows={data.waiting_times} /> : <Empty>No qualifying tanker waiting stays observed in this window.</Empty>}
    </section>}
    {view === 'congestion' && <section aria-label="Congestion"><h3>Observed tanker queue</h3>
      <div className="num" style={{fontSize:40}}>{data.congestion.waiting_tankers ?? '—'}</div>
      <p className="caption">{words(data.congestion.status)} · Current observed waiting vessels, not a congestion severity score</p>
      {data.congestion.waiting_tankers == null ? <Empty>A queue count is unavailable until reviewed waiting areas and recent observations are present.</Empty> :
        <Stays rows={data.congestion.observed_waits} />}
    </section>}
    {view === 'transits' && <section aria-label="Checkpoint transit counts"><h3>Checkpoint crossings</h3>
      <p className="caption">Observed tanker gate crossings, not completed strait passages. Directions refer to the signed sides of each ordered gate.</p>
      {!gates.length ? <Empty>No checkpoint gates in the selected area. Choose the entire geography to include its gates.</Empty> :
        <ul className="analytics-list">{gates.map(([id,g]) => <li key={id}><strong>{id}</strong>
          <div className="row"><span>Negative → positive</span><span className="num">{q.observation_status==='no_observations' ? '—' : g.negative_to_positive}</span></div>
          <div className="row"><span>Positive → negative</span><span className="num">{q.observation_status==='no_observations' ? '—' : g.positive_to_negative}</span></div>
          <div className="caption">{g.reviewed_boundary ? 'Reviewed geometry' : 'Experimental · unreviewed geometry'} · {g.source}</div>
        </li>)}</ul>}
    </section>}
    <details className="caption"><summary>Boundaries and method</summary>
      <p>{q.note}</p><p>Boundary version: {data.boundary_version}</p>
      {data.boundaries.map(b => <p key={b.id}>{b.id} · {b.kind} · {b.reviewed ? 'reviewed' : 'unreviewed'} — {b.source}</p>)}
    </details>
  </>;
}
