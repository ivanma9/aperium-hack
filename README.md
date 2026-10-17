# Aperium: live tanker monitor backend

Turns live AIS (aisstream.io) and Sentinel-1 radar into tanker state, events, per-region
metrics, and an **uncalibrated** US energy-CPI nowcast with a Strait of Hormuz disruption
shock. Regions: Corpus Christi, TX (context) and the Strait of Hormuz (signal). No frontend
here; the output contract for the frontend is [SCHEMA.md](SCHEMA.md), with sample files in
`outputs/sample/`.

AIS cannot measure the CPI level. The nowcast is anchored on official BLS/EIA prices and AIS
only supplies a disruption shock; every output carries `calibrated: false` and its assumptions.

## Pipeline

```
aisstream.io --> aperium.recorder --> data/raw_YYYYMMDD.jsonl --> aperium.run (aperium.state + zones.yaml)
                                                                    |-> outputs/latest/{region}/vessels.json, events.jsonl, metrics.json
Sentinel-1 (copernicus_demo.py -> sentinel_cache/) --> aperium.sentinel -> {region}/sentinel.json
BLS + EIA + Hormuz gate crossings --> aperium.cpi_nowcast (config.yaml) -> cpi_nowcast.json
outputs/latest/ --> aperium.api (read-only HTTP, port 8001)
```

## Run

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

Only one process may hold the AISstream connection per key: do not run `aperium.recorder` and
the legacy `aperium.app` collector (below) at the same time.

Tunables: zones and region boxes in `zones.yaml`; CPI/shock parameters in `config.yaml`;
radar detection settings in `config.py`; tanker class/laden/barrel constants at the top of
`aperium/state.py`.

## Limitations

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

---

# Legacy: Hormuz region AIS collector

Python + FastAPI + SQLite service that collects live AISstream positions in the
Fujairah, Shahid Rajaee, Khor Fakkan, and Jebel Ali areas through one connection.
Includes Class A and Class B reports, durable position history,
latest positions per MMSI, stale-position filtering, and automatic reconnects.

## Run

Python 3.11+ recommended (3.9+ supported). From this directory:

```sh
uv sync
cp .env.example .env
# Edit .env and set AISSTREAM_API_KEY to your AISstream key.
uv run uvicorn aperium.app:app --host 127.0.0.1 --port 8000
```

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

- `GET /api/status`: connection status, data freshness, counters, last-message times, and all geofences.
- `GET /api/ports`: port IDs and approximate bounding boxes.
- `GET /api/vessels`: fresh observed vessels inside the box.
- `GET /api/vessels?port=fujairah`: filter by port; also accepts `shahid_rajaee`, `khor_fakkan`, or `jebel_ali`.
- `GET /api/vessels?include_stale=true`: include old positions, explicitly marked stale.
- `GET /api/metrics`: combined and per-port fresh unique vessels, slow vessels (<1 knot), reported anchored vessels. Optional `?port=fujairah` filter.
- `GET /api/vessels/{mmsi}/history?limit=100`: stored observations, newest first (max 10,000).

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

Edit `PORTS` in `aperium/tracking.py` to change them, then restart.
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

SQLite history lives in `data/ais.sqlite3` and survives restarts. There is currently
no automatic retention limit: monitor disk use during extended collection.
The collector writes each position synchronously; this is intended for this small
regional subscription, not a worldwide high-throughput feed.

## Tests

```sh
uv run pytest
# Core normalization/storage tests need only the standard library:
python3 -m unittest discover -s tests -p test_tracking.py
```

Tests use synthetic AIS messages and a local WebSocket provider; no API key needed.
Provider documentation: https://aisstream.io/documentation/

## Compare with other observations

1. Check `/api/status`: `subscribed` confirms acceptance, not vessel coverage.
   `positions_received` and `last_position_at` show whether the current collector
   has received usable positions. `data_status` reports silence separately from connection state.
2. Check `/api/metrics` → `by_port`. Each port has its own freshness status.
   Existing SQLite observations can remain visible even before this session receives new data.
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
