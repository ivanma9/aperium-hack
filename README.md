<h1 align="center">Aperium</h1>

<p align="center">
  <strong>Energy-flow intelligence around the Strait of Hormuz.</strong><br>
  A live AIS collector, a tanker monitor with an uncalibrated CPI nowcast, and <strong>Tidemark</strong>, a HUD that turns chokepoint oil flow into a one-month US energy CPI outlook.
</p>

<p align="center">
  <a href="https://github.com/ivanma9/aperium-hack/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ivanma9/aperium-hack/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white">
  <img alt="React 19" src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black">
  <img alt="TypeScript 5" src="https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white">
  <img alt="Bun 1.4+" src="https://img.shields.io/badge/Bun-%E2%89%A51.4-000000?style=flat-square&logo=bun&logoColor=white">
  <img alt="MapLibre GL JS 6" src="https://img.shields.io/badge/MapLibre_GL-6-396CB2?style=flat-square&logo=maplibre&logoColor=white">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="PostgreSQL 17" src="https://img.shields.io/badge/PostgreSQL-17-4169E1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

<!-- Screenshot: save a 1440x900 capture of the HUD to docs/screenshot.png, then uncomment.
<p align="center">
  <img src="docs/screenshot.png" width="900" alt="Tidemark HUD on the OpenFreeMap map of the Strait of Hormuz: port geofences, shipping lanes, live AIS ships, the oil-flow panel and the US energy CPI outlook card."><br>
  <sub>Flow and CPI figures on the HUD come from the simulated feed (see <a href="#what-is-live-and-what-is-simulated">what is live</a>).</sub>
</p>
-->

