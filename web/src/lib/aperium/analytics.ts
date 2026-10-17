import { APERIUM_BASE } from './client';

export type AnalyticsView = 'classification' | 'calls' | 'waiting' | 'congestion' | 'transits';
export const ANALYTICS_VIEWS: { id: AnalyticsView; label: string }[] = [
  { id: 'classification', label: 'Classification' }, { id: 'calls', label: 'Port calls' },
  { id: 'waiting', label: 'Waiting times' }, { id: 'congestion', label: 'Congestion' },
  { id: 'transits', label: 'Crossings' },
];
export interface Stay {
  id: string; mmsi: string; boundary_id: string; port: string;
  kind: 'terminal_call_candidate' | 'anchorage_stay';
  reviewed_boundary: boolean; entry_observed: boolean;
  first_seen_at: number; last_seen_at: number; observed_seconds: number;
  departure_observed_at: number | null; end_reason: string;
  observed_prior_wait_seconds?: number | null;
}
export interface Boundary {
  id: string; kind: 'terminal' | 'anchorage' | 'checkpoint'; port: string; geography_id: string;
  source: string; reviewed: boolean; purpose: 'waiting' | 'service' | 'unknown'; coordinates: number[][];
}
export interface AnalyticsResult {
  geography_id: string; port: string | null; window_hours: number; generated_at: number;
  stream_status: string; boundary_version: string; boundaries: Boundary[];
  classification: { mmsi: string; name: string; vessel_class: string; ship_type: number | null;
    source: string | null; last_seen_at: number; stale: boolean; classification_updated_at: number | null }[];
  port_calls: Stay[]; waiting_times: Stay[];
  configuration: { terminal_boundaries: number; reviewed_waiting_boundaries: number };
  transit_counts: Record<string, { reviewed_boundary: boolean; source: string; negative_to_positive: number; positive_to_negative: number }>;
  congestion: { status: string; waiting_tankers: number | null; observed_waits: Stay[];
    by_boundary: Record<string, { port: string; waiting_tankers: number; source: string }> };
  quality: { observed_vessels: number; tanker_vessels: number; unclassified_vessels: number;
    discontinuities: number; coverage_completeness: string; observation_status: string;
    latest_observed_at: number | null; note: string };
}
export async function fetchAnalytics(geography: string, hours: number, port: string, signal: AbortSignal): Promise<AnalyticsResult> {
  const query = new URLSearchParams({ geography, hours: String(hours) });
  if (port) query.set('port', port);
  const response = await fetch(`${APERIUM_BASE}/analytics?${query}`, { signal, cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Analytics request failed (HTTP ${response.status})`);
  }
  return response.json();
}
export const duration = (seconds: number | null | undefined) => seconds == null ? 'Unknown' :
  seconds < 3600 ? `${Math.floor(seconds / 60)} min` : `${(seconds / 3600).toFixed(1)} h`;
