# Output contract — tanker monitor backend

**schema_version: 2.0.0** (breaking changes from 1.0.0 — see the changelog at the bottom)

Everything the backend publishes, for the frontend to consume. Machine-readable JSON Schemas
(draft 2020-12) are in [`schema/`](schema/); they are generated from `aperium/contract.py`, the
single source of truth. Sample files that validate against them are in
[`outputs/sample/`](outputs/sample/) — build against those while live data is quiet.

## Conventions

- **Timestamps:** UTC ISO-8601 strings with a trailing `Z` (`2026-10-17T19:20:00Z`).
- **Coordinates:** `lat`/`lon` in decimal degrees. `bbox` is `[[lat_sw, lon_sw], [lat_ne, lon_ne]]`.
  Zone geometry in `regions.json` is GeoJSON, so those coordinates are `[lon, lat]`.
- **Units:** speed in knots (`speed_kn`), length/draft in metres, heading in degrees true,
  oil in barrels, prices in USD, CPI as index points (1982-84 = 100), percentages as percent (1.5 = 1.5 %).
- **Nullability:** a field is `null` when unknown — never omitted. Absent AIS static data is common.
- **Envelope:** every JSON document (not event lines) carries `schema_version`, `as_of_utc`
  (when the backend wrote it), and `calibrated: false`.
- **Honesty:** AIS cannot measure a price level. Counts, barrels, and the CPI shock are rough,
  uncalibrated estimates. Show `calibrated: false` / the `assumptions` list somewhere in the UI.
- **Versioning:** the schema will not change without bumping `schema_version` and adding a row to
  the changelog below. Additive optional fields bump the minor version; anything else bumps major.

## Files and endpoints

Files live in `outputs/latest/`, rewritten every 10 s with atomic renames (never half-written).
Region ids: `corpus_christi`, `hormuz`.

| File | API (read-only, `uvicorn aperium.api:app --port 8001`) | Schema | Refresh |
| --- | --- | --- | --- |
| `regions.json` | `GET /api/regions` | `regions` | on start |
| `{region}/vessels.json` | `GET /api/regions/{region}/vessels` | `vessels` | 10 s |
| `{region}/events.jsonl` | `GET /api/regions/{region}/events?since=&limit=` (newest first) | `event` (one per line) | append-only |
| `{region}/metrics.json` | `GET /api/regions/{region}/metrics` | `metrics` | 10 s |
| `{region}/sentinel.json` | `GET /api/regions/{region}/sentinel` | `sentinel` | 10 min |
| `{region}/<image>.png` | `GET /api/files/{image_path}` | — | per radar pass |
| `cpi_nowcast.json` | `GET /api/cpi_nowcast` | `cpi_nowcast` | 30 min |
| — | `GET /api/cpi/scenario?disruption=0.3&days=10` (alias `/cpi/scenario`) | `cpi_scenario` | on request |
| — | `GET /api/health` (file mtimes), `GET /api/schema/{name}` | — | — |

CORS is open for GET. A file that has not been written yet returns HTTP 503.

### regions.json
`regions[]`: `id`, `name`, `role`, `bbox`, `zones` (GeoJSON FeatureCollection; feature
`properties`: `id`, `name`, `kind` = `terminal` | `anchorage` | `gate` | `boundary`).
Terminals/anchorages are Polygons; gates/boundaries are LineStrings. Zone ids appear in
`vessels[].zone` and `events.zone`.

### {region}/vessels.json
`region`, `vessels[]` — tankers only (AIS ship type 80-89):

| Field | Type | Notes |
| --- | --- | --- |
| `mmsi` | string | 9 digits |
| `name`, `imo`, `destination` | string \| null | from AIS static data |
| `class` | `VLCC` \| `Suezmax` \| `Aframax` \| `product` \| null | by length: ≥300 m, 250-300, 220-250, <220 |
| `length_m`, `draft_m` | number \| null | |
| `laden` | boolean \| null | draft > 70 % of the class's typical max draft |
| `state` | `underway` \| `anchored` \| `berthed` \| `outbound_laden` | |
| `lat`, `lon` | number | |
| `speed_kn`, `heading` | number \| null | |
| `zone` | string \| null | zone id the vessel is in |
| `last_seen_utc` | timestamp | |

### {region}/events.jsonl
One JSON object per line, no envelope: `ts_utc`, `mmsi`, `name`, `type` (`ANCHORED` |
`BERTHED` | `DEPARTED` | `GATE_CROSS`), `zone`, `direction` (`inbound` | `outbound` | null;
GATE_CROSS only — inbound = toward the port / into the Gulf), `laden`, `est_barrels`
(integer | null; only laden departures and laden outbound crossings; typical load by class:
VLCC 2.0 M, Suezmax 1.0 M, Aframax 0.7 M, product 0.3 M bbl).

### {region}/metrics.json
`region`, `tankers_present`, `waiting_at_anchor`, `avg_wait_h` (null if nobody anchored),
`berthed_now`, `est_barrels_departed_today` (since 00:00 UTC), plus:

