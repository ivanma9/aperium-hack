import { createStore } from "zustand/vanilla";
import { getLocation, LOCATIONS } from "@/config/locations";
import type {
  CpiRecomputed,
  Direction,
  FeedEvent,
  FeedTopic,
  FlowEstimate,
  ImageryTile,
  Snapshot,
  Vessel,
} from "@/lib/feed/types";

export type ViewId = "flow" | "vessels" | "supply" | "cpi" | "connect";

export interface VesselView extends Vessel {
  /** Position jumped (lap wrap / new location), so don't animate this move. */
  jumped: boolean;
}

export interface TidemarkState {
  locationId: string;
  scenarioId: string;
  view: ViewId;
  hudVisible: boolean;
  paused: boolean;
  selectedMmsi: string | null;

  clock: number;
  lastTopic: FeedTopic;
  tile: ImageryTile;
  flow: FlowEstimate;
  history: number[];
  vessels: Record<string, VesselView>;
  vesselOrder: string[];
  outlook: CpiRecomputed;
}

export interface TidemarkActions {
  hydrate(snapshot: Snapshot): void;
  apply(event: FeedEvent): void;
  setLocation(id: string): void;
  setScenario(id: string): void;
  setOutlook(outlook: CpiRecomputed): void;
  setView(view: ViewId): void;
  toggleHud(): void;
  togglePaused(): void;
  selectVessel(mmsi: string | null): void;
}

export type TidemarkStore = TidemarkState & TidemarkActions;

/** Gate a vessel crosses on its way into the corridor. */
const entryGate = (d: Direction) => (d === "outbound" ? "a" : "b");

/** Share of the bbox width beyond which a position update counts as a jump. */
const JUMP_FRACTION = 0.15;

const slugToId = (slug: string) => LOCATIONS.find((l) => l.slug === slug)?.id;

function fromSnapshot(s: Snapshot) {
  return {
    locationId: slugToId(s.location) ?? s.location,
    scenarioId: s.scenario,
    clock: s.ts,
    tile: s.tile,
    flow: s.flow,
    history: s.history,
    outlook: s.outlook,
    vessels: Object.fromEntries(s.vessels.map((v) => [v.mmsi, { ...v, jumped: true }])),
    vesselOrder: s.vessels.map((v) => v.mmsi),
  };
}

export function createTidemarkStore(initial: Snapshot) {
  return createStore<TidemarkStore>()((set, get) => {
    /** Events for another location are stale (in flight during a switch). */
    const isCurrent = (slug: string) => getLocation(get().locationId).slug === slug;

    return {
      ...fromSnapshot(initial),
      view: "flow",
      hudVisible: true,
      paused: false,
      selectedMmsi: null,
      lastTopic: "flow.estimate.updated",

      hydrate: (snapshot) => set(fromSnapshot(snapshot)),

      apply: (e) => {
        const s = get();
        if (s.paused) return;
        const ts = "ts" in e.data ? e.data.ts : s.clock;
        const base = { lastTopic: e.topic, clock: Math.max(s.clock, ts) };

        switch (e.topic) {
          case "ais.position.v2": {
            const v = s.vessels[e.data.mmsi];
            if (!v) return set(base);
            const [w, , east] = getLocation(s.locationId).bbox;
            const jumped = Math.abs(e.data.lon - v.position.lon) > (east - w) * JUMP_FRACTION;
            return set({ ...base, vessels: { ...s.vessels, [v.mmsi]: { ...v, position: e.data, jumped } } });
          }
          case "vessel.gate.crossed": {
            const v = s.vessels[e.data.mmsi];
            if (!v || !isCurrent(e.data.location)) return set(base);
            const inCorridor = e.data.gate === entryGate(e.data.direction);
            return set({ ...base, vessels: { ...s.vessels, [v.mmsi]: { ...v, inCorridor } } });
          }
          case "ais.gap.detected": {
            const v = s.vessels[e.data.mmsi];
            if (!v || !isCurrent(e.data.location)) return set(base);
            return set({ ...base, vessels: { ...s.vessels, [v.mmsi]: { ...v, ais: "dark" } } });
          }
          case "imagery.tile.ingested":
            if (!isCurrent(e.data.location)) return;
            return set({ ...base, tile: e.data });
          case "flow.estimate.updated":
            if (!isCurrent(e.data.location)) return;
            return set({ ...base, flow: e.data, history: [...s.history.slice(1), e.data.ratio] });
          case "cpi.energy.recomputed":
            if (!isCurrent(e.data.location) || e.data.scenario !== s.scenarioId) return;
            return set({ ...base, outlook: e.data });
        }
      },

      setLocation: (id) => set({ locationId: getLocation(id).id, selectedMmsi: null }),
      setScenario: (id) => set({ scenarioId: id }),
      setOutlook: (outlook) => {
        if (outlook.scenario === get().scenarioId && isCurrent(outlook.location)) set({ outlook });
      },
      setView: (view) => set({ view }),
      toggleHud: () => set((s) => ({ hudVisible: !s.hudVisible })),
      togglePaused: () => set((s) => ({ paused: !s.paused })),
      selectVessel: (mmsi) =>
        set((s) => ({
          selectedMmsi: mmsi && s.selectedMmsi !== mmsi ? mmsi : null,
          view: mmsi ? "vessels" : s.view,
        })),
    };
  });
}

export type TidemarkStoreApi = ReturnType<typeof createTidemarkStore>;
