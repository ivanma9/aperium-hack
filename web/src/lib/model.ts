import type { Geography } from "@/lib/geographies";
import type { ModelParams } from "@/config/model";
import type { ScenarioConfig } from "@/config/scenarios";

/**
 * Flow → Brent → gasoline → energy CPI → headline CPI, one-month horizon.
 * Pure and config-driven so the model service, REST, MCP and the mock feed all
 * share it.
 */

export interface OutlookInput {
  geography: Geography;
  scenario: ScenarioConfig;
  /** Observed / baseline flow ratio from gate crossings. */
  ratio: number;
  /** Events since the last shock (scenario or location change); ramps the bypass. */
  eventsSinceShock: number;
}

export interface ComponentContribution {
  id: string;
  name: string;
  weight: number;
  /** Component price change after one month, %. */
  deltaPct: number;
  /** Contribution to headline CPI, pp. */
  pp: number;
}

export interface Outlook {
  flowMbd: number;
  gapMbd: number;
  bypassMbd: number;
  netMbd: number;
  bypassReady: number;
  brentPct: number;
  brentUsd: number;
  gasPct: number;
  components: ComponentContribution[];
  energyWeight: number;
  energyPct: number;
  headlinePp: number;
  corePp: number;
}

export function computeOutlook(input: OutlookInput, params: ModelParams): Outlook {
  const { geography, scenario, ratio, eventsSinceShock } = input;
  const base = geography.baseMbd;

  const flowMbd = base * ratio;
  const gapMbd = base - flowMbd;
  const bypassReady = Math.min(1, Math.max(0, eventsSinceShock / params.bypassRampEvents));
  const bypassMbd = gapMbd > 0 ? Math.min(geography.bypassCapMbd, gapMbd) * bypassReady : 0;
  const netMbd = Math.max(0, gapMbd - bypassMbd);

  const supplyPct =
    gapMbd > 0 ? netMbd * params.brentPctPerMbd : gapMbd * params.brentPctPerMbd * params.surplusDamping;
  const brentPct = supplyPct + scenario.premiumPct * geography.premiumMultiplier;
  const brentUsd = params.brentRefUsd * (1 + brentPct / 100);
  const gasPct = ((params.gasUsdPerBrentUsd * (brentUsd - params.brentRefUsd)) / params.gasRefUsd) * 100;

  const components = params.components.map((c) => {
    const driverPct = c.driver === "gasoline" ? gasPct : brentPct;
    const deltaPct = driverPct * c.elasticity * c.passThrough1m;
    return { id: c.id, name: c.name, weight: c.weight, deltaPct, pp: (c.weight * deltaPct) / 100 };
  });

  const energyWeight = components.reduce((a, c) => a + c.weight, 0);
  const headlinePp = components.reduce((a, c) => a + c.pp, 0);
  const energyPct = energyWeight > 0 ? (headlinePp / energyWeight) * 100 : 0;
  const corePp = params.corePpPerBrentPct * brentPct * params.corePassThrough1m;

  return {
    flowMbd,
    gapMbd,
    bypassMbd,
    netMbd,
    bypassReady,
    brentPct,
    brentUsd,
    gasPct,
    components,
    energyWeight,
    energyPct,
    headlinePp,
    corePp,
  };
}

/** Shock intensity 0..1 on day `d` of the scenario. */
export function shockAt(scenario: ScenarioConfig, d: number): number {
  if (d < scenario.onsetDays) return 0;
  const a = d - scenario.onsetDays;
  if (a < scenario.rampDays) return a / scenario.rampDays;
  const b = a - scenario.rampDays;
  if (b < scenario.holdDays) return 1;
  return Math.max(0, 1 - (b - scenario.holdDays) / scenario.recoveryDays);
}

export interface SupplyPoint {
  day: number;
  /** Transit flow, mb/d. */
  transitMbd: number;
  /** Effective supply including the bypass, mb/d. */
  withBypassMbd: number;
  sigmaMbd: number;
}

export interface SupplyForecast {
  points: SupplyPoint[];
  troughMbd: number;
  /** Cumulative barrels lost after bypass, mb. */
  cumulativeLossMb: number;
}

/** Days for the bypass to reach full capacity in the 90-day path. */
const BYPASS_RAMP_DAYS = 10;

export function forecastSupply(
  geography: Geography,
  scenario: ScenarioConfig,
  { horizonDays = 90, stepDays = 2 }: { horizonDays?: number; stepDays?: number } = {},
): SupplyForecast {
  const base = geography.baseMbd;
  const points: SupplyPoint[] = [];
  for (let day = 0; day <= horizonDays; day += stepDays) {
    const transitMbd = base * (1 - scenario.depth * shockAt(scenario, day));
    const withBypassMbd =
      scenario.depth > 0
        ? transitMbd + Math.min(base - transitMbd, geography.bypassCapMbd) * Math.min(1, day / BYPASS_RAMP_DAYS)
        : transitMbd;
    points.push({ day, transitMbd, withBypassMbd, sigmaMbd: scenario.sigmaMbd * (0.3 + day / horizonDays) });
  }
  const cumulativeLossMb = points.reduce((a, p) => a + Math.max(0, base - p.withBypassMbd) * stepDays, 0);
  const troughMbd = Math.min(...points.map((p) => p.transitMbd));
  return { points, troughMbd, cumulativeLossMb };
}
