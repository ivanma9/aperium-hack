# Tidemark HUD — web

Next.js 16 (App Router) frontend for Aperium. It's a live HUD on a MapLibre map that turns chokepoint oil transit into a one-month US energy CPI outlook, alongside port activity and live AIS ships from the collector in `../aperium/`. Start with the [root README](../README.md), which says what's live and what's simulated. The design spec is `HANDOFF.md`; it's kept locally and is gitignored.

Runs on **Bun** (`bun --bun next …`). Use Bun ≥ 1.4: `next build` crashes on Bun 1.3.x with a Bun module-loader bug.

```bash
../dev.sh          # recommended: Postgres + collector + HUD together
bun install
bun run dev        # HUD only, http://localhost:3000 (needs the collector for /api/geographies)
bun run build
bun run test       # model, store, mock feed
bun run typecheck
bun run lint
```

`APERIUM_API_URL` (default `http://127.0.0.1:8000`) points the HUD at the collector, both for the server-side geographies read and for the browser's `/aperium/*` proxy.

`predev` / `prebuild` run `scripts/copy-maplibre-worker.mjs`, which copies MapLibre's web-worker files into `public/maplibre/` (gitignored). Turbopack doesn't emit the worker's sibling module, so MapLibre v6 documents serving both from `public/`. If you start Next some other way (e.g. `bunx next dev`), run `bun scripts/copy-maplibre-worker.mjs` first or the map won't load tiles.

## Data sources

| Source | Feeds | Code |
|---|---|---|
| **Geographies** (Postgres `geographies` + `ports`, `GET /api/geographies`) | Geography switcher, map framing, lanes, gates, port geofences, model parameters (base flow, bypass) | `fetchGeographies` in `src/lib/geographies.ts`, called by `src/app/page.tsx` at request time |
| **Live AIS** (Postgres NOTIFY → `GET /api/stream`, SSE) | Green ships on the map; hover/tap details; live count in the Vessels tab | `subscribeVessels` in `src/lib/aperium/client.ts`, `src/app/aperium/stream/route.ts` (pass-through) |
| **Collector status** (REST, polled every 10 s) | **Ports** tab: per-port active / <1 kn / anchored / stale counts, collector state; counts on the map's geofence labels | `src/lib/aperium/client.ts`, `useCollectorStatus` in `src/components/TidemarkProvider.tsx` |
| **Mock feed** (simulated stream, HANDOFF §6 topics) | Flow, Supply, CPI, outcome card, corridor ships (orange laden, grey ballast, red ring = AIS-dark) | `src/lib/feed/mock.ts` implementing `FeedClient` in `src/lib/feed/types.ts` |
| **Basemap** | OpenFreeMap `dark` style (OpenStreetMap data), retinted to the HUD palette | `src/components/MapStage.tsx` |

Nothing about geographies or ports is hardcoded in the frontend. Add or edit rows in Postgres and reload the page. If the collector is unreachable, the page shows an "offline" message instead of the HUD.

To make the simulated part live, implement `FeedClient` over the real flow/CPI stream and swap it in for `createMockFeed` in `TidemarkProvider.tsx` and `page.tsx`.

## Map and ships

- **MapLibre GL JS 6** with OpenFreeMap vector tiles: no API key. The required credit (OpenFreeMap © OpenMapTiles © OpenStreetMap) is always visible. It sits in the toggle row on desktop and on the bottom edge on narrow screens.
- **Framing:** each geography's `bbox` is fitted into the part of the stage not covered by the glass overlays. It measures the overlays and tries reserving the outcome card's width or its height, then keeps whichever zooms in further. It re-frames on geography change and on Hide/Show HUD. Panning and zooming are free.
- **Lanes, gates and geofences** are GeoJSON layers. Lanes animate their dashes (off under `prefers-reduced-motion`), and the laden lane's width tracks observed flow. Clicking a geofence opens it in the Ports tab.
- **Ships** are HTML markers (real `<button>`s: focusable and labelled):
  - **Hover** (mouse) or **keyboard focus** previews the ship in the info panel, in any view.
  - **Click / tap** pins it in the Vessels tab. Touch doesn't trigger a hover, so a tap goes straight to pinning.
  - Live AIS details: MMSI, speed, course, navigational status, port, time since the last position, and a "Live AIS" tag. Simulated ships are tagged "Simulated corridor traffic".
- Lanes and gates are hand-placed approximations of the main tanker routes (a few km), not official traffic separation schemes.

## Layout

| Path | What |
|---|---|
| `src/lib/geographies.ts` | `Geography` / `PortGeofence` types, API row mapping, `fetchGeographies` |
| `src/lib/aperium/client.ts` | Typed collector client: status, metrics, SSE vessel stream, AIS nav-status labels |
| `src/app/aperium/stream/route.ts` | SSE pass-through to the collector (the rewrite proxy truncates long-lived streams) |
| `src/config/scenarios.ts` | Geopolitical scenarios (depth, premium, ramp/hold/recovery, σ) |
| `src/config/model.ts` | **Placeholder** coefficients: Brent/gas refs, $/mb/d, CPI weights, pass-through |
| `src/lib/model.ts` | Pure model (HANDOFF §5): `computeOutlook`, `forecastSupply`, `shockAt` |
| `src/lib/feed/` | Planned flow stream's wire types + the mock |
| `src/store/tidemark.ts` | Zustand store: geographies, feed events, live AIS, collector state, ship hover/selection |
| `src/components/MapStage.tsx` | MapLibre map, overlay layers, ship markers |
| `src/components/` | Glass overlays and view panels |
| `src/test/fixtures.ts` | Geography fixtures shaped like `/api/geographies` rows (tests only) |

## Not done yet

- Satellite imagery under the vector map, once a licensed source is chosen.
- The model service, the pipeline, and the planned flow/CPI REST, WebSocket and MCP layers (HANDOFF §7 steps 3–5).
- Ships don't animate between position updates. Simulated ones step every ~1.5 s, live ones on each AIS report.