**Contents:** [Overview](#overview) · [Run everything](#run-everything) · [Live vs simulated](#what-is-live-and-what-is-simulated) · [Collector only](#run-the-collector-only) · [Endpoints](#endpoints) · [MCP server](#mcp-server) · [Tests](#tests) · [Tanker monitor](#tanker-monitor-and-cpi-nowcast-backend)

## Overview

Three parts:

| Part | Path | Stack | What it does |
| --- | --- | --- | --- |
| **Postgres** | `compose.yaml` | Postgres 17 (Docker) | Stores the monitored geographies, port geofences and AIS positions. A trigger raises a NOTIFY event on every new position. |
| **AIS collector** | `aperium/` | Python · FastAPI · psycopg | Collects live AISstream positions in the port geofences stored in Postgres. Class A and B reports, durable position history, latest position per MMSI, stale filtering, automatic reconnects. Serves geographies and ports over REST, and new positions as Server-Sent Events. |
| **Tidemark HUD** | `web/` | Next.js 16 · Bun · MapLibre · Zustand | Live dashboard on an OpenFreeMap map: chokepoint oil flow → one-month US energy CPI outlook, plus port activity and live AIS ships. See [`web/README.md`](web/README.md). |

## Run everything

```sh
./dev.sh   # Postgres :5434 · collector + MCP :8000 · tanker monitor · HUD :3000
```

| Process | What it does |
| --- | --- |
| Postgres (Docker) | Geographies, ports, AIS positions; left running between sessions |
| Collector (`aperium.app`) | AISstream connection, REST + SSE API, MCP server at `/mcp`; records raw AIS to `data/raw_YYYYMMDD.jsonl` |
| Tanker monitor (`aperium.run`) | Tails that raw file and writes `outputs/latest/` every 10 s (regions, flow metrics, events), plus the CPI nowcast every 30 min. Skip it with `MONITOR=0 ./dev.sh` |
| HUD (`web/`) | Next.js dev server |

Ctrl-C stops everything except Postgres.

Requires Docker (Desktop running), Python 3.9+ and Bun ≥ 1.4. `dev.sh` starts Postgres with
`docker compose up -d --wait db` and leaves it running between sessions; stop it with
`docker compose stop db`. On first run it also creates `.env` from `.env.example`, installs the
collector (with uv if available, otherwise into `.venv`) and runs `bun install` in `web/`.
Set `AISSTREAM_API_KEY` in `.env` for live positions, and optionally `EIA_API_KEY` (free, eia.gov) so
the CPI nowcast includes EIA weekly retail gasoline; without it the nowcast still runs and its
`sources` list marks EIA as `missing_key`. Change ports with `BACKEND_PORT` /
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

## MCP server

The collector's and tanker monitor's data as MCP tools (`aperium/mcp_server.py`, MCP Python SDK 2,
Python 3.10+). Two transports, same tools:

| Transport | How | Notes |
| --- | --- | --- |
| **Streamable HTTP** | `http://127.0.0.1:8000/mcp` | Mounted on the collector, so `./dev.sh` serves it. Stateless, JSON responses. |
| **stdio** | `.venv/bin/python -m aperium.mcp_server` | For harnesses that launch a command. Needs the collector running. |

Every tool wraps one collector REST endpoint (`APERIUM_API_URL`, default `http://127.0.0.1:8000`), so
MCP clients get exactly what the HUD and REST clients get:

| Tool | Endpoint | Data |
| --- | --- | --- |
| `list_geographies` | `/api/geographies` | Monitored chokepoints and their port geofences (Postgres) |
| `get_collector_status` | `/api/status` | AISstream connection, counters, freshness |
| `list_vessels(port?, include_stale?)` | `/api/vessels` | Live AIS ships inside the geofences |
| `get_port_metrics(port?)` | `/api/metrics` | Active / slow / anchored / stale per port |
| `get_vessel_history(mmsi, limit?)` | `/api/vessels/{mmsi}/history` | Stored observations for one ship |
| `list_regions` | `/api/regions` | Tanker-monitor regions (tanker monitor) |
| `get_flow_estimate(region?)` | `/api/regions/{region}/metrics` | Tankers present, gate crossings, laden departures, est. barrels (tanker monitor) |
| `list_region_tankers(region?)` | `/api/regions/{region}/vessels` | Tracked tankers (tanker monitor) |
| `get_region_events(region?, since?, limit?)` | `/api/regions/{region}/events` | Tanker events, newest first (tanker monitor) |
| `get_energy_cpi_outlook` | `/api/cpi_nowcast` | Uncalibrated US energy-CPI nowcast (tanker monitor) |
| `run_scenario(disruption, days)` | `/api/cpi/scenario` | What-if Hormuz disruption on the cached CPI baseline |

Tools marked "tanker monitor" read the files `aperium.run` writes; `./dev.sh` starts it. Until its
first write (about 10 s), or with `MONITOR=0`, they return an error naming the command that produces
the data, rather than failing silently. Every tool returns a single JSON object (lists are wrapped
with a `count`), so empty results still read clearly. CPI figures are uncalibrated
(`calibrated: false`), and the server's instructions tell clients to say so.

**Connect a harness** (start `./dev.sh` first):

```sh
# Claude Code
claude mcp add --transport http aperium http://127.0.0.1:8000/mcp

# MCP Inspector (browser UI for trying tools): choose "Streamable HTTP", URL http://127.0.0.1:8000/mcp
npx @modelcontextprotocol/inspector
```

For clients configured with JSON (Claude Desktop, Cursor and similar), use stdio with absolute paths:

```json
{
  "mcpServers": {
    "aperium": {
      "command": "/absolute/path/to/aperium-hack/.venv/bin/python",
      "args": ["-m", "aperium.mcp_server"],
      "env": { "APERIUM_API_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

Clients that accept a URL (Cursor's `"url"` field, for example) can use `http://127.0.0.1:8000/mcp`
directly.

**Security:** like the rest of the API it's local and unauthenticated. The SDK's DNS-rebinding
protection only accepts `localhost`/`127.0.0.1` Host headers, so it can't be reached through another
hostname. Don't expose it beyond loopback without adding auth (the handoff specifies OAuth).

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

CI (`.github/workflows/ci.yml`, the badge above) runs both suites on every push to `main` and every
pull request. The backend job starts Postgres from `compose.yaml` with a password generated for that
run, then runs `uv sync --locked` and `uv run pytest`. The web job runs typecheck, lint and vitest.

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

## Tanker monitor and CPI nowcast backend

Turns live AIS (aisstream.io) and Sentinel-1 radar into tanker state, events, per-region
metrics, and an **uncalibrated** US energy-CPI nowcast with a Strait of Hormuz disruption
shock. Regions: Corpus Christi, TX (context) and the Strait of Hormuz (signal). The HUD in `web/`
does not consume these yet; the output contract for it is [SCHEMA.md](SCHEMA.md), with sample files in
`outputs/sample/`.

AIS cannot measure the CPI level. The nowcast is anchored on official BLS/EIA prices and AIS
only supplies a disruption shock; every output carries `calibrated: false` and its assumptions.

### Pipeline

```
aisstream.io --> aperium.recorder --> data/raw_YYYYMMDD.jsonl --> aperium.run (aperium.state + zones.yaml)
                                                                    |-> outputs/latest/{region}/vessels.json, events.jsonl, metrics.json
Sentinel-1 (copernicus_demo.py -> sentinel_cache/) --> aperium.sentinel -> {region}/sentinel.json
BLS + EIA + Hormuz gate crossings --> aperium.cpi_nowcast (config.yaml) -> cpi_nowcast.json
outputs/latest/ --> aperium.api (read-only HTTP, port 8001)
```

### Run

```sh
uv sync
cp .env.example .env          # add AISSTREAM_API_KEY (aisstream.io), EIA_API_KEY (eia.gov/opendata)
uv run python -m aperium.recorder            # terminal 1: one AISstream connection, prints counts every 60 s
uv run python -m aperium.run                 # terminal 2: tails today's raw file, writes outputs every 10 s
uv run uvicorn aperium.api:app --port 8001   # terminal 3: read-only API, docs at /docs
```

Without live data (no key, or quiet AIS), replay synthetic or recorded data through the same engine:

```sh
uv run python -m aperium.synth --out data/synthetic_replay.jsonl --hours 6   # synthetic test data
uv run python -m aperium.run --replay data/synthetic_replay.jsonl --speed 30  # 0 = as fast as possible
```

Other commands: `python -m aperium.zones --map outputs/zones_map.png` (zone check map),
`python -m aperium.sentinel [--refresh]` (latest radar pass; refresh needs Copernicus creds),
`python -m aperium.cpi_nowcast [--offline]`, `python -m aperium.contract` (regenerate `schema/`),
`uv run pytest -q`.

AISstream allows one connection per key. When `aperium.app` (the collector, see above) is running
with a key, it is that connection: it subscribes to the port geofences and both monitor regions and
appends every raw message to `data/raw_YYYYMMDD.jsonl`, which `aperium.run` tails. Run
`aperium.recorder` only when the collector is not running. The collector also serves the
backend's read-only routes (`/api/regions/...`, `/api/cpi_nowcast`, `/api/cpi/scenario`), so the
HUD reaches them through its `/aperium/*` rewrite; `uvicorn aperium.api:app --port 8001` serves
them standalone.

Tunables: zones and region boxes in `zones.yaml`; CPI/shock parameters in `config.yaml`;
radar detection settings in `config.py`; tanker class/laden/barrel constants at the top of
`aperium/state.py`.

### Limitations

- **Not calibrated.** Every output says `calibrated: false`. There is no backtest; the shock chain's
  parameters (`config.yaml`) are rough literature-style assumptions, not fitted values.
- **AIS cannot measure the CPI level.** The level comes from the latest BLS print plus EIA weekly retail
  gasoline; AIS only supplies a Hormuz disruption shock on top.
- **Low counts.** Hormuz sees roughly 15-25 laden outbound tankers a day, so only rolling 24h / 3d / 7d
  windows with Poisson 90 % intervals are reported. A one-day dip is usually inside the interval.
- **Coverage, not just traffic.** aisstream.io relies on volunteer land receivers. Hormuz coverage is
  patchy (thin on the Iranian side and mid-strait) and can drop out. A drop in message volume and
  non-tanker vessels together with tankers is reported as `data_gap`, not a disruption. The coverage
  baseline ignores time-of-day patterns and needs 12 h of history before it can flag anything.
- **Baseline transit rate** (`baseline_laden_out_per_day`, 20/day) is an assumption about what the gate
  sees under normal coverage, not a measured figure.
- **Duration model.** The price shock depends on the size of the net supply loss only; duration decides
  how many days of elevated pump prices (after a 1-2 week pass-through lag) land in the current vs next
  month. Prices are assumed to revert when the disruption ends, with the same lag. Next month's baseline
  is assumed flat.
- **Offsets.** `bypass_capacity_mbd` (2.5, assumption: Saudi East-West and UAE Habshan-Fujairah
  pipelines) and a strategic stock release (`strategic_release_mbd`) are subtracted from supply at risk,
  floored at 0. Both are assumptions.
- **Gasoline weight.** The gasoline share of energy CPI uses BLS relative importances recalled from memory
  (`config.yaml`); verify against the published BLS table.
- **Vessel data.** Tanker class comes from AIS length and laden status from self-reported draught. Both
  are often missing or stale, and cargo volumes are typical loads by class, not measurements. GPS
  spoofing near Hormuz is filtered only by implied speed (> 40 kn) and a coarse 1 km land mask.
- **Zones are approximate**, hand-placed from charts (`zones.yaml`, map in `outputs/zones_map.png`).
- **Radar** covers Corpus Christi only, about one Sentinel-1 pass every 12 days; Hormuz has none.
- **Sample data is synthetic** (`aperium.synth`), tagged `status: replay`.
