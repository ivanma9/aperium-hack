# Phase 3 plan: `portwatch` package and dataset

Goal: turn the Phase 2 Copernicus script into a small package that appends per-pass ship counts for any port in `ports.yaml` to parquet, with tests and a README. The detector itself is unchanged from Phase 2.

Decisions already made:
- Earth Engine is dropped. `gee_demo.py` is deleted and stays in git history.
- Every satellite track over a port is counted, and each port and track gets its own reference image.

## Layout

```
portwatch/
  __init__.py
  __main__.py      # python -m portwatch -> cli.main()
  config.py        # detection parameters (moved from ./config.py), params_hash()
  ports.py         # load + validate ports.yaml
  copernicus.py    # catalogue search, token, tiled Process API fetch, on-disk pass cache
  reference.py     # per-(port, track) reference image from cached passes
  detect.py        # detect_ships, pixel_to_lonlat, draw_overlay (Phase 2 code, unchanged logic)
  dataset.py       # append/dedupe parquet
  cli.py           # ports | search | run
ports.yaml
tests/
  conftest.py      # synthetic scene helpers
  test_detect.py
  test_tiling.py
  test_reference.py
  test_dataset.py
  test_ports.py
README.md
```

`copernicus_demo.py`, `gee_demo.py` and the root `config.py` are removed. `requirements.txt` adds `pyyaml`, `pandas`, `pyarrow` and `pytest`, each pinned to the version that gets installed.

## Behaviour

### `ports.yaml`
For each port: `name` (key), `bbox: [lon0, lat0, lon1, lat1]` and `notes`. Optional `reference: {from, to}` overrides the global window in `config.py`.

| Port | bbox | Covers |
|---|---|---|
| `corpus_christi` | -97.30, 27.75, -96.95, 27.90 | Phase 2 box |
| `houston_ship_channel` | -95.30, 29.60, -94.95, 29.78 | Upper channel and terminals, Battleship Texas to the turning basin. The Galveston offshore anchorage can be added later as its own port. |
| `loop` | -90.15, 28.80, -89.90, 28.95 | Louisiana Offshore Oil Port buoys and anchorage |

### Tiled fetch (`copernicus.py`)
- `tile_edges(n, max_px)` splits n pixels into `ceil(n/max_px)` near-equal spans: `[round(i*n/k) for i in range(k+1)]`.
- Tiling works on both axes. A tile covers the lon/lat span of its exact pixel range in the full W×H grid.
- Tiles are stitched with `np.block`.

### Pass cache
- Each S1 pass is fetched once for each port bbox and stored as `data/cache/{port}/{image_id}.npz`, holding the raw uint16 dB encoding, compressed.
- `--refresh` refetches.
- A pass with no data is cached too, so the catalogue doesn't keep re-requesting it.

### Tracks
- Scenes are grouped by `relative_orbit`.
- The reference for a (port, orbit) uses the cached passes of that orbit whose start falls in the reference window.
- Per-pixel percentile on dB: sort the valid samples, take `v[floor(PCT/100*(n-1))]`, and return NaN if fewer than 3 samples are valid. This is the same index rule as the Phase 2 evalscript.
- The result is saved as `data/cache/{port}/reference_orbit{N}_{from}_{to}_p25.npy`.
- If fewer than 3 passes exist in the window, `run` exits with a clear message for that orbit instead of counting.

### `run --port X --days N`
For every S1 pass in the last N days, per orbit:
1. Ensure the reference exists.
2. Load or fetch the pass.
3. Detect.
4. Save `data/overlays/{port}/{stamp}_orbit{N}.png`.
5. Append to parquet.

### Parquet (`dataset.py`)

`data/ship_counts.parquet`, one row per (port, pass):

| Column | Type |
|---|---|
| port | str |
| timestamp_utc | datetime64[ns, UTC], real acquisition start |
| satellite | str |
| relative_orbit | int |
| orbit_direction | str |
| image_id | str |
| coverage | float |
| ship_count | Int64, nullable; null when coverage is 0 |
| params_hash | str |
| one column per detection parameter, prefixed `p_` | |

`data/detections.parquet`, one row per target:

| Column |
|---|
| port |
| timestamp_utc |
| image_id |
| lon |
| lat |
| area_m2 |
| peak_db |
| params_hash |

- Appending dedupes on `(port, image_id, params_hash)`; the newer row wins.
- `params_hash` is the first 12 hex characters of the sha256 of the sorted-key JSON of the detection parameters.

## Carried over from the Phase 2 code review

Already fixed in Phase 2:
- The merge-distance description now says candidates up to about 2×MERGE_M apart are merged.
- Oversize merged clusters fall back to their individual parts instead of being dropped.
- Only passes in the reference's orbit direction are processed.
- `gee_demo.py` is removed.

