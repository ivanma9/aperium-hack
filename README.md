# Aperium

Energy-flow intelligence around the Strait of Hormuz. Two parts:

| Part | Path | Stack | What it does |
| --- | --- | --- | --- |
| **Postgres** | `compose.yaml` | Postgres 17 (Docker) | Stores the monitored geographies, port geofences and AIS positions. A trigger raises a NOTIFY event on every new position. |
| **AIS collector** | `aperium/` | Python · FastAPI · psycopg | Collects live AISstream positions in the port geofences stored in Postgres. Class A and B reports, durable position history, latest position per MMSI, stale filtering, automatic reconnects. Serves geographies and ports over REST, and new positions as Server-Sent Events. |
| **Tidemark HUD** | `web/` | Next.js 16 · Bun · MapLibre · Zustand | Live dashboard on an OpenFreeMap map: chokepoint oil flow → one-month US energy CPI outlook, plus port activity and live AIS ships. See [`web/README.md`](web/README.md). |

## Run everything

```sh
./dev.sh   # Postgres (Docker) on :5434, collector on :8000, HUD on :3000; Ctrl-C stops collector + HUD
```

Requires Docker (Desktop running), Python 3.9+ and Bun ≥ 1.4. `dev.sh` starts Postgres with
`docker compose up -d --wait db` and leaves it running between sessions; stop it with
`docker compose stop db`. On first run it also creates `.env` from `.env.example`, installs the
collector (with uv if available, otherwise into `.venv`) and runs `bun install` in `web/`.
Set `AISSTREAM_API_KEY` in `.env` for live positions. Change ports with `BACKEND_PORT` /
`FRONTEND_PORT`, and the host's Postgres port with `APERIUM_DB_PORT` (default 5434, chosen to avoid
the 5432/5433 a local or other project's Postgres often uses; update `DATABASE_URL` to match).

### What is live and what is simulated

