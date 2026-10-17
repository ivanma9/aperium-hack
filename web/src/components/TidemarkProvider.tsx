"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useStore } from "zustand";
import { aperium, subscribeVessels } from "@/lib/aperium/client";
import { createMockFeed } from "@/lib/feed/mock";
import type { FeedClient, Snapshot } from "@/lib/feed/types";
import type { Geography } from "@/lib/geographies";
import { createTidemarkStore, type TidemarkStore, type TidemarkStoreApi } from "@/store/tidemark";

interface TidemarkContextValue {
  store: TidemarkStoreApi;
  feed: FeedClient;
}

const TidemarkContext = createContext<TidemarkContextValue | null>(null);

export function TidemarkProvider({
  geographies,
  initial,
  children,
}: {
  geographies: Geography[];
  initial: Snapshot;
  children: ReactNode;
}) {
  // Created once per mount. Swap `createMockFeed` for the real flow/CPI stream when it exists.
  const [value] = useState<TidemarkContextValue>(() => ({
    store: createTidemarkStore(geographies, initial),
    feed: createMockFeed({ geographies, now: initial.ts }),
  }));

  const paused = useStore(value.store, (s) => s.paused);

  useEffect(() => {
    if (paused) return;
    return value.feed.subscribe((e) => value.store.getState().apply(e));
  }, [paused, value]);

  useCollectorStatus(value.store, paused);
  useAisStream(value.store, paused);

  return <TidemarkContext.Provider value={value}>{children}</TidemarkContext.Provider>;
}

/** How often to poll collector status + per-port metrics. Positions arrive by SSE instead. */
const COLLECTOR_POLL_MS = 10_000;

/** Poll the collector's status and metrics. Offline is a normal state. */
function useCollectorStatus(store: TidemarkStoreApi, paused: boolean) {
  useEffect(() => {
    if (paused) return;
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const [status, metrics] = await Promise.all([aperium.status(ctrl.signal), aperium.metrics(ctrl.signal)]);
        store.getState().setCollector({ reachable: true, status, metrics });
      } catch {
        if (ctrl.signal.aborted) return;
        store.getState().setCollector({ reachable: false, status: null, metrics: null });
      }
      timer = setTimeout(poll, COLLECTOR_POLL_MS);
    };
    poll();
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [store, paused]);
}

/** Live AIS positions: snapshot + per-vessel events over SSE, fed by Postgres NOTIFY. */
function useAisStream(store: TidemarkStoreApi, paused: boolean) {
  useEffect(() => {
    if (paused) return;
    return subscribeVessels({
      onSnapshot: (vessels) => store.getState().aisSnapshot(vessels),
      onVessel: (vessel) => store.getState().aisUpsert(vessel),
      onConnection: (open) => store.getState().aisConnection(open),
    });
  }, [store, paused]);
}

function useTidemarkContext() {
  const ctx = useContext(TidemarkContext);
  if (!ctx) throw new Error("useTidemark must be used inside <TidemarkProvider>");
  return ctx;
}

export function useTidemark<T>(selector: (s: TidemarkStore) => T): T {
  return useStore(useTidemarkContext().store, selector);
}

/** UI intents that also talk to the feed (REST calls in the real client). */
export function useTidemarkActions() {
  const { store, feed } = useTidemarkContext();
  return useMemo(
    () => ({
      async switchGeography(id: string) {
        const s = store.getState();
        if (id === s.geographyId) return;
        s.setGeography(id);
        const snapshot = await feed.getSnapshot(id, s.scenarioId);
        // Ignore if the user moved on before the response arrived.
        if (store.getState().geographyId === id) store.getState().hydrate(snapshot);
      },
      async runScenario(id: string) {
        const s = store.getState();
        s.setScenario(id);
        store.getState().setOutlook(await feed.runScenario(s.geographyId, id));
      },
    }),
    [store, feed],
  );
}