Built into Phase 3:

| # | Finding | How Phase 3 handles it |
|---|---|---|
| I-3 | Series runs are all-or-nothing, and the token expires | `dataset.append()` runs after every pass. Passes already in parquet for the same params_hash are skipped, so runs resume. The token is refreshed when fewer than 60 s of `expires_in` remain. API errors still exit loudly. |
| I-4 | Orbit geometry isn't enforced from end to end | Each reference belongs to one (port, relative_orbit) and is built only from that orbit's passes. The cache key includes port, orbit, window, percentile and a hash of the fetch request and evalscript. |
| I-5 | Busy berths can be absorbed into the reference | The local stack makes a minimum reference free alongside p25. Each run reports water pixels where p25 − min > 10 dB ("possibly absorbed berths") and saves a map PNG per (port, orbit). Switching to p10 is a decision for later, made on the evidence. |
| I-6 | No way to spot the S1A to S1D calibration step | New per-pass QC columns: `cal_proxy_db` (median of db − ref over stable land pixels with ref above -12 dB) and `sea_state_db` (median of db − ref over water). |
| M1 | Water mask and coverage depend on the pass | The water mask is built once per reference from the reference alone and cached. `coverage` is the fraction of pixels where both db and ref are valid. A new `water_coverage` column is the fraction of the static water mask imaged. |
| M2 | Timestamp is the slice start | Documented in the README: the bbox is imaged up to about 25 s after `timestamp_utc`, so use a ±60 s window for AIS matching. |
| M3 | Provenance is incomplete | Each row carries `params_hash`, `reference_id`, `in_reference_period` and `code_version` (the git short SHA, or "dirty"). |
| M5 | Catalogue results can be truncated | The search pages with `$skip` until the result set is exhausted. |
| M6 | Robustness gaps | Every save is atomic: write to a temporary file, then rename. Tile shape and dtype are asserted. `"polarization": "DV"` is set in the dataFilter. |
| M7 | Join schema is thin | Detections gain `det_id` (image_id plus an index), `length_m`, `width_m` and `heading_deg` from second moments, and `n_parts`. |
| — | Oversize rejections are invisible | A per-pass `n_rejected_large` column counts blobs over MAX_AREA, including parts, that were dropped. |

Additional tests (on top of the ones below):
- **20. Oversize fallback:** three 6×30 px ships with 80 m gaps give 3 targets. One 25×25 px blob (62,500 m²) gives 0 targets and `n_rejected_large` = 1.
- **21. Absorbed-berth diagnostic:** in a stack of 15 passes where a ship is present in 12, the pixel is flagged by p25 − min > 10 dB. With the ship present in 2, it isn't flagged.
- **22. Second moments:** a 6×30 px horizontal blob gives `length_m` ≈ 300, `width_m` ≈ 60 (each within 15%) and `heading_deg` ≈ 90 (within 5°).
- **23. Resume:** running `append` with the same image_id and params_hash skips the pass, which the fetch function confirms by not being called.
- **24. QC columns:** a pass offset by +1 dB everywhere gives `cal_proxy_db` ≈ 1.0 (within 0.1).

Test 6 changes to match the real merge rule: a 40 m gap gives 1 target, and a 150 m gap gives 2.

## Tests (written first; each must fail with the expected assertion before implementation)

Synthetic setup (`conftest.py`):
- reference `ref` = calm water drawn from N(-22, 0.5) dB, 400×400 px at 10 m;
- pass = ref + N(0, 1);
- fixed RNG seed.

### test_detect.py
1. **Ships on water:** a 6×20 px blob at +12 dB and a 4×10 px blob at +8 dB on water give exactly 2 targets, with areas 12000 and 4000 m² and centroids within 1 px of the true centres.
2. **Bright land:** ref columns 0–119 at -8 dB (land), and the pass has a 30×30 block at +10 dB on that land. Result: 0 targets, and the water mask is all False on columns 0–119.
3. **Static bright structure on water:** a dock is +5 dB in the ref and +6 dB in the pass. Result: 0 targets, because the contrast is below 10 dB.
4. **Speckle:** isolated 1 px and 3×3 px returns at +10 dB on water give 0 targets, since they're under 1500 m². A pure noise pass (ref + N(0, 3)) gives 0 targets.
5. **Image edges:**
   - A ship on rows 0–5 (touching the top edge) gives 1 target, with its centroid inside the image.
   - With the pass's left half NaN, a ship entirely inside the NaN area gives 0 targets.
   - A ship adjacent to the NaN boundary on the valid side gives 1 target.
   - The water mask is False wherever the pass is NaN.
   - With ref NaN and the pass valid at a pixel, that pixel is never water.
