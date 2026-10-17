# portwatch

Per-pass ship counts for ports, from Sentinel-1 radar (Copernicus Data Space), appended to parquet.

For each satellite track (relative orbit) over a port, `portwatch` builds a static reference image from earlier passes of
that track, finds targets on water that are much brighter than the reference, and counts the large ones. Every pass
becomes one row. The detector is the Phase 2 one, tuned on Corpus Christi.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # all tests, no network, no credentials
```

## Credentials

`ports`, `search` and the tests need none. `run` needs a Copernicus Data Space OAuth client:

1. Register at https://dataspace.copernicus.eu and open the Sentinel Hub dashboard (https://shapps.dataspace.copernicus.eu/dashboard/).
2. User settings, then OAuth clients, then create a client. Copy the id and the secret (the secret is shown once).
3. `cp .env.example .env` and fill in `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`.

`.env` is git-ignored. Never commit it. The token is requested on demand and refreshed when fewer than 60 s of its life remain.

## Commands

```
python -m portwatch ports                              # configured ports, boxes, reference windows
python -m portwatch search --port corpus_christi       # passes and relative orbits, free (public catalogue)
python -m portwatch search --port loop --days 90
python -m portwatch run --port corpus_christi --days 40            # count the last 40 days
python -m portwatch run --port corpus_christi --days 40 --refresh  # refetch cached passes, rebuild the reference
```

**One run at a time per data directory.** `run` takes an exclusive lock on `data/.lock` for its whole duration and a
second run on the same directory stops with an error instead of racing it. The parquet files are rewritten after every
pass, so the program is single-process by design. Parallel runs need separate `--data-dir`s.

**`--refresh` refetches everything**: every reference pass and every pass in the window, about 1,000 PU for Houston's 3
tracks. It never replaces a cached pass with an empty answer: if the refetch of a cached pass returns no data, the run
stops with an error naming the pass and the cache is left as it was.

`run`, per relative orbit:

1. Fetch (or load from `data/cache`) every pass of that orbit inside the reference window, and build the reference:
   per-pixel 25th, 50th and 75th percentile and minimum of VV dB, and the number of valid samples. A track with
   fewer than 3 usable reference passes is reported and not counted; reference passes that return no data are logged
   and left out. The water mask is not stored: it is recomputed from p25 on every run (`WATER_DB` and friends are part
   of `params_hash`), and the port's `exclude:` boxes are removed from it. A track without any water is reported as
   `no_water` and writes no rows.
2. Report "possibly absorbed berths": pixels that are water in the minimum reference, ship-bright in the p25
   reference (above `SHIP_DB`) and more than 10 dB above the minimum, i.e. a ship moored there in more than ~75%
   of the reference passes. The log line gives the rule, the number of blobs and the area of the largest, and the map
   PNG is rewritten on every run. (p25 minus min alone is not enough: radar speckle puts the minimum of ~15 passes more
   than 10 dB under p25 on most open water.)
3. For each pass in the last N days: skip it if `ship_counts.parquet` already has a count for the same
   `(port, image_id, params_hash, reference_id)`; otherwise load or fetch it, detect, save the overlay, and append to
   both parquet files straight away. An interrupted run resumes where it stopped; a pass with no data yet (null
   count, not cached) is fetched again on the next run.

Fallbacks in the detector (an oversize merged blob re-split at hull scale) are written to `data/run.log` with the blob
area and the parts kept. Check them against the overlays in `data/overlays/{port}/`.

## Adding a port

Add an entry to `ports.yaml`:

```yaml
my_port:
  bbox: [lon0, lat0, lon1, lat1]     # WGS84, lon0 < lon1, lat0 < lat1
  notes: what the box covers
  reference: {from: "2026-03-22T00:00:00Z", to: "2026-09-22T00:00:00Z"}   # optional, defaults to portwatch/config.py
  exclude:                           # optional: ground that reads as water
    - bbox: [lon0, lat0, lon1, lat1] # same rules as the port bbox
      note: William P. Hobby Airport runways (smooth asphalt reads as water)
