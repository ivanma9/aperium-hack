/**
 * Monitored geographies and their port geofences. The source of truth is Postgres
 * (`geographies` and `ports` tables), served by the collector at GET /api/geographies.
 * Geometry is [lon, lat]; port bounds keep the API's [[south, west], [north, east]] order.
 */

export type LonLat = readonly [lon: number, lat: number];

export interface PortGeofence {
  id: string;
  name: string;
  geographyId: string | null;
  /** [[south, west], [north, east]] in degrees. Approximate discovery box, not an anchorage boundary. */
  bounds_lat_lon: readonly [readonly [number, number], readonly [number, number]];
  boundary_type: string;
}

export interface Geography {
  id: string;
  /** API slug, used in REST paths. */
  slug: string;
  short: string;
  name: string;
  /** Baseline transit flow, mb/d. */
  baseMbd: number;
  /** Max flow the bypass (pipeline or reroute) can absorb, mb/d. */
  bypassCapMbd: number;
  bypassLabel: string;
  /** Scales the scenario risk premium for this geography. */
  premiumMultiplier: number;
  /** [west, south, east, north]: the area the map frames. */
  bbox: readonly [number, number, number, number];
  imageryProvider: string;
  lanes: { outbound: readonly LonLat[]; inbound: readonly LonLat[] };
  /** Pixel offset between the two lanes when they share one centerline. */
  laneOffsetPx: number | null;
  /** Corridor gates; flow counts laden crossings between them. */
  gates: readonly (readonly LonLat[])[];
  destinations: { outbound: readonly string[]; inbound: readonly string[] };
  ports: readonly PortGeofence[];
}

/** Row shape of GET /api/geographies (aperium/db.py). */
export interface GeographyRow {
  id: string;
  slug: string;
  short_name: string;
  name: string;
  base_mbd: number;
  bypass_cap_mbd: number;
  bypass_label: string;
  premium_multiplier: number;
  bbox: [number, number, number, number];
  imagery_provider: string | null;
  lanes: { outbound: [number, number][]; inbound: [number, number][] };
  lane_offset_px: number | null;
  gates: [number, number][][];
  destinations: { outbound: string[]; inbound: string[] };
  ports: {
    id: string;
    name: string;
    geography_id: string | null;
    bounds_lat_lon: [[number, number], [number, number]];
    boundary_type: string;
  }[];
}

export function fromRow(r: GeographyRow): Geography {
  return {
    id: r.id,
    slug: r.slug,
    short: r.short_name,
    name: r.name,
    baseMbd: r.base_mbd,
    bypassCapMbd: r.bypass_cap_mbd,
    bypassLabel: r.bypass_label,
    premiumMultiplier: r.premium_multiplier,
    bbox: r.bbox,
    imageryProvider: r.imagery_provider ?? "",
    lanes: r.lanes,
    laneOffsetPx: r.lane_offset_px,
    gates: r.gates,
    destinations: r.destinations,
    ports: r.ports.map((p) => ({
      id: p.id,
      name: p.name,
      geographyId: p.geography_id,
      bounds_lat_lon: p.bounds_lat_lon,
      boundary_type: p.boundary_type,
    })),
  };
}

/** Server-side read of the geographies (page render). Throws if the collector is unreachable. */
export async function fetchGeographies(baseUrl: string): Promise<Geography[]> {
  const res = await fetch(`${baseUrl}/api/geographies`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
  if (!res.ok) throw new Error(`GET /api/geographies: HTTP ${res.status}`);
  const rows = (await res.json()) as GeographyRow[];
  if (!rows.length) throw new Error("GET /api/geographies returned no geographies");
  return rows.map(fromRow);
}

export function findGeography(list: readonly Geography[], id: string): Geography {
  return list.find((g) => g.id === id) ?? list[0];
}

/** Geography owning a port, by the API slug used in feed events. */
export function findBySlug(list: readonly Geography[], slug: string): Geography | undefined {
  return list.find((g) => g.slug === slug);
}