6. **Merge rule:** two 4×10 px blobs with a 40 m gap give 1 target. The same blobs 150 m apart give 2.
7. **Size limits:** a blob of exactly 15 px (1500 m²) gives 1 target; 14 px gives 0. A blob of exactly 400 px (40000 m²) gives 1; 401 px gives 0.
8. **Small water body:** a 0.05 km² pond surrounded by land, with a ship in it, gives 0 targets.
9. **`pixel_to_lonlat`:** on a 100×200 grid, (row 0, col 0) maps to (x0 + 0.5·dx, y1 − 0.5·dy), and (99, 199) maps to (x1 − 0.5·dx, y0 + 0.5·dy).

### test_tiling.py
10. `tile_edges(3446, 2500)` returns `[0, 1723, 3446]`. `tile_edges(1658, 2500)` returns `[0, 1658]`. `tile_edges(5000, 2500)` returns `[0, 2500, 5000]`.
11. The tile bboxes for a 5000×3000 grid form 2×2 tiles. Their union equals the full bbox exactly, adjacent tiles share edges exactly, and each tile's pixel size equals its span divided by the global dlon/dlat.

### test_reference.py
12. For a stack of 4 arrays with values [-20, -10, 0, 10] at a pixel, the p25 result is -20, since floor(0.25·3) = 0. With values [-20, NaN, 0, 10], the result is -20, using index floor(0.25·2) = 0.
13. With fewer than 3 valid samples at a pixel, the result is NaN.

### test_dataset.py
14. Appending the same 2 rows twice leaves 2 rows. Appending a row with the same (port, image_id, params_hash) and a different count keeps the new count.
15. A null `ship_count` survives a round trip as `<NA>`, not 0. The `timestamp_utc` dtype is `datetime64[ns, UTC]`.
16. Rows with a different `params_hash` for the same pass are both kept.

### test_ports.py
17. `ports.yaml` loads all 3 ports.
18. A bbox with lon0 ≥ lon1 or lat0 ≥ lat1 raises `ValueError`.
19. An unknown port name raises `KeyError`, and the message lists the valid names.

Negative-case checklist (validation):
- Empty input is covered by 4 (noise only).
- The max-length analogue is the size limits in 7.
- Unicode and type-coercion cases are N/A: the inputs are numeric arrays and a controlled YAML file.

Authz, race and payment checklists are N/A: there are no users or concurrency, and runs are single-process.

## Verification runs (cost in Copernicus processing units, PU)
1. `pytest -q`: all tests pass.
2. **Corpus Christi parity:** `python -m portwatch run --port corpus_christi --days 183`.
   - The reference is now built locally from about 15 passes (03-26 to 09-11), compared with Sentinel Hub's percentile in Phase 2.
   - Accept if each pass's count is within ±1 of `output/ship_counts.csv`.
   - Cost: about 23 unique passes at 15 PU, roughly 350 PU.
3. **Houston and LOOP:** `search` first to see the tracks. Then `run --days 36`, about 3 passes per track, each building its reference first.
   - Cost: about 18 passes per track at 15–20 PU, roughly 1–1.5k PU in total.
   - Look at the overlays before trusting the counts.
4. Code review loop until no Critical or Important issues remain. Then commit and push to `claude/tanker-activity-corpus-christi-4030ce`, never `main`.

## README contents
- Setup: venv and requirements.
- Credentials: `.env`, where to get the CDSE OAuth client, never commit it.
- Commands.
- How to add a port.
- Output schema.
- PU costs.
- Known limitations:
  - counts all large vessels, not specifically tankers;
  - ships berthed tight against docks are partly missed;
  - very bright targets throw sidelobes that can be counted twice;
  - passes inside the reference window are counted against a reference that includes them;
  - S1A and S1D calibration;
  - the reference goes stale when new docks are built;
  - about one pass every 12 days per track, so never resample to daily.

## Amendments from the Phase 2 re-review (these supersede the text above wherever they conflict)

**A1. Cache and resume keys include the grid and the reference.**
- `grid_id` = sha256[:12] of (bbox, RES_M, S1 fetch request body, S1 evalscript).
- `reference_id` = sha256[:12] of (grid_id, relative_orbit, window from/to, pct, the sorted image_ids used).
- Passes are cached under `data/cache/{port}/{grid_id}/{image_id}.npz`. Each npz stores `bbox` and `shape`, and both are asserted on load.
- References are cached under `data/cache/{port}/{grid_id}/reference_{reference_id}.npz`, which holds `p{pct}`, `min`, `n_samples` and `water`.
- Resume and dedupe key on `(port, image_id, params_hash, reference_id)`, and `reference_id` is a column in both parquet files.
- Test 25: the same image_id and params_hash with a different reference_id gets recomputed. A different bbox for the same port gives a different grid_id, so a cached npz is never reused across bboxes.

