import { createStore } from "zustand/vanilla";
import type { AisVessel, CollectorMetrics, CollectorStatus } from "@/lib/aperium/client";
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
import { findBySlug, findGeography, type Geography } from "@/lib/geographies";

export type ViewId = "flow" | "vessels" | "ports" | "supply" | "cpi" | "connect";

/** Ships come from two places: simulated corridor traffic (mock feed) and live AIS (collector). */
export type ShipSource = "sim" | "ais";
export interface ShipRef {
  source: ShipSource;
  mmsi: string;
}

/** Aperium collector status + metrics, polled over REST. `reachable: null` = not checked yet. */
export interface CollectorState {
  reachable: boolean | null;
  status: CollectorStatus | null;
  metrics: CollectorMetrics | null;
}

/** Live AIS vessels from the collector's SSE stream (Postgres NOTIFY). */
export interface AisState {
  /** null = not connected yet, false = disconnected (EventSource retries). */
  connected: boolean | null;
  vessels: Record<string, AisVessel>;
}

export interface TidemarkState {
  /** Monitored geographies from GET /api/geographies (Postgres `geographies` + `ports`). */
  geographies: readonly Geography[];
  geographyId: string;
  scenarioId: string;
  view: ViewId;
  hudVisible: boolean;
  paused: boolean;
  /** Pinned by click/tap; shown in the Vessels view. */
  selected: ShipRef | null;
  /** Under the pointer or keyboard focus; previewed in the info panel. */
  hovered: ShipRef | null;
  selectedPortId: string | null;

  clock: number;
  lastTopic: FeedTopic;
  tile: ImageryTile;
  flow: FlowEstimate;
  history: number[];
  vessels: Record<string, Vessel>;
  vesselOrder: string[];
  outlook: CpiRecomputed;

  collector: CollectorState;
  ais: AisState;
}

export interface TidemarkActions {
  hydrate(snapshot: Snapshot): void;
  apply(event: FeedEvent): void;
  setGeography(id: string): void;
  setScenario(id: string): void;
  setOutlook(outlook: CpiRecomputed): void;
  setView(view: ViewId): void;
  toggleHud(): void;
  togglePaused(): void;
  selectShip(ref: ShipRef | null): void;
  hoverShip(ref: ShipRef | null): void;
  selectPort(id: string | null): void;
  setCollector(collector: CollectorState): void;
  aisSnapshot(vessels: AisVessel[]): void;
  aisUpsert(vessel: AisVessel): void;
  aisConnection(open: boolean): void;
}

export type TidemarkStore = TidemarkState & TidemarkActions;

export const sameShip = (a: ShipRef | null, b: ShipRef | null) => !!a && !!b && a.source === b.source && a.mmsi === b.mmsi;

/** Gate a vessel crosses on its way into the corridor. */
const entryGate = (d: Direction) => (d === "outbound" ? "a" : "b");

function fromSnapshot(geographies: readonly Geography[], s: Snapshot) {
  return {
    geographyId: findBySlug(geographies, s.location)?.id ?? geographies[0].id,
    scenarioId: s.scenario,
    clock: s.ts,
    tile: s.tile,
    flow: s.flow,
    history: s.history,
    outlook: s.outlook,
    vessels: Object.fromEntries(s.vessels.map((v) => [v.mmsi, v])),
    vesselOrder: s.vessels.map((v) => v.mmsi),
  };
}

export function createTidemarkStore(geographies: readonly Geography[], initial: Snapshot) {
  return createStore<TidemarkStore>()((set, get) => {
    /** Events for another geography are stale (in flight during a switch). */
    const isCurrent = (slug: string) => findGeography(get().geographies, get().geographyId).slug === slug;

    return {
      geographies,
      ...fromSnapshot(geographies, initial),
      view: "flow",
      hudVisible: true,
      paused: false,
      selected: null,
      hovered: null,
      selectedPortId: null,
      lastTopic: "flow.estimate.updated",
      collector: { reachable: null, status: null, metrics: null },
      ais: { connected: null, vessels: {} },

      hydrate: (snapshot) => set(fromSnapshot(get().geographies, snapshot)),

      apply: (e) => {
        const s = get();
        if (s.paused) return;
        const ts = "ts" in e.data ? e.data.ts : s.clock;
        const base = { lastTopic: e.topic, clock: Math.max(s.clock, ts) };

        switch (e.topic) {
          case "ais.position.v2": {
            const v = s.vessels[e.data.mmsi];
            if (!v) return set(base);
            return set({ ...base, vessels: { ...s.vessels, [v.mmsi]: { ...v, position: e.data } } });
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

      setGeography: (id) =>
        set((s) => ({
          geographyId: findGeography(s.geographies, id).id,
          selected: null,
          hovered: null,
          selectedPortId: null,
        })),
      setScenario: (id) => set({ scenarioId: id }),
      setOutlook: (outlook) => {
        if (outlook.scenario === get().scenarioId && isCurrent(outlook.location)) set({ outlook });
      },
      setView: (view) => set({ view }),
      toggleHud: () => set((s) => ({ hudVisible: !s.hudVisible })),
      togglePaused: () => set((s) => ({ paused: !s.paused })),
      selectShip: (ref) =>
        set((s) => ({
          selected: ref && !sameShip(s.selected, ref) ? ref : null,
          view: ref ? "vessels" : s.view,
        })),
      hoverShip: (ref) => set({ hovered: ref }),
      selectPort: (id) =>
        set((s) => ({
          selectedPortId: id && s.selectedPortId !== id ? id : null,
          view: id ? "ports" : s.view,
        })),
      setCollector: (collector) => set({ collector }),
      aisSnapshot: (vessels) =>
        set((s) => ({ ais: { ...s.ais, vessels: Object.fromEntries(vessels.map((v) => [v.mmsi, v])) } })),
      aisUpsert: (vessel) =>
        set((s) => (s.paused ? s : { ais: { ...s.ais, vessels: { ...s.ais.vessels, [vessel.mmsi]: vessel } } })),
      aisConnection: (open) => set((s) => ({ ais: { ...s.ais, connected: open } })),
    };
  });
}

export type TidemarkStoreApi = ReturnType<typeof createTidemarkStore>;

/** Current geography, from the store. */
export const selectGeography = (s: TidemarkState) => findGeography(s.geographies, s.geographyId);

/** Live AIS vessels inside the current geography's port geofences. */
export function aisInGeography(s: TidemarkState): AisVessel[] {
  const ids = new Set(selectGeography(s).ports.map((p) => p.id));
  return Object.values(s.ais.vessels).filter((v) => v.ports.some((p) => ids.has(p)));
}
