"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useStore } from "zustand";
import { createMockFeed } from "@/lib/feed/mock";
import type { FeedClient, Snapshot } from "@/lib/feed/types";
import { createTidemarkStore, type TidemarkStore, type TidemarkStoreApi } from "@/store/tidemark";

interface TidemarkContextValue {
  store: TidemarkStoreApi;
  feed: FeedClient;
}

const TidemarkContext = createContext<TidemarkContextValue | null>(null);

export function TidemarkProvider({ initial, children }: { initial: Snapshot; children: ReactNode }) {
  // Created once per mount. Swap `createMockFeed` for the WebSocket/REST client when the backend lands.
  const [value] = useState<TidemarkContextValue>(() => ({
    store: createTidemarkStore(initial),
    feed: createMockFeed({ now: initial.ts }),
  }));

  const paused = useStore(value.store, (s) => s.paused);

  useEffect(() => {
    if (paused) return;
    return value.feed.subscribe((e) => value.store.getState().apply(e));
  }, [paused, value]);

  return <TidemarkContext.Provider value={value}>{children}</TidemarkContext.Provider>;
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
      async switchLocation(id: string) {
        const s = store.getState();
        if (id === s.locationId) return;
        s.setLocation(id);
        const snapshot = await feed.getSnapshot(id, s.scenarioId);
        // Ignore if the user moved on before the response arrived.
        if (store.getState().locationId === id) store.getState().hydrate(snapshot);
      },
      async runScenario(id: string) {
        const s = store.getState();
        s.setScenario(id);
        store.getState().setOutlook(await feed.runScenario(s.locationId, id));
      },
    }),
    [store, feed],
  );
}
