/**
 * Client for the Aperium collector (FastAPI + Postgres, `aperium/app.py`). The browser
 * calls `/aperium/*`, which next.config.ts rewrites to `${APERIUM_API_URL}/api/*`.
 * Response types mirror app.py; timestamps are Unix seconds (UTC).
 */

export const APERIUM_BASE = "/aperium";

export type StreamStatus =
  | "missing_api_key"
  | "connecting"
  | "awaiting_subscription"
  | "subscribed"
  | "receiving"
  | "reconnecting";

export interface CollectorStatus {
  status: StreamStatus;
  last_error: string | null;
  last_position_at: number | null;
  positions_received: number;
  seconds_since_last_position: number | null;
  data_status: "no_positions_received" | "stale" | "recent_positions_received";
  stale_seconds: number;
  now: number;
  event_stream: "listening" | "reconnecting";
}

export interface PortMetrics {
  active_vessels: number;
  slow_vessels_under_1_knot: number;
  reported_anchored: number;
  stale_vessels_in_area: number;
  latest_receipt_at: number | null;
  data_status: "fresh_observations" | "stale_observations_only" | "no_observed_vessels";
}

export interface CollectorMetrics extends PortMetrics {
  by_port: Record<string, PortMetrics>;
  stream_status: StreamStatus;
  note: string;
}

/** A vessel observed by AIS inside a port geofence (`/api/vessels` item, `/api/stream` event). */
export interface AisVessel {
  mmsi: string;
  name: string;
  latitude: number;
  longitude: number;
  speed_knots: number | null;
  course: number | null;
  /** ITU-R M.1371 navigational status code. */
  nav_status: number | null;
  observed_at: number;
  received_at: number;
  time_source: "provider" | "local_receipt";
  age_seconds: number;
  stale: boolean;
  ports: string[];
  inside_geofence: boolean;
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${APERIUM_BASE}${path}`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`Aperium ${path}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const aperium = {
  status: (signal?: AbortSignal) => get<CollectorStatus>("/status", signal),
  metrics: (signal?: AbortSignal) => get<CollectorMetrics>("/metrics", signal),
};

/**
 * Subscribe to `/api/stream` (Server-Sent Events fed by Postgres NOTIFY).
 * `snapshot` replaces the vessel set; `vessel` upserts one. EventSource reconnects on
 * its own; each reconnect starts with a fresh snapshot.
 */
export function subscribeVessels(handlers: {
  onSnapshot: (vessels: AisVessel[]) => void;
  onVessel: (vessel: AisVessel) => void;
  onConnection: (open: boolean) => void;
}): () => void {
  const source = new EventSource(`${APERIUM_BASE}/stream`);
  source.addEventListener("open", () => handlers.onConnection(true));
  source.addEventListener("error", () => handlers.onConnection(false));
  source.addEventListener("snapshot", (e) => handlers.onSnapshot(JSON.parse((e as MessageEvent).data)));
  source.addEventListener("vessel", (e) => handlers.onVessel(JSON.parse((e as MessageEvent).data)));
  return () => source.close();
}

/** ITU-R M.1371 navigational status, for display. */
export const NAV_STATUS: Record<number, string> = {
  0: "Under way using engine",
  1: "At anchor",
  2: "Not under command",
  3: "Restricted manoeuvrability",
  4: "Constrained by draught",
  5: "Moored",
  6: "Aground",
  7: "Engaged in fishing",
  8: "Under way sailing",
  14: "AIS-SART active",
};
