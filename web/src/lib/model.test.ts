import { describe, expect, it } from "vitest";
import { DEFAULT_MODEL_PARAMS } from "@/config/model";
import { getScenario } from "@/config/scenarios";
import { HORMUZ, SUEZ } from "@/test/fixtures";
import { computeOutlook, forecastSupply, shockAt } from "./model";

const hormuz = HORMUZ;
const params = DEFAULT_MODEL_PARAMS;

describe("computeOutlook", () => {
  it("matches the prototype at its opening state (Hormuz, Tension, r=0.93)", () => {
    const o = computeOutlook({ geography: hormuz, scenario: getScenario("elevated"), ratio: 0.93, eventsSinceShock: 30 }, params);
    expect(o.flowMbd).toBeCloseTo(18.6, 6);
    expect(o.gapMbd).toBeCloseTo(1.4, 6);
    // Gap is within bypass capacity and the bypass is fully ramped → no net loss.
    expect(o.bypassMbd).toBeCloseTo(1.4, 6);
    expect(o.netMbd).toBe(0);
    expect(o.brentPct).toBeCloseTo(5, 6);
    expect(o.brentUsd).toBeCloseTo(73.5, 6);
    expect(o.gasPct).toBeCloseTo(2.625, 6);
    expect(o.headlinePp).toBeCloseTo(0.079706, 5);
    expect(o.energyWeight).toBeCloseTo(6.6, 6);
    expect(o.energyPct).toBeCloseTo(1.2077, 3);
    expect(o.corePp).toBeCloseTo(0.00225, 6);
  });

  it("ramps the bypass from zero after a shock", () => {
    const input = { geography: hormuz, scenario: getScenario("closure"), ratio: 0.15 };
    const fresh = computeOutlook({ ...input, eventsSinceShock: 0 }, params);
    const half = computeOutlook({ ...input, eventsSinceShock: 7.5 }, params);
    const full = computeOutlook({ ...input, eventsSinceShock: 100 }, params);
    expect(fresh.bypassMbd).toBe(0);
    expect(half.bypassMbd).toBeCloseTo(1.3, 6);
    expect(full.bypassMbd).toBeCloseTo(hormuz.bypassCapMbd, 6);
    expect(full.netMbd).toBeCloseTo(17 - 2.6, 6);
    expect(fresh.energyPct).toBeGreaterThan(full.energyPct);
  });

  it("damps the price response when flow runs above baseline", () => {
    const o = computeOutlook({ geography: hormuz, scenario: getScenario("base"), ratio: 1.02, eventsSinceShock: 30 }, params);
    expect(o.gapMbd).toBeCloseTo(-0.4, 6);
    expect(o.bypassMbd).toBe(0);
    expect(o.netMbd).toBe(0);
    expect(o.brentPct).toBeCloseTo(-0.4 * 6 * 0.5, 6);
    expect(o.energyPct).toBeLessThan(0);
  });

  it("scales the risk premium per location", () => {
    const o = computeOutlook({ geography: SUEZ, scenario: getScenario("closure"), ratio: 1, eventsSinceShock: 30 }, params);
    expect(o.brentPct).toBeCloseTo(12 * 0.4, 6);
  });

  it("uses configurable coefficients", () => {
    const o = computeOutlook(
      { geography: hormuz, scenario: getScenario("base"), ratio: 0.9, eventsSinceShock: 0 },
      { ...params, brentPctPerMbd: 10 },
    );
    expect(o.brentPct).toBeCloseTo(2 * 10, 6);
  });
});

describe("shockAt", () => {
  it("ramps, holds and recovers", () => {
    const sc = getScenario("partial"); // ramp 5, hold 25, recovery 35
    expect(shockAt(sc, 0)).toBe(0);
    expect(shockAt(sc, 2.5)).toBeCloseTo(0.5);
    expect(shockAt(sc, 10)).toBe(1);
    expect(shockAt(sc, 30 + 17.5)).toBeCloseTo(0.5);
    expect(shockAt(sc, 200)).toBe(0);
  });
});

describe("forecastSupply", () => {
  it("is flat with no loss in the baseline scenario", () => {
    const f = forecastSupply(hormuz, getScenario("base"));
    expect(f.points).toHaveLength(46);
    expect(f.troughMbd).toBeCloseTo(20, 6);
    expect(f.cumulativeLossMb).toBe(0);
  });

  it("reports the closure trough and a bypass-reduced loss", () => {
    const f = forecastSupply(hormuz, getScenario("closure"));
    expect(f.troughMbd).toBeCloseTo(20 * 0.15, 6);
    const withBypass = f.points.find((p) => p.day === 20)!;
    expect(withBypass.withBypassMbd - withBypass.transitMbd).toBeCloseTo(2.6, 6);
    expect(f.cumulativeLossMb).toBeGreaterThan(0);
  });
});
