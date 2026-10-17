import { DEFAULT_MODEL_PARAMS, type ModelParams } from "@/config/model";
import { DEFAULT_SCENARIO_ID, getScenario } from "@/config/scenarios";
import { findGeography, type Geography } from "@/lib/geographies";
import { headingAlong, pointAlong } from "@/lib/geo";
import { computeOutlook } from "@/lib/model";
import type {
  AisPosition,
  CpiRecomputed,
  Direction,
  FeedClient,
  FeedEvent,
  FlowEstimate,
  ImageryTile,
  Snapshot,
  Vessel,
  VesselClass,
} from "./types";

/**
 * In-process stand-in for the Tidemark backend. Matches the prototype cadence
 * (one tick per ~1.5s) and is deterministic until the first tick, so a snapshot
 * rendered on the server hydrates cleanly on the client.
 */

const TICK_MS = 1500;
const HISTORY_LEN = 60;
/** Lane progress at which a vessel crosses the entry / exit gate. */
const GATE_T = { entry: 0.35, exit: 0.65 } as const;
/** Flow eases toward the scenario target by this share per event. */
const EASE = 0.12;

const NAMES = ["Coral Meridian", "Aster Voyager", "Kestrel Bay", "Northern Halcyon", "Sable Crest", "Orion Tide", "Marlin Grace", "Silver Lark", "Azure Dawn", "Jade Horizon"];
const CLASSES: VesselClass[] = ["VLCC", "Suezmax", "VLCC", "Aframax", "VLCC", "Suezmax", "VLCC", "Aframax", "Suezmax", "VLCC"];
const CARGO_MB: Record<VesselClass, number> = { VLCC: 2.0, Suezmax: 1.0, Aframax: 0.7 };
const DARK = new Set([4, 7]);
const TILE_TIMES: Record<string, { hm: string; cloud: number }> = {
  hormuz: { hm: "06:41", cloud: 3 },
  malacca: { hm: "03:22", cloud: 11 },
  "bab-el-mandeb": { hm: "07:58", cloud: 1 },
  suez: { hm: "08:35", cloud: 0 },
};

interface SimVessel {
  index: number;
  mmsi: string;
  direction: Direction;
  t: number;
  speed: number;
  kn: number;
}

function initialVessels(): SimVessel[] {
  return NAMES.map((_, i) => ({
    index: i,
    mmsi: String(538009100 + i),
    direction: i % 2 === 0 ? "outbound" : "inbound",
    t: (i * 0.163) % 1,
    speed: 0.006 + (i % 3) * 0.0007,
    kn: Number((12.2 + (i % 4) * 0.4).toFixed(1)),
  }));
}

function initialHistory(r0: number): number[] {
  return Array.from({ length: HISTORY_LEN }, (_, i) => r0 + 0.008 * Math.sin(i / 5) + 0.004 * Math.sin(i * 7.3));
}

const inCorridor = (t: number) => t > GATE_T.entry && t < GATE_T.exit;

/** True if progress moved across `th` between `prev` and `next`, allowing for a lap wrap. */
function crossed(prev: number, next: number, th: number): boolean {
  return next >= prev ? prev < th && next >= th : prev < th || next >= th;
}

export interface MockFeedOptions {
  /** Geographies from GET /api/geographies; the first is the default. */
  geographies: readonly Geography[];
  params?: ModelParams;
  /** Clock for the deterministic initial snapshot. */
  now?: number;
  random?: () => number;
}

