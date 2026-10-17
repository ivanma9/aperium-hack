import { fromRow, type Geography, type GeographyRow } from "@/lib/geographies";

/**
 * Test fixtures shaped like GET /api/geographies rows. Mirrors the backend seed
 * (aperium/seed.py) for Hormuz and Suez; not used by the app at runtime.
 */
const ROWS: GeographyRow[] = [
  {
    id: "hormuz",
    slug: "hormuz",
    short_name: "Hormuz",
    name: "Strait of Hormuz",
    base_mbd: 20,
    bypass_cap_mbd: 2.6,
    bypass_label: "Pipeline bypass",
    premium_multiplier: 1,
    bbox: [54.85, 24.85, 57.2, 27.25],
    imagery_provider: "SENTINEL-2 L2A",
    lanes: {
      outbound: [[54.4, 25.98], [55.4, 26.16], [56.0, 26.42], [56.35, 26.5], [56.58, 26.44], [56.85, 26.15], [57.6, 25.55]],
      inbound: [[57.6, 25.72], [56.95, 26.25], [56.65, 26.58], [56.35, 26.64], [56.0, 26.54], [55.4, 26.36], [54.4, 26.14]],
    },
    lane_offset_px: null,
    gates: [
      [[56.12, 26.28], [56.12, 26.72]],
      [[56.78, 25.98], [56.78, 26.62]],
    ],
    destinations: {
      outbound: ["Ningbo", "Jamnagar", "Chiba", "Ulsan", "Qingdao", "Rotterdam"],
      inbound: ["Ras Tanura", "Basrah", "Ruwais", "Mina al-Ahmadi", "Kharg"],
    },
    ports: [
      { id: "fujairah", name: "Fujairah", geography_id: "hormuz", bounds_lat_lon: [[25.05, 56.32], [25.28, 56.65]], boundary_type: "approximate_discovery_box" },
      { id: "jebel_ali", name: "Jebel Ali", geography_id: "hormuz", bounds_lat_lon: [[24.9, 54.95], [25.12, 55.15]], boundary_type: "approximate_discovery_box" },
    ],
  },
  {
    id: "suez",
    slug: "suez",
    short_name: "Suez",
    name: "Suez Canal",
    base_mbd: 5,
    bypass_cap_mbd: 2.5,
    bypass_label: "SUMED pipeline",
    premium_multiplier: 0.4,
    bbox: [31.9, 29.75, 32.9, 31.5],
    imagery_provider: "SENTINEL-2 L2A",
    lanes: {
      outbound: [[32.33, 31.45], [32.31, 30.85], [32.4, 30.32], [32.57, 29.8]],
      inbound: [[32.57, 29.8], [32.4, 30.32], [32.31, 30.85], [32.33, 31.45]],
    },
    lane_offset_px: 3,
    gates: [
      [[32.22, 30.85], [32.4, 30.85]],
      [[32.47, 30.05], [32.65, 30.05]],
    ],
    destinations: { outbound: ["Jeddah", "Singapore"], inbound: ["Rotterdam", "Trieste"] },
    ports: [],
  },
];

export const GEOGRAPHIES: Geography[] = ROWS.map(fromRow);
export const HORMUZ = GEOGRAPHIES[0];
export const SUEZ = GEOGRAPHIES[1];
