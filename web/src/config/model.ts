/**
 * Model coefficients. ALL VALUES ARE PLACEHOLDERS — replace with current market
 * prices, BLS CPI relative-importance weights and estimated pass-through rates.
 */

export type PriceDriver = "gasoline" | "brent";

export interface CpiComponentParams {
  id: string;
  name: string;
  /** CPI relative importance, % of basket. */
  weight: number;
  /** Which price move feeds this component. */
  driver: PriceDriver;
  /** Component price % change per 1% move in the driver. */
  elasticity: number;
  /** Share of the full move that reaches CPI within one month. */
  passThrough1m: number;
}

export interface ModelParams {
  brentRefUsd: number;
  gasRefUsd: number;
  /** Brent % move per mb/d of net supply loss. */
  brentPctPerMbd: number;
  /** Brent sensitivity when flow runs above baseline, relative to a loss. */
  surplusDamping: number;
  /** $/gal of retail gasoline per $1/bbl of Brent. */
  gasUsdPerBrentUsd: number;
  /** Stream events for the bypass to ramp from 0 to full after a shock. */
  bypassRampEvents: number;
  /** Core CPI pp per 1% Brent move, at full spillover. */
  corePpPerBrentPct: number;
  /** Share of the core spillover visible after one month. */
  corePassThrough1m: number;
  components: readonly CpiComponentParams[];
}

export const DEFAULT_MODEL_PARAMS: ModelParams = {
  brentRefUsd: 70,
  gasRefUsd: 3.2,
  brentPctPerMbd: 6,
  surplusDamping: 0.5,
  gasUsdPerBrentUsd: 0.024,
  bypassRampEvents: 15,
  corePpPerBrentPct: 0.003,
  corePassThrough1m: 0.15,
  components: [
    { id: "motor_fuel", name: "Motor fuel", weight: 3.3, driver: "gasoline", elasticity: 1, passThrough1m: 0.85 },
    { id: "electricity", name: "Electricity", weight: 2.5, driver: "brent", elasticity: 0.04, passThrough1m: 0.2 },
    { id: "utility_gas", name: "Utility gas", weight: 0.7, driver: "brent", elasticity: 0.12, passThrough1m: 0.35 },
    { id: "fuel_oil", name: "Fuel oil", weight: 0.1, driver: "brent", elasticity: 0.8, passThrough1m: 0.9 },
  ],
};
