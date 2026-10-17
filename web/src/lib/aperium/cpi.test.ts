import { describe, expect, it } from "vitest";
import { getScenario, SCENARIOS } from "@/config/scenarios";
import { liveView, monthLabel, scenarioToQuery, type CpiCustom, type CpiLive } from "./cpi";

describe("scenarioToQuery", () => {
  it("maps a scenario to a manual chokepoint query", () => {
    expect(scenarioToQuery("hormuz", getScenario("partial"))).toEqual({
      chokepoints: "hormuz",
      hormuz_source: "manual",
      hormuz_fraction: 0.36,
      days: 30,
      region: "national",
    });
  });

  it("converts the slug dashes to underscores", () => {
    const q = scenarioToQuery("bab-el-mandeb", getScenario("partial"));
    expect(q).toMatchObject({ chokepoints: "bab_el_mandeb", bab_el_mandeb_fraction: 0.36, bab_el_mandeb_source: "manual" });
  });

  it("floors negative depth at 0", () => {
    expect(scenarioToQuery("suez", getScenario("deesc"))?.suez_fraction).toBe(0);
  });

  it("returns null for an unknown geography", () => {
    expect(scenarioToQuery("panama", getScenario("partial"))).toBeNull();
  });

  it("clamps days to 1..90", () => {
    const base = SCENARIOS[0];
    expect(scenarioToQuery("hormuz", { ...base, rampDays: 0, holdDays: 0 })?.days).toBe(1);
    expect(scenarioToQuery("hormuz", { ...base, rampDays: 60, holdDays: 60 })?.days).toBe(90);
  });
});

const shock = (energy: number) => ({
  crude_shock_usd_bbl: 10,
  gasoline_shock_usd_gal: 0.2,
  energy_cpi_shock_pct: energy,
  energy_cpi_index: null,
});

function data(price: number | null): CpiCustom {
  return {
    schema_version: "2.1.0",
    as_of_utc: "",
    calibrated: false,
    inputs: { chokepoints: ["hormuz"], region: "national", days: 30, gasoline_share: 0.5, energy_weight: 6.4, reference_gasoline_usd_gal: 3.5 },
    supply: {
      chokepoints: [{ id: "hormuz", name: "Hormuz", source: "manual", fraction: 0.36, at_risk_mbd: 7, net_mbd: 3, status: "ok", reason: null }],
      net_before_release_mbd: 3,
      release_applied_mbd: 1,
      net_supply_loss_mbd: 2,
      overlap_warning: false,
      net_supply_loss_lower_bound_mbd: null,
    },
    regions: [
      {
        id: "national",
        name: "United States",
        baseline: { retail_gasoline_this_month_usd_gal: price } as never,
        months: {
          current_month: { period: "2026-10", elevated_pump_days: 12, days_in_month: 31, low: shock(1), central: shock(5), high: shock(9) } as never,
          next_month: { period: "2026-11", elevated_pump_days: 30, days_in_month: 30, low: shock(2), central: shock(10), high: shock(20) } as never,
        },
        contributions: [],
      },
    ],
    assumptions: [],
    sources: [],
  };
}

describe("liveView", () => {
  it("is null unless live data is ok", () => {
    expect(liveView({ data: null, status: "loading" })).toBeNull();
    expect(liveView({ data: null, status: "unavailable", reason: "x" })).toBeNull();
    expect(liveView({ data: data(4), status: "unavailable" })).toBeNull();
  });

  it("is null when the region has no baseline months", () => {
    const d = data(4);
    d.regions[0].months = null;
    expect(liveView({ data: d, status: "ok" })).toBeNull();
  });

  it("derives headline pp and gasoline % from the response", () => {
    const live: CpiLive = { data: data(4), status: "ok" };
    const v = liveView(live)!;
    expect(v.headlinePp).toBeCloseTo((5 * 6.4) / 100);
    expect(v.gasolinePct).toBeCloseTo(5);
    expect(v.netSupplyLossMbd).toBe(2);
    expect([v.energyLowPct, v.energyHighPct]).toEqual([1, 9]);
    expect(v.source).toContain("manual Hormuz 36%");
  });

  it("exposes next-month values", () => {
    const v = liveView({ data: data(4), status: "ok" })!;
    expect([v.currentLabel, v.currentPumpDays, v.currentDaysInMonth]).toEqual(["Oct", 12, 31]);
    expect(v.next.label).toBe("Nov");
    expect([v.next.pumpDays, v.next.daysInMonth]).toEqual([30, 30]);
    expect([v.next.energyPct, v.next.energyLowPct, v.next.energyHighPct]).toEqual([10, 2, 20]);
    expect(v.next.headlinePp).toBeCloseTo((10 * 6.4) / 100);
  });

  it("is null when next_month is missing", () => {
    const d = data(4);
    d.regions[0].months = { current_month: d.regions[0].months!.current_month } as never;
    expect(liveView({ data: d, status: "ok" })).toBeNull();
  });

  it("monthLabel falls back to the raw period", () => {
    expect(monthLabel("2026-11")).toBe("Nov");
    expect(monthLabel("weird")).toBe("weird");
  });

  it("falls back to the reference gasoline price", () => {
    expect(liveView({ data: data(null), status: "ok" })!.gasolinePct).toBeCloseTo((0.2 / 3.5) * 100);
  });
});