| In the HUD | Source |
| --- | --- |
| Geography switcher, map framing, lanes, gates, port geofences | **Postgres** `geographies` + `ports` tables, via `GET /api/geographies` (read when the page loads) |
| **Green ships** (live AIS), hover/tap details | **Live**: Postgres NOTIFY → `GET /api/stream` (SSE), pushed as each position is saved |
| **Ports** tab: active / slow / anchored / stale per port, collector status | **Live**: `/api/status`, `/api/metrics`, polled every 10 s |
| Flow, Supply and CPI tabs, outcome card, **orange/grey ships** (corridor traffic) | **Simulated** by an in-browser mock of the planned flow stream (`web/src/lib/feed/mock.ts`) |
| Basemap | [OpenFreeMap](https://openfreemap.org) vector tiles (OpenStreetMap data), no API key |

The HUD calls the collector same-origin: REST through a rewrite (`/aperium/*` →
`$APERIUM_API_URL/api/*`, in `web/next.config.ts`), and the event stream through a small route
handler (`web/src/app/aperium/stream/route.ts`), because the rewrite proxy truncated long-lived
SSE responses under Bun. The collector keeps its loopback binding and needs no CORS.
The HUD needs the collector to load: without `/api/geographies` there is nothing to show, so it
displays an "offline" page with instructions instead.

Port geofences currently exist only for Hormuz. The other geographies (Malacca, Bab el-Mandeb,
Suez) have no AIS coverage until you add `ports` rows for them.

## Run the collector only

Python 3.11+ recommended (3.9+ supported). From this directory:

```sh
docker compose up -d --wait db   # Postgres on 127.0.0.1:5434 (also creates aperium_test)
uv sync
cp .env.example .env
# Edit .env and set AISSTREAM_API_KEY to your AISstream key.
uv run uvicorn aperium.app:app --host 127.0.0.1 --port 8000
```

On startup the collector creates its tables if needed and inserts the initial geographies and ports
from `aperium/seed.py` (insert-if-missing, so edits made in the database are kept).

Credentials live only in `.env` (gitignored). Set `POSTGRES_PASSWORD` to a random value before the
first `docker compose up` (`./dev.sh` generates one with `openssl rand -hex 24`). compose.yaml
refuses to start without it. The collector connects to `127.0.0.1:${APERIUM_DB_PORT:-5434}` as
`POSTGRES_USER` (default `aperium`) with that password. Set `DATABASE_URL` instead to point at
another Postgres. No password has a default anywhere in the repo.

To rotate the password, change `POSTGRES_PASSWORD` in `.env` and rerun `./dev.sh`. It recreates the
container and re-applies the password to the database role on every start, because Postgres only
reads `POSTGRES_PASSWORD` when the volume is first created.

If uv is unavailable, use a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Then create `.env` as above and run
`.venv/bin/python -m uvicorn aperium.app:app --host 127.0.0.1 --port 8000`.

Open http://127.0.0.1:8000/docs to inspect and try the API.
Run one worker: each worker would open a separate upstream connection.
The API is local and unauthenticated; keep the default loopback binding.
Keys are loaded only on the server; `.env`, the virtual environment, and data are ignored by Git.
Without a key, the API still starts and reports `missing_api_key`.
Restart after changing `.env`.

## Endpoints

- `GET /api/status`: connection status, data freshness, counters, last-message times, all geofences, and whether the event stream is listening.
- `GET /api/geographies`: monitored geographies (chokepoints) with framing bbox, lanes, gates, model parameters, and their `ports`.
- `GET /api/ports`: port IDs, approximate bounding boxes, and `geography_id`. Optional `?geography=hormuz` filter.
- `GET /api/vessels`: fresh observed vessels inside the box.
- `GET /api/vessels?port=fujairah`: filter by port (any `ports.id`; unknown IDs return 422).
- `GET /api/vessels?include_stale=true`: include old positions, explicitly marked stale.
- `GET /api/metrics`: combined and per-port fresh unique vessels, slow vessels (<1 knot), reported anchored vessels. Optional `?port=fujairah` filter.
- `GET /api/vessels/{mmsi}/history?limit=100`: stored observations, newest first (max 10,000).
- `GET /api/stream`: Server-Sent Events. `event: snapshot` on connect (fresh vessels inside the geofences), then `event: vessel` for each new position, same shape as `/api/vessels` items. A `: keep-alive` comment every 15 s when idle. Fed by a Postgres trigger on `latest` (`pg_notify('vessel_positions', …)`) that the collector LISTENs to.

All timestamps are Unix seconds in UTC. `time_source` indicates whether the provider
timestamp or local receipt time was used. Unknown speed/course sentinel values become null.

## Area and interpretation

Approximate discovery boxes, in `[latitude, longitude]` order:

| Port ID | Southwest | Northeast |
| --- | --- | --- |
| fujairah | [25.05, 56.32] | [25.28, 56.65] |
| shahid_rajaee | [26.95, 55.95] | [27.18, 56.20] |
| khor_fakkan | [25.30, 56.32] | [25.45, 56.55] |
| jebel_ali | [24.90, 54.95] | [25.12, 55.15] |

These live in the Postgres `ports` table (`south`, `west`, `north`, `east`, `geography_id`).
Edit the rows, then restart the collector: it reads the geofences once at startup and subscribes
to AISstream with those boxes. The HUD picks them up on its next page load. Monitored geographies
live in the `geographies` table the same way. `aperium/seed.py` only provides the initial rows for a
fresh database. If a new port falls outside its geography's `bbox`, widen the bbox so the map frames it.
Each vessel includes matching `ports`. Overall counts count each MMSI only once;
if boxes are changed to overlap, per-port totals may include the same vessel.

This box includes port approaches and offshore waters; it is **not** an official
anchorage polygon. Slow or anchored vessels may be bunkering, servicing, or waiting
for other reasons. Metrics describe observed activity, not confirmed congestion.

The initial list starts empty and builds from incoming reports. No historical
backfill is available. Missing reception is not evidence that a vessel departed;
positions older than `STALE_SECONDS` (default 900) are excluded from active counts.
Check connection status and last-position time when interpreting empty results.
Geofence exits cannot reliably be detected from this geographically filtered stream.

Position history lives in the Postgres `positions` table (Docker volume `pgdata`) and survives
restarts. There is currently no automatic retention limit: monitor disk use during extended
collection. The collector writes each position as one small transaction; this is intended for this
small regional subscription, not a worldwide high-throughput feed.

## Tests

```sh
# Collector: needs Postgres (docker compose up -d db); uses the aperium_test database
uv run pytest
# Normalization and geofence-matching tests need only the standard library:
python3 -m unittest discover -s tests -p test_tracking.py

# HUD (model, store, mock feed)
cd web && bun run test
```

Tests use synthetic AIS messages and a local WebSocket provider; no API key needed. The storage,
API, NOTIFY and SSE tests run against `TEST_DATABASE_URL` (default
the `aperium_test` database with the `.env` credentials), which they reset, and are skipped if
it's unreachable or no password is configured.
Provider documentation: https://aisstream.io/documentation/

## Compare with other observations

1. Check `/api/status`: `subscribed` confirms acceptance, not vessel coverage.
   `positions_received` and `last_position_at` show whether the current collector
   has received usable positions. `data_status` reports silence separately from connection state.
2. Check `/api/metrics` → `by_port`. Each port has its own freshness status.
   Existing stored observations can remain visible even before this session receives new data.
3. Compare individual MMSIs from `/api/vessels` with VesselFinder or MarineTraffic,
   matching the observation time, coordinates, and speed. Differences in receiver
   coverage and update delay are expected; neither is absolute ground truth.
4. For Fujairah, also compare names/IMO numbers against the port authority's shipping
   list. This validates port activity rather than exact coordinates. The current
   position feed includes names when available and MMSI, but not IMO enrichment.

Sources for manual comparison:

- https://www.vesselfinder.com/ports/AEFJR001
- https://fujairahport.ae/daily_shipping_list_print.cfm
- https://fujairahport.ae/offshore/s_list1.cfm

Use the same geographic boundaries and observation period when comparing counts.
Expected arrivals are not ships currently present. A port's berth list also differs
from this larger discovery box, which includes nearby waters.
If all four areas stay silent, check provider coverage and service status. A larger
subscription does not create coverage where upstream receivers are missing.
