import { describe, expect, it } from "vitest";
import type { AisVessel } from "@/lib/aperium/client";
import { createMockFeed } from "@/lib/feed/mock";
import { GEOGRAPHIES } from "@/test/fixtures";
import { aisInGeography, createTidemarkStore, selectGeography } from "./tidemark";

const NOW = Date.UTC(2026, 9, 17, 12);

async function setup() {
  const feed = createMockFeed({ geographies: GEOGRAPHIES, now: NOW });
  const snapshot = await feed.getSnapshot("hormuz", "elevated");
  return { feed, snapshot, store: createTidemarkStore(GEOGRAPHIES, snapshot) };
}

function aisVessel(overrides: Partial<AisVessel> = {}): AisVessel {
  return {
    mmsi: "403000001",
    name: "LIVE ONE",
    latitude: 25.16,
    longitude: 56.4,
    speed_knots: 0.4,
    course: 30,
    nav_status: 1,
    observed_at: NOW / 1000,
    received_at: NOW / 1000,
    time_source: "provider",
    age_seconds: 1,
    stale: false,
    ports: ["fujairah"],
    inside_geofence: true,
    ...overrides,
  };
}

describe("tidemark store", () => {
  it("keeps analytics area selection in sync without switching views or toggling it off", async () => {
    const { store } = await setup();
    store.getState().setView("analytics");
    store.getState().setAnalyticsPort("fujairah");
    store.getState().setAnalyticsPort("fujairah");
    expect(store.getState().selectedPortId).toBe("fujairah");
    expect(store.getState().view).toBe("analytics");
    store.getState().setAnalyticsPort("jebel_ali");
    expect(store.getState().selectedPortId).toBe("jebel_ali");
    store.getState().setAnalyticsPort(null);
    expect(store.getState().selectedPortId).toBeNull();
    store.getState().setAnalyticsPort("fujairah");
    store.getState().setGeography("suez");
    expect(store.getState().selectedPortId).toBeNull();
    store.getState().setAnalyticsPort("fujairah");
    expect(store.getState().selectedPortId).toBeNull();
  });

  it("hydrates from a snapshot, with geographies from the backend", async () => {
    const { store } = await setup();
    const s = store.getState();
    expect(s.geographyId).toBe("hormuz");
    expect(selectGeography(s).ports.map((p) => p.id)).toEqual(["fujairah", "jebel_ali"]);
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

  it("ignores events for another geography or scenario", async () => {
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
    store.getState().aisUpsert(aisVessel());
    expect(store.getState().ais.vessels).toEqual({});
  });

  it("switching geography clears selection and hover; the new snapshot resets bypass readiness", async () => {
    const { store, feed } = await setup();
    store.getState().selectShip({ source: "sim", mmsi: "538009101" });
    store.getState().hoverShip({ source: "sim", mmsi: "538009102" });
    store.getState().selectPort("fujairah");
    store.getState().setGeography("suez");
    const s = store.getState();
    expect([s.selected, s.hovered, s.selectedPortId]).toEqual([null, null, null]);
    store.getState().hydrate(await feed.getSnapshot("suez", "elevated"));
    expect(store.getState().tile.location).toBe("suez");
    expect(store.getState().outlook.chain.bypassReady).toBe(0);
  });
});

describe("ship hover and selection", () => {
  it("selecting a ship pins it in the Vessels view; selecting it again unpins", async () => {
    const { store } = await setup();
    const ref = { source: "ais" as const, mmsi: "403000001" };
    store.getState().selectShip(ref);
    expect(store.getState().view).toBe("vessels");
    expect(store.getState().selected).toEqual(ref);
    store.getState().selectShip(ref);
    expect(store.getState().selected).toBeNull();
  });

  it("the same MMSI from different sources is a different ship", async () => {
    const { store } = await setup();
    store.getState().selectShip({ source: "sim", mmsi: "538009100" });
    store.getState().selectShip({ source: "ais", mmsi: "538009100" });
    expect(store.getState().selected).toEqual({ source: "ais", mmsi: "538009100" });
  });

  it("hover does not change the view or the pinned ship", async () => {
    const { store } = await setup();
    store.getState().setView("cpi");
    store.getState().hoverShip({ source: "sim", mmsi: "538009100" });
    expect(store.getState().view).toBe("cpi");
    expect(store.getState().selected).toBeNull();
  });
});

describe("live AIS (SSE)", () => {
  it("snapshot replaces, events upsert, and only the current geography's ports count", async () => {
    const { store } = await setup();
    store.getState().aisSnapshot([aisVessel(), aisVessel({ mmsi: "403000002", ports: ["jebel_ali"] })]);
    store.getState().aisUpsert(aisVessel({ latitude: 25.2 }));
    store.getState().aisUpsert(aisVessel({ mmsi: "403000003", ports: ["somewhere_else"] }));
    expect(Object.keys(store.getState().ais.vessels).sort()).toEqual(["403000001", "403000002", "403000003"]);
    expect(store.getState().ais.vessels["403000001"].latitude).toBe(25.2);
    expect(aisInGeography(store.getState()).map((v) => v.mmsi).sort()).toEqual(["403000001", "403000002"]);
    store.getState().setGeography("suez");
    expect(aisInGeography(store.getState())).toEqual([]);
  });
});

describe("mock feed", () => {
  it("produces identical snapshots for the same clock (SSR hydration)", async () => {
    const a = await createMockFeed({ geographies: GEOGRAPHIES, now: NOW }).getSnapshot("hormuz", "elevated");
    const b = await createMockFeed({ geographies: GEOGRAPHIES, now: NOW }).getSnapshot("hormuz", "elevated");
    expect(a).toEqual(b);
  });

  it("places simulated ships on the geography's lanes, in lon/lat", async () => {
    const snap = await createMockFeed({ geographies: GEOGRAPHIES, now: NOW }).getSnapshot("hormuz", "elevated");
    const [w, s, e, n] = [54.3, 25.4, 57.7, 26.8];
    for (const v of snap.vessels) {
      expect(v.position.lon).toBeGreaterThan(w);
      expect(v.position.lon).toBeLessThan(e);
      expect(v.position.lat).toBeGreaterThan(s);
      expect(v.position.lat).toBeLessThan(n);
    }
  });

  it("runScenario resets bypass readiness and returns the new outlook", async () => {
    const feed = createMockFeed({ geographies: GEOGRAPHIES, now: 0 });
    await feed.getSnapshot("hormuz", "elevated");
    const out = await feed.runScenario("hormuz", "closure");
    expect(out.scenario).toBe("closure");
    expect(out.chain.bypassReady).toBe(0);
  });
});
