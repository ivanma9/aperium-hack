import { describe, expect, it } from "vitest";
import { createMockFeed } from "@/lib/feed/mock";
import { createTidemarkStore } from "./tidemark";

async function setup() {
  const feed = createMockFeed({ now: Date.UTC(2026, 9, 17, 12) });
  const snapshot = await feed.getSnapshot("hormuz", "elevated");
  return { feed, snapshot, store: createTidemarkStore(snapshot) };
}

describe("tidemark store", () => {
  it("hydrates from a snapshot", async () => {
    const { store } = await setup();
    const s = store.getState();
    expect(s.locationId).toBe("hormuz");
    expect(s.vesselOrder).toHaveLength(10);
    expect(s.history).toHaveLength(60);
    expect(Object.values(s.vessels).filter((v) => v.ais === "dark")).toHaveLength(2);
  });

  it("tracks corridor membership from gate crossings", async () => {
    const { store } = await setup();
    const v = store.getState().vessels["538009100"]; // outbound
    const cross = (gate: "a" | "b") =>
      store.getState().apply({
        topic: "vessel.gate.crossed",
        data: { mmsi: v.mmsi, location: "hormuz", gate, direction: "outbound", laden: true, est_cargo_mb: 2, ts: 1 },
      });
    cross("a");
    expect(store.getState().vessels[v.mmsi].inCorridor).toBe(true);
    cross("b");
    expect(store.getState().vessels[v.mmsi].inCorridor).toBe(false);
  });

  it("ignores events for another location or scenario", async () => {
    const { store, snapshot } = await setup();
    const before = store.getState().flow;
    store.getState().apply({ topic: "flow.estimate.updated", data: { ...snapshot.flow, location: "suez", flow_mbd: 1 } });
    expect(store.getState().flow).toBe(before);
    store.getState().apply({ topic: "cpi.energy.recomputed", data: { ...snapshot.outlook, scenario: "closure" } });
    expect(store.getState().outlook).toBe(snapshot.outlook);
  });

  it("drops events while paused", async () => {
    const { store, snapshot } = await setup();
    store.getState().togglePaused();
    store.getState().apply({ topic: "flow.estimate.updated", data: { ...snapshot.flow, flow_mbd: 1 } });
    expect(store.getState().flow.flow_mbd).toBe(snapshot.flow.flow_mbd);
  });

  it("switching location clears the selection; the new snapshot resets bypass readiness", async () => {
    const { store, feed } = await setup();
    store.getState().selectVessel("538009101");
    expect(store.getState().view).toBe("vessels");
    store.getState().setLocation("malacca");
    expect(store.getState().selectedMmsi).toBeNull();
    store.getState().hydrate(await feed.getSnapshot("malacca", "elevated"));
    expect(store.getState().tile.location).toBe("malacca");
    expect(store.getState().outlook.chain.bypassReady).toBe(0);
  });

  it("selecting the selected vessel toggles it off", async () => {
    const { store } = await setup();
    store.getState().selectVessel("538009102");
    store.getState().selectVessel("538009102");
    expect(store.getState().selectedMmsi).toBeNull();
  });
});

describe("mock feed", () => {
  it("produces identical snapshots for the same clock (SSR hydration)", async () => {
    const now = Date.UTC(2026, 9, 17, 12);
    const a = await createMockFeed({ now }).getSnapshot("hormuz", "elevated");
    const b = await createMockFeed({ now }).getSnapshot("hormuz", "elevated");
    expect(a).toEqual(b);
  });

  it("runScenario resets bypass readiness and returns the new outlook", async () => {
    const feed = createMockFeed({ now: 0 });
    await feed.getSnapshot("hormuz", "elevated");
    const out = await feed.runScenario("hormuz", "closure");
    expect(out.scenario).toBe("closure");
    expect(out.chain.bypassReady).toBe(0);
  });
});
