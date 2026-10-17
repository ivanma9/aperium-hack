# Aperium: Hormuz region AIS collector

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
