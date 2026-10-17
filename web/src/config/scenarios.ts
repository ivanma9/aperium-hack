/**
 * Geopolitical scenarios. `depth` is the share of flow lost at peak (negative =
 * flow above baseline). ramp/hold/recovery are in days and drive the 90-day path.
 */
export interface ScenarioConfig {
  id: string;
  name: string;
  depth: number;
  /** Brent risk premium, %. Scaled per location by `premiumMultiplier`. */
  premiumPct: number;
  onsetDays: number;
  rampDays: number;
  holdDays: number;
  recoveryDays: number;
  /** Forecast uncertainty, mb/d. */
  sigmaMbd: number;
}

export const SCENARIOS: readonly ScenarioConfig[] = [
  { id: "base", name: "Baseline", depth: 0, premiumPct: 0, onsetDays: 0, rampDays: 1, holdDays: 0, recoveryDays: 1, sigmaMbd: 0.5 },
  { id: "elevated", name: "Tension", depth: 0.07, premiumPct: 5, onsetDays: 0, rampDays: 6, holdDays: 40, recoveryDays: 30, sigmaMbd: 0.9 },
  { id: "partial", name: "Disruption", depth: 0.36, premiumPct: 8, onsetDays: 0, rampDays: 5, holdDays: 25, recoveryDays: 35, sigmaMbd: 1.7 },
  { id: "closure", name: "Closure", depth: 0.85, premiumPct: 12, onsetDays: 0, rampDays: 3, holdDays: 21, recoveryDays: 40, sigmaMbd: 2.6 },
  { id: "deesc", name: "De-escalation", depth: -0.02, premiumPct: -3, onsetDays: 0, rampDays: 20, holdDays: 90, recoveryDays: 1, sigmaMbd: 0.5 },
];

export const DEFAULT_SCENARIO_ID = "elevated";

export function getScenario(id: string): ScenarioConfig {
  return SCENARIOS.find((s) => s.id === id) ?? SCENARIOS[0];
}