**A2. Passes with no data are retried, not frozen.**
- No-data fetches are not cached.
- Resume never skips a row whose `ship_count` is null; it fetches that pass again. The new row replaces the null row through dedupe.
- Test 26: a pass whose fake fetch first returns all-NaN and then real data ends with a non-null count after two runs. A pass that already has coverage above 0 isn't fetched again.

**A3. The absorbed-berth report uses a water mask built from the minimum reference.**
- The mask is the median-smoothed (WATER_SMOOTH_M) `min` reference below WATER_DB. It is not the p25 water mask, which by construction excludes absorbed berths.
- The report flags pixels in that mask where p25 − min > 10 dB.
- Test 21 now goes through the report function: 15 passes, ship present in 12 → flagged, ship present in 11 → not flagged.

**A4. Detector changes already in the Phase 2 commit, carried into `detect.py`:**
- An oversize merged blob is re-split at `SPLIT_M` = 20 m (hull scale) and cropped to its bounding box.
- Test 20 cases, with ships modelled as 30 px hulls made of 3 bright clusters and 20–30 m dark gaps:
  - 1, 2 and 3 such tankers with 80 m gaps give 1, 1 and 3 targets. The 2 → 1 step is documented: two hulls under MAX_AREA stay merged.
  - Three solid 6×30 px ships with 80 m gaps give 3 targets, with `n_rejected_large` = 0.
  - A 44,000 m² ship split by a 20 m gap gives 0 targets and `n_rejected_large` = 1.
- Log every fallback (blob area and parts kept) to the run log, so it can be eyeballed on real overlays.
- Open question for later, decided on `n_parts` evidence and re-validated on 09-23, 10-05 and 10-17: a size-aware split for all merged blobs (split at SPLIT_M only when two or more parts are each at least 5,000 m²).

**A5. Test fixes:**
- **Test 6** uses the boundary: a 120 m gap gives 1 target and a 130 m gap gives 2.
- **Test 22:**
  - The estimator is length = √12·σ_major and width = √12·σ_minor, with a 2% tolerance (a 6×30 px blob gives 300 by 60 m).
  - Add a NE–SW diagonal blob that should give 45°, which checks the row-axis flip.
  - Rename the field to `orientation_deg` in [0, 180), since second moments carry no direction.
- **Test 23** asserts that detect isn't called and no row is written, not just that fetch isn't called.
- **Test 24:** the scene includes a land block (ref -8 dB). A pass at +1 dB everywhere gives `cal_proxy_db` ≈ 1. A pass at +1 dB on water only gives `sea_state_db` ≈ 1 and `cal_proxy_db` ≈ 0.
- **Test 5:** `detect_ships` returns the static water mask AND pass validity. The water mask is False where the pass is NaN, and the static mask is unchanged.

**A6. Verification step 2 corrections:**
- The reference window holds the 04-01 to 09-11 passes, about 15 of them. Only track 107 covers the bbox, so about 18 unique passes get fetched.
- Build the baseline without spending extra PU. Run the Phase 2 commit's `detect_ships` on the passes Phase 3 caches, against the Phase 2 Sentinel Hub reference in `output/reference_*.npy`. The fallback changed the detector, so the old CSV is not the baseline.
- Then require ±1 per pass.
- Visually check the 06-12 overlay (S1A, the series maximum) and the persistent bright target at (-97.166, 27.861).

**A7. The absorbed-berth rule needs `p25 > SHIP_DB`.**
- The rule is: a pixel of the water mask built from the `min` reference, with `p25 > SHIP_DB` and `p25 - min > ABSORBED_DB`.
- `p25 - min > 10 dB` alone is wrong. On real Corpus Christi data it flagged 287,794 pixels, almost all speckle:
  the minimum of ~15 passes of open water sits more than 10 dB under p25 on most of it.
- Requiring p25 itself to be ship-bright keeps only what a ship moored in more than ~75% of the reference passes can produce.
- The log line states the full rule, the number of blobs and the area of the largest one, and the map is rewritten every run.
- Test 21c covers it: speckle and sea state alone flag nothing.
- Also from the review (supersedes A1's list of reference arrays): a reference npz holds `p25`, `p50`, `p75`, `min` and `n_samples`,
  and no water mask, which is recomputed on every run. `reference_id` also hashes the exclude boxes, `MIN_REF_PASSES` and `REFERENCE_FORMAT`.