export function createMockFeed(opts: MockFeedOptions): FeedClient {
  const { geographies } = opts;
  const params = opts.params ?? DEFAULT_MODEL_PARAMS;
  const random = opts.random ?? Math.random;

  const r0 = 0.93;
  const state = {
    geographyId: geographies[0].id,
    scenarioId: DEFAULT_SCENARIO_ID,
    // The prototype opens 30 events after the last shock, so the bypass is fully ramped.
    eventsSinceShock: 30,
    ratio: r0,
    history: initialHistory(r0),
    vessels: initialVessels(),
    tile: null as ImageryTile | null,
    now: opts.now ?? Date.now(),
  };

  const listeners = new Set<(e: FeedEvent) => void>();
  let timer: ReturnType<typeof setInterval> | null = null;
  const pending = new Set<ReturnType<typeof setTimeout>>();

  const loc = (): Geography => findGeography(geographies, state.geographyId);

  const tileFor = (l: Geography, capturedAt: string, cloud: number): ImageryTile => ({
    location: l.slug,
    provider: l.imageryProvider,
    tile_id: `${l.slug}-${capturedAt.replace(/[^0-9]/g, "").slice(0, 12)}`,
    captured_at: capturedAt,
    cloud_pct: cloud,
    gsd_m: 10,
  });

  const initialTile = (l: Geography): ImageryTile => {
    const t = TILE_TIMES[l.id] ?? { hm: "00:00", cloud: 0 };
    const day = new Date(state.now).toISOString().slice(0, 10);
    return tileFor(l, `${day}T${t.hm}:00Z`, t.cloud);
  };

  const position = (v: SimVessel, l: Geography): AisPosition => {
    const lane = l.lanes[v.direction];
    const [lon, lat] = pointAlong(lane, v.t);
    return { mmsi: v.mmsi, lat, lon, sog_kn: v.kn, heading: Math.round(headingAlong(lane, v.t)), ts: state.now };
  };

  const toVessel = (v: SimVessel, l: Geography): Vessel => {
    const vesselClass = CLASSES[v.index];
    const laden = v.direction === "outbound";
    const dests = l.destinations[v.direction];
    return {
      mmsi: v.mmsi,
      name: `MT ${NAMES[v.index]}`,
      vesselClass,
      direction: v.direction,
      laden,
      cargo: laden ? `${CARGO_MB[vesselClass].toFixed(1)} mb crude` : "Ballast",
      cargoMb: laden ? CARGO_MB[vesselClass] : 0,
      destination: dests[v.index % dests.length],
      ais: DARK.has(v.index) ? "dark" : "live",
      inCorridor: inCorridor(v.t),
      position: position(v, l),
    };
  };

  const flowEstimate = (): FlowEstimate => {
    const l = loc();
    return {
      location: l.slug,
      flow_mbd: l.baseMbd * state.ratio,
      ratio: state.ratio,
      ci_mbd: getScenario(state.scenarioId).sigmaMbd * 0.3,
      window_h: 6,
      ts: state.now,
    };
  };

  const outlook = (): CpiRecomputed => {
    const l = loc();
    const chain = computeOutlook(
      { geography: l, scenario: getScenario(state.scenarioId), ratio: state.ratio, eventsSinceShock: state.eventsSinceShock },
      params,
    );
    return {
      location: l.slug,
      scenario: state.scenarioId,
      horizon: "1m",
      energy_pct: chain.energyPct,
      headline_pp: chain.headlinePp,
      core_pp: chain.corePp,
      chain,
      ts: state.now,
    };
  };

  const emit = (e: FeedEvent) => listeners.forEach((fn) => fn(e));
  const emitLater = (delay: number, events: () => FeedEvent[]) => {
    const id = setTimeout(() => {
      pending.delete(id);
      if (listeners.size) events().forEach(emit);
    }, delay);
    pending.add(id);
  };

  const tick = () => {
    const l = loc();
    const sc = getScenario(state.scenarioId);
    state.now = Date.now();
    state.eventsSinceShock += 1;
    state.ratio += (1 - sc.depth - state.ratio) * EASE + (random() - 0.5) * 0.008;
    state.history = [...state.history.slice(1), state.ratio];

    const crossings: FeedEvent[] = [];
    for (const v of state.vessels) {
      const prev = v.t;
      v.t += v.speed * (0.4 + 0.6 * Math.min(1, state.ratio));
      if (v.t > 1) v.t -= 1;
      for (const [gate, th] of [["entry", GATE_T.entry], ["exit", GATE_T.exit]] as const) {
        if (!crossed(prev, v.t, th)) continue;
        const info = toVessel(v, l);
        // Outbound traffic meets gate "a" first; inbound meets "b" first.
        const first = v.direction === "outbound" ? "a" : "b";
        const second = first === "a" ? "b" : "a";
        crossings.push({
          topic: "vessel.gate.crossed",
          data: {
            mmsi: v.mmsi,
            location: l.slug,
            gate: gate === "entry" ? first : second,
            direction: v.direction,
            laden: info.laden,
            est_cargo_mb: info.cargoMb,
            ts: state.now,
          },
        });
      }
    }

    // Stagger topics inside the tick window, like a real multiplexed stream.
    const positions = state.vessels.map((v) => ({ topic: "ais.position.v2" as const, data: position(v, l) }));
    emitLater(random() * 900, () => [...positions, ...crossings]);
    const flow = flowEstimate();
    const cpi = outlook();
    emitLater(random() * 900, () => [
      { topic: "flow.estimate.updated", data: flow },
      { topic: "cpi.energy.recomputed", data: cpi },
    ]);
    if (random() < 0.06) {
      const cloud = Math.round(random() * 12);
      state.tile = tileFor(l, new Date(state.now).toISOString().slice(0, 17) + "00Z", cloud);
      const tile = state.tile;
      emitLater(1000 + random() * 400, () => [{ topic: "imagery.tile.ingested", data: tile }]);
    }
  };

  const start = () => {
    if (!timer) timer = setInterval(tick, TICK_MS);
  };
  const stop = () => {
    if (timer) clearInterval(timer);
    timer = null;
    pending.forEach(clearTimeout);
    pending.clear();
  };

  return {
    async getSnapshot(geographyId, scenarioId) {
      if (geographyId !== state.geographyId || scenarioId !== state.scenarioId) {
        // Drop in-flight events for the previous location.
        pending.forEach(clearTimeout);
        pending.clear();
        state.geographyId = findGeography(geographies, geographyId).id;
        state.scenarioId = getScenario(scenarioId).id;
        state.eventsSinceShock = 0;
        state.tile = null;
      }
      const l = loc();
      state.tile ??= initialTile(l);
      return {
        location: l.slug,
        scenario: state.scenarioId,
        ts: state.now,
        tile: state.tile,
        flow: flowEstimate(),
        history: [...state.history],
        vessels: state.vessels.map((v) => toVessel(v, l)),
        outlook: outlook(),
      };
    },

    async runScenario(geographyId, scenarioId) {
      state.geographyId = findGeography(geographies, geographyId).id;
      state.scenarioId = getScenario(scenarioId).id;
      state.eventsSinceShock = 0;
      return outlook();
    },

    subscribe(onEvent) {
      listeners.add(onEvent);
      start();
      return () => {
        listeners.delete(onEvent);
        if (!listeners.size) stop();
      };
    },
  };
}

/** Server-side initial snapshot for SSR; identical to a fresh client mock's first read. */
export function getMockSnapshot(geographies: readonly Geography[]): Promise<Snapshot> {
  return createMockFeed({ geographies }).getSnapshot(geographies[0].id, DEFAULT_SCENARIO_ID);
}