- `crossings` — rolling windows `"24h"`, `"3d"`, `"7d"`, each `{window_h, observed_h, in, out,
  laden_out}`, where every count is `{count, per_day, per_day_ci90: [low, high]}`. `observed_h` is
  the hours of the window with any AIS from the region; `per_day = count / observed_h × 24`; the
  interval is an exact Poisson 90 % interval (null when `observed_h < 1`). There are deliberately no
  hourly numbers: Hormuz sees only ~15-25 laden outbound tankers a day, so hourly counts are noise.
  Show the interval, not just the point.
- `laden_out_daily` — last 7 UTC days, oldest first: `{date, count, observed_h}`.
- `coverage_status` — `ok` | `degraded` | `data_gap`. Message volume and distinct non-tanker vessels
  over the last 3 h are compared with their trailing 7-day baseline. If they fall together with tanker
  counts it is `data_gap` (receivers went quiet), not a disruption; a fall in volume alone is
  `degraded`. Stays `ok` until 12 h of history exist.
- `coverage` — the numbers behind it: `window_h`, `messages_per_h`, `messages_per_h_baseline`,
  `non_tankers`, `non_tankers_baseline`, `tankers`, `tankers_baseline`, `baseline_hours`.
- `data_coverage {messages_last_10m, distinct_tankers, status}` — unchanged: `live`, `thin`,
  `no_data`, or `replay` (synthetic or recorded data — label it in the UI).

### {region}/sentinel.json
`region`, `image` (null when no radar image) = `{acquired_utc, satellite, image_path
(relative to outputs/latest/, serve via /api/files/), bbox, ship_count}`, `next_pass_note`.
Sentinel-1 passes Corpus Christi about every 12 days; Hormuz has no radar pipeline yet (`image: null`).

### cpi_nowcast.json
- `coverage_status` — Hormuz coverage (as in metrics.json); `data_gap` if Hormuz metrics are missing.
- `baseline` — official-data nowcast of the CPI energy index: last BLS print
  (`cpi_energy_last`, `cpi_energy_period` YYYY-MM), gasoline share of energy, EIA weekly retail
  gasoline this vs last month, → `nowcast_cpi_energy`, `nowcast_mom_pct`, `status`
  (`ok` | `partial` | `unavailable`).
- **Shock blocks** (`hormuz_scenario`, `hormuz_live.projection`, `/api/cpi/scenario`) share one shape:
  `disruption_fraction`, `days`, `start_utc`, `supply_at_risk_mbd`, `bypass_capacity_mbd`,
  `net_supply_loss_mbd`, and `months: {current_month, next_month}`. Each month has `period`,
  `elevated_pump_days`, `days_in_month`, `baseline_cpi_energy`, and `low` / `central` / `high`, each
  `{crude_shock_usd_bbl, gasoline_shock_usd_gal, energy_cpi_shock_pct, energy_cpi_index}`. Pump prices
  rise after a 1-2 week pass-through lag and stay up for `days`; each month gets the share of the
  impact matching its elevated days.
- `hormuz_live` — from observed laden outbound gate crossings: `status` (`ok` | `data_gap` |
  `no_data`; only `ok` carries numbers), `coverage_status`, `laden_out_per_day_24h` (+ `_ci90`),
  `laden_out_per_day_3d`, `baseline_laden_out_per_day`, `disruption_fraction` (+ `_ci90`),
  `days_since_drop`, `recovery_trend` (`improving` | `flat` | `worsening`, 24h vs 3d rate), and
  `projection` (a shock block, or null).
- `hormuz_scenario` — the configured default what-if (`label`, e.g. 50 % for 30 days).
- `scenario_grid` — precomputed `disruption_values` 0.0-1.0 (step 0.1) × `days_values`
  {3, 7, 14, 30}, starting now: `cells[]` of `{disruption_fraction, days, net_supply_loss_mbd,
  current_month: {low, central, high}, next_month: {low, central, high}}` with values in
  `energy_cpi_shock_pct`. Use `/api/cpi/scenario` for any other combination.
- `assumptions[]` (plain-English strings — please show them), `sources[]` (`name`, `series`,
  `fetched_utc`, `status`).

## Regions

Zones are approximate, hand-placed from charts (see `zones.yaml`, check map
`outputs/zones_map.png`). Both bboxes are wider than the original brief:
Corpus Christi `[[27.70,-97.50],[27.95,-96.85]]` (adds inner-harbor docks and the offshore
anchorage), Hormuz `[[24.90,54.90],[27.30,57.20]]` (adds Fujairah and Jebel Ali).

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| 1.0.0 | 2026-10-17 | Initial contract. |
| 2.0.0 | 2026-10-17 | Design review. **metrics.json:** removed `crossings_last_hour`; added `crossings` (24h/3d/7d windows with Poisson 90 % intervals), `laden_out_daily`, `coverage_status`, `coverage`. **cpi_nowcast.json:** added top-level `coverage_status`; `hormuz_live` rewritten (`status`, laden-outbound rates with intervals, nullable `disruption_fraction`, `days_since_drop`, `recovery_trend`, `projection`; removed `method`, `crossings_24h`, `baseline_crossings_24h`, `scenarios`); shock blocks gained `days`, `start_utc`, `bypass_capacity_mbd` and replaced `scenarios[]` with `months.current_month` / `months.next_month` × low/central/high; added `scenario_grid`. **New:** `GET /api/cpi/scenario` (`cpi_scenario` schema). Unchanged: regions, vessels, events, sentinel. |