```

Reference times need an explicit `Z` or `+00:00` (quote them, or YAML turns them into dates); naive times are refused.
`exclude` boxes remove water pixels whose centre lies inside the box, so nothing there is ever counted. Use them for
smooth surfaces that radar sees as water (runway asphalt: an aircraft was once counted as a ship at Houston). The boxes
are part of `reference_id`, so changing them recomputes the rows next to the old ones.

Run `search` first to see which tracks cross the box, then `run`. Look at the overlays before trusting the counts.
Boxes up to a few tens of km work; tiles over 2,500 px per side are fetched in pieces and stitched.

## Output

Everything is under `data/` (git-ignored): `ship_counts.parquet`, `detections.parquet`, `cache/`, `overlays/`, `run.log`.

`ship_counts.parquet`, one row per (port, pass, parameters, reference):

| Column | Type / meaning |
|---|---|
| port | str |
| timestamp_utc | datetime64[ns, UTC]; the start of the acquisition slice, see AIS matching |
| satellite | S1A, S1C, S1D... |
| relative_orbit, orbit_direction | the track |
| image_id | Sentinel-1 product name without the SAFE suffix |
| coverage | fraction of pixels where both the pass and the reference are valid |
| water_coverage | fraction of the static water mask imaged by the pass |
| ship_count | Int64, null when coverage is 0 (no data yet) or when the pass images none of the reference's water |
| n_rejected_large | blobs over 40,000 m2 (including re-split parts) that were dropped |
| cal_proxy_db | median of pass minus the reference median (p50) over stable bright targets (reference p25 above -5 dB, p75 - p25 below 1.5 dB, not water); NaN with fewer than 100 such pixels |
| sea_state_db | median of pass minus the reference median over water; wind roughens the sea and shifts it |
| in_reference_period | true if the pass is one of those the reference was built from (inside the window but without data does not count) |
| code_version | git short SHA of the code, `<sha>-dirty` with uncommitted changes |
| params_hash | first 12 hex of sha256 of the sorted-key JSON of the detection parameters |
| reference_id | first 12 hex of sha256 of (grid_id, orbit, window, percentile, sorted image_ids, exclude boxes, `MIN_REF_PASSES`, `REFERENCE_FORMAT`) |
| p_* | one column per detection parameter (`p_ship_db`, `p_contrast_db`, ...) |

`detections.parquet`, one row per target: `port, timestamp_utc, image_id, det_id` (image_id plus an index), `lon, lat,
area_m2, peak_db, length_m, width_m, orientation_deg` (second moments; long axis as a compass bearing in [0, 180), no
direction of travel), `n_parts` (hull-scale pieces within the target), `params_hash, reference_id`.

Rows dedupe on `(port, image_id, params_hash, reference_id)`; the newer row wins. Changing a parameter or the reference
adds rows next to the old ones instead of overwriting them.

## Joining

Take one `(params_hash, reference_id)` per (port, orbit) before anything else: rows of other parameters or references sit
next to each other in the file, and a pass appears once per combination. Then filter on `water_coverage` (drop or flag
passes that image little of the water) before aggregating, and treat a null `ship_count` as missing, never as 0.

**AIS.** `timestamp_utc` is the start of the slice of the acquisition that covers the box, not the moment a ship was
imaged. The box is imaged up to about 25 s later, so match AIS positions within +-60 s of `timestamp_utc`. Radar also places a
moving ship away from where it is: a ship moving radially is displaced along-track by about 110 s times its radial
speed (about 300 m at 5 kn), so widen the match radius for moving vessels, and compare with the interpolated AIS track
rather than a single ping.

**EIA.** Weekly series (W-FRI weeks): aggregate the passes per week, carry the number of passes next to the count, and
never fill empty weeks. A week without a pass is missing data, not zero ships.

## Processing-unit costs

Catalogue search is free. The Process API is charged in processing units (PU):

- about 15 PU per Sentinel-1 pass over the Corpus Christi box (3446 x 1658 px at 10 m), 15-20 for the Houston and LOOP boxes;
- every pass is fetched once and cached, so reruns, parameter changes and new references cost nothing;
- the first run for a track also fetches its reference passes (about 15-18 per track), so budget roughly 250-350 PU per
  track on first use, then about 15 PU per new pass (one every 12 days per track).

## Known limitations

- Counts all large vessels, not specifically tankers.
- Ships berthed tight against docks are partly missed (they sit inside the reference's bright structure or are merged into it).
- Very bright targets throw sidelobes that can be counted twice.
- Passes that built the reference are counted against a reference that includes them (`in_reference_period` marks them).
- Smooth ground that reads as water (runway asphalt) is counted as water unless a port lists it under `exclude`.
- Calibration between satellites: the first proxy (pass minus p25 over bright land) read about +1.4 dB and its noise
  was larger than any step it could have shown. Measured on stable bright targets against the median reference,
  S1A is +0.03 +- 0.05 dB and S1D is -0.03 +- 0.11 dB, so no meaningful step was found at Corpus Christi. Keep
  `satellite` as a covariate anyway.
- Very bright static or long-stay objects that are absent from the reference period (rigs at fabrication yards,
  vessels in lay-up) count as ships while they are there. Example: a ~300 m, +25-32 dB target on the Aransas Pass
  waterfront (-97.166, 27.861) in 9 of 16 passes, May-September 2026.
- The reference goes stale when new docks are built; rebuild it by changing the window.
- Passes come about every 12 days per track, so the series is sparse. Never
  resample it to daily: interpolation invents observations.
- Two hulls closer than about 130 m whose combined area is under 40,000 m2 stay one target.
