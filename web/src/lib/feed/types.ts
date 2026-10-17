import type { Outlook } from "@/lib/model";

/**
 * Wire types for the Tidemark feed (HANDOFF §6). Names are placeholders until
 * the backend contract is final; keep them in sync with the OpenAPI/AsyncAPI spec.
 */

export type Direction = "outbound" | "inbound";
export type VesselClass = "VLCC" | "Suezmax" | "Aframax";
export type GateId = "a" | "b";

export interface AisPosition {
  mmsi: string;
  lat: number;
  lon: number;
  sog_kn: number;
  heading: number;
  ts: number;
}

export interface GateCrossing {
  mmsi: string;
  location: string;
  gate: GateId;
  direction: Direction;
  laden: boolean;
  est_cargo_mb: number;
  ts: number;
}

export interface ImageryTile {
  location: string;
  provider: string;
  tile_id: string;
  captured_at: string;
  cloud_pct: number;
  gsd_m: number;
}

export interface FlowEstimate {
  location: string;
  flow_mbd: number;
  ratio: number;
  ci_mbd: number;
  window_h: number;
  ts: number;
}

export interface CpiRecomputed {
  location: string;
  scenario: string;
  horizon: "1m";
  energy_pct: number;
  headline_pp: number;
  core_pp: number;
  chain: Outlook;
  ts: number;
}

export interface AisGap {
  mmsi: string;
  location: string;
  dark_hours: number;
  sar_match: boolean;
  ts: number;
}

export type FeedEvent =
  | { topic: "ais.position.v2"; data: AisPosition }
  | { topic: "vessel.gate.crossed"; data: GateCrossing }
  | { topic: "imagery.tile.ingested"; data: ImageryTile }
  | { topic: "flow.estimate.updated"; data: FlowEstimate }
  | { topic: "cpi.energy.recomputed"; data: CpiRecomputed }
  | { topic: "ais.gap.detected"; data: AisGap };

export type FeedTopic = FeedEvent["topic"];

/** Vessel record as returned by `GET /v1/vessels?zone=corridor&location=`. */
export interface Vessel {
  mmsi: string;
  name: string;
  vesselClass: VesselClass;
  direction: Direction;
  laden: boolean;
  cargo: string;
  cargoMb: number;
  destination: string;
  ais: "live" | "dark";
  inCorridor: boolean;
  position: AisPosition;
}

/** Initial state for a location: REST reads stitched together. */
export interface Snapshot {
  location: string;
  scenario: string;
  ts: number;
  tile: ImageryTile;
  flow: FlowEstimate;
  /** Last 60 flow ratios, oldest first. */
  history: number[];
  vessels: Vessel[];
  outlook: CpiRecomputed;
}

/**
 * Transport-agnostic client. The mock implements it in-process; the real one
 * maps to REST (`getSnapshot`, `runScenario`) and the WebSocket (`subscribe`).
 */
export interface FeedClient {
  getSnapshot(geographyId: string, scenarioId: string): Promise<Snapshot>;
  runScenario(geographyId: string, scenarioId: string): Promise<CpiRecomputed>;
  /** Returns an unsubscribe function. */
  subscribe(onEvent: (e: FeedEvent) => void): () => void;
}
