/**
 * Types + fetchers for the CPI factor picker (`aperium/cpi_factors.py`, schemas `cpi_factors` / `cpi_custom`).
 * Browser calls `/aperium/cpi/*`, rewritten to `${APERIUM_API_URL}/api/cpi/*`. All outputs are uncalibrated.
 */
import { APERIUM_BASE } from "./client";

export type ChokepointId = "hormuz" | "malacca" | "bab_el_mandeb" | "suez";
export type RegionId = "national" | "northeast" | "midwest" | "south" | "west";
export type Case = "low" | "central" | "high";

export interface Envelope {
  schema_version: string;
  as_of_utc: string;
  calibrated: false;
}

export interface Factor {
  id: string;
  label: string;
  kind: "toggle" | "slider" | "locked";
  default: number | boolean | null;
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string | null;
  available: boolean;
  /** Why the control is disabled. */
  reason: string | null;
}

export interface ChokepointInfo {
  id: ChokepointId;
  name: string;
  flow_mbd: number;
  default_bypass_mbd: number;
  default_fraction: number;
  live_available: boolean;
  live_reason: string | null;
}

export type BaselineStatus = "ok" | "partial" | "unavailable";

export interface RegionInfo {
  id: RegionId;
  name: string;
  series: { bls_energy: string; bls_gasoline: string; eia_gasoline: string };
  baseline_status: BaselineStatus;
  data_period: string | null;
}

export interface CpiFactors extends Envelope {
  factors: Factor[];
  chokepoints: ChokepointInfo[];
  regions: RegionInfo[];
}

export interface CaseShock {
  crude_shock_usd_bbl: number;
  gasoline_shock_usd_gal: number;
  energy_cpi_shock_pct: number;
  energy_cpi_index: number | null;
}

export interface Month {
  period: string;
  elevated_pump_days: number;
  days_in_month: number;
  baseline_cpi_energy: number | null;
  low: CaseShock;
  central: CaseShock;
  high: CaseShock;
}

export interface Baseline {
  cpi_energy_last: number | null;
  cpi_energy_period: string | null;
  nowcast_period: string | null;
  nowcast_cpi_energy: number | null;
  nowcast_mom_pct: number | null;
  retail_gasoline_mom_pct: number | null;
  gasoline_share_of_energy: number;
  gasoline_share_source: "bls" | "fallback" | "override" | "national_fallback";
  status: BaselineStatus;
}

export interface Contribution {
  id: string;
  label: string;
  kind: "baseline" | "chokepoint" | "bypass" | "release";
  current_month_pct: number;
  next_month_pct: number;
}

export interface CustomRegion {
  id: RegionId;
  name: string;
  baseline: Baseline;
  /** null when the region has no baseline data. */
  months: { current_month: Month; next_month: Month } | null;
  contributions: Contribution[];
}

export interface SupplyChokepoint {
  id: ChokepointId;
  name: string;
  source: "live" | "manual";
  fraction: number | null;
  at_risk_mbd: number;
  net_mbd: number;
  status: "ok" | "unavailable";
  reason: string | null;
}

export interface CpiCustom extends Envelope {
  supply: {
    chokepoints: SupplyChokepoint[];
    net_before_release_mbd: number;
    release_applied_mbd: number;
    net_supply_loss_mbd: number;
    overlap_warning: boolean;
    net_supply_loss_lower_bound_mbd: number | null;
  };
  regions: CustomRegion[];
  assumptions: string[];
  sources: { name: string; series: string | null; fetched_utc: string | null; status: string }[];
}

/** Query params for /cpi/custom: factor ids, `region`, `chokepoints` (csv), `<id>_fraction`, `<id>_bypass_mbd`, `hormuz_source`. */
export type CustomParams = Record<string, string | number | boolean>;

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${APERIUM_BASE}${path}`, { signal });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchFactors = (signal?: AbortSignal) => getJson<CpiFactors>("/cpi/factors", signal);

export const fetchCustom = (params: CustomParams, signal?: AbortSignal) =>
  getJson<CpiCustom>(`/cpi/custom?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}`, signal);
