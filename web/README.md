# Tidemark — web

Next.js 16 (App Router) frontend for the Tidemark HUD described in [`../HANDOFF.md`](../HANDOFF.md). It currently runs against an in-process **mock feed**, so it works offline.

Runs on **Bun** (`bun --bun next …`). Use Bun ≥ 1.4: `next build` crashes on Bun 1.3.x with a Bun module-loader bug.

```bash
bun install
bun run dev        # http://localhost:3000
bun run build
bun run test       # model + store unit tests (vitest)
bun run typecheck
bun run lint
```

To run it with the backend, use `../dev.sh` from the repo root.

## Layout

| Path | What |
|---|---|
| `src/config/locations.ts` | Monitored locations: model params, map geometry (`0 −15 800 450` viewBox), bbox ↔ lon/lat |
| `src/config/scenarios.ts` | Geopolitical scenarios (depth, premium, ramp/hold/recovery, σ) |
| `src/config/model.ts` | **Placeholder** coefficients: Brent/gas refs, $/mb/d, CPI weights, pass-through |
| `src/lib/model.ts` | Pure model (HANDOFF §5): `computeOutlook`, `forecastSupply`, `shockAt` |
| `src/lib/feed/types.ts` | Wire types for the §6 topics + the `FeedClient` interface |
| `src/lib/feed/mock.ts` | Mock backend: ~1.5s ticks, staggered topics, gate crossings, scenario/location state |
| `src/store/tidemark.ts` | Zustand store that reduces feed events into UI state |
| `src/components/` | Stage (stylized map + vessel markers), glass overlays, view panels |

## Data flow

- `page.tsx` reads an initial snapshot on the server and streams the dashboard inside `<Suspense>` (the stage shell is prerendered).
- `TidemarkProvider` subscribes to the feed. **Pause** unsubscribes, and the store drops events while paused.
- Switching location calls `getSnapshot` (→ REST reads). Changing scenario calls `runScenario` (→ `POST /v1/scenarios/run`). The store ignores stale events from a previous location or scenario.

To go live, implement `FeedClient` over the WebSocket and REST endpoints and swap it in for `createMockFeed` in `TidemarkProvider.tsx` and `page.tsx`.

## Not done yet

- Real imagery: the map is still the stylized SVG. The provider choice (MapLibre + Sentinel-2 vs commercial) is open.
- The mobile crop is one offset for every location (`--crop-x` on `.mapbox`, default −56%).
- The model service, pipeline and API/MCP layers (HANDOFF §7 steps 3–5) aren't built. `src/lib/model.ts` is ready to be shared with them.
