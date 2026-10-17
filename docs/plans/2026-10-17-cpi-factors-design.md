# CPI factor picker — MVP design (2026-10-17)

Let a user choose which factors and regions drive the energy-CPI nowcast, with toggles + sliders,
recomputed by the backend. MVP: minimal, plugs into the existing API router and web app.

## Decisions

- **Compute on the backend.** `aperium/cpi_nowcast.py` stays the only copy of the math. New module
  `aperium/cpi_factors.py`; new GET routes on the existing `aperium/api.py` router (so the collector on
  :8000 serves them and the web app reaches them through the `/aperium/*` rewrite). GET only (CORS is GET-only).
- **Requests never hit the network.** `cpi_nowcast.build()` (run every 30 min by `aperium.run`) also
  refreshes two new cache entries; the endpoints read caches with `offline=True` semantics.
- **Supply side: chokepoints aggregate to one shock.** Hormuz, Malacca, Bab el-Mandeb, Suez. Net loss per
  chokepoint = max(0, fraction x flow - bypass). Total = sum, minus strategic release (global). One global
  crude -> gasoline -> CPI chain. Hormuz flow/bypass defaults come from `config.yaml` (so defaults reproduce
  the existing nowcast); the others from `aperium/seed.py` GEOGRAPHIES (`base_mbd`, `bypass_cap_mbd`).
  Only Hormuz has a `live` source (from `hormuz_live`); others are manual.
- **Overlap flag.** Hormuz flow largely also transits Malacca / Bab el-Mandeb+Suez. If Hormuz and any other
  chokepoint both have net loss > 0, set `overlap_warning` and report `net_supply_loss_lower_bound_mbd` =
  largest single chokepoint net loss (after release). No invented correction factor.
- **Demand side: US region.** national / northeast / midwest / south / west, or `all` (compare). National is
  BLS's own published national series — we never re-weight regions.
  Verified live 2026-10-17:
  | region | BLS energy | BLS gasoline | EIA weekly retail regular |
  |---|---|---|---|
  | national | CUUR0000SA0E | CUUR0000SETB01 | EMM_EPMR_PTE_NUS_DPG |
  | northeast | CUUR0100SA0E | CUUR0100SETB01 | EMM_EPMR_PTE_R10_DPG (PADD 1 East Coast) |
  | midwest | CUUR0200SA0E | CUUR0200SETB01 | EMM_EPMR_PTE_R20_DPG (PADD 2) |
  | south | CUUR0300SA0E | CUUR0300SETB01 | EMM_EPMR_PTE_R30_DPG (PADD 3 Gulf Coast) |
  | west | CUUR0400SA0E | CUUR0400SETB01 | EMM_EPMR_PTE_R50_DPG (PADD 5 West Coast) |
  PADDs are not census regions: the pairing is approximate and stated in assumptions. Regional gasoline share
  of energy is not verified, so regions use the national share with `gasoline_share_source: "national_fallback"`.
  The crude/gasoline $ shock is the same in every region; the % differs by regional gasoline price.
  EIA multi-series requests ignore `length` (5000-row cap): filter with `start` (~120 days back).
- **Factors** (toggle / sliders, defaults from config):
  - BLS anchor: locked on. Slider `gasoline_share` (national override, 0.2-0.8).
  - EIA gasoline MoM move: toggle `eia_move` (off = carry last BLS print flat, `nowcast_mom_pct` 0).
  - Chokepoints: enable list; per chokepoint `source` (live|manual), `fraction` 0-1, `bypass_mbd` 0-25.
    Live disabled (falls back to unavailable status, not a silent 0) when `hormuz_live.status != "ok"`.
    `baseline_transits` (10-30) recomputes the live Hormuz fraction from `laden_out_per_day_24h`.
  - Strategic release: toggle + `release_mbd` 0-4 + `release_scale` 0-1.
  - Crude response: locked on; `sensitivity_central` 1-20 (low = x0.5, high = x2).
  - Pump: locked on; `pass_through` 0-1, `lag_days` 0-30. Shared `days` 1-90 duration, start = now.
- **Contributions** (central case, current and next month, energy-CPI %): EIA baseline move, each chokepoint's
  gross shock, bypass offset (negative), strategic release (negative). The chain is linear in net mb/d, so
  per-mb/d attribution is exact; release is attributed after summing (stated in assumptions).
- **Out of MVP:** Corpus Christi / Sentinel (not price inputs; possible read-only evidence panel later),
  electricity / natural gas held flat, per-chokepoint durations, live AIS gates outside Hormuz.

## API

- `GET /api/cpi/factors` — catalog: factor list (id, label, kind toggle|slider|locked, default, min, max,
  step, unit, available, reason), chokepoints (id, name, flow_mbd, default bypass, live_available + reason),
  regions (id, name, series, baseline status, data period). Schema `cpi_factors`.
- `GET /api/cpi/custom?...` — query params as above; chokepoint params prefixed by id with underscores
  (`hormuz_source`, `bab_el_mandeb_fraction`, ...); `chokepoints=hormuz,suez`; `region=national|...|all`.
  Returns envelope + `inputs` (resolved values), `supply` (per chokepoint at_risk/bypass/net, total, release,
  lower bound, overlap_warning), `regions[]` (each: baseline + months current/next low/central/high reusing
  the MONTH shape + contributions), `assumptions[]`, `sources[]`. Schema `cpi_custom`.
- Contract bump 2.0.0 -> 2.1.0, SCHEMA.md changelog row, regenerate `schema/`.

## Web (standalone, does not touch existing components)

`web/src/app/factors/page.tsx` + `web/src/components/FactorPanel.tsx` + `web/src/lib/aperium/cpi.ts` (types +
fetchers via `/aperium/cpi/...`). Loads catalog, renders toggles/sliders per factor, chokepoint rows, region
picker incl. compare; debounced (150 ms) refetch of `/cpi/custom`; shows nowcast, contribution bars, region
table, overlap warning, assumptions. Reuses existing CSS classes (`panel`, `glass`, ...).
