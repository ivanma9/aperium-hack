# Strait of Hormuz: Sentinel-2 ship imagery

These are true-color satellite images of the **same 30 × 24 km box over the Strait of Hormuz shipping lanes**. There are roughly four dates per month, running from December 2025 to October 2026. Ships are visible: large tankers and container ships appear as bright streaks 10–30 px long, often with a visible wake.

## What's in this folder

```
images/
  2025-12/hormuz_2025-12-03_ships.jpg   one folder per month, one JPEG per date
  2026-01/...
  ...
  manifest.csv                          one row per image (date, time, cloud %, source scenes)
  zoom_cloud.json                       cloud % over the box for every pass (cache for the script)
  README.md
```

| Month | Images | Dates |
|---|---|---|
| 2025-12 | 4 | 3, 13, 23, 30 |
| 2026-01 | 4 | 2, 7, 17, 22 |
| 2026-02 | 3 | 16, 21, 26 |
| 2026-03 | 2 | 18, 28 |
| 2026-04 | 3 | 2, 7, 17 |
| 2026-05 | 4 | 2, 9, 17, 29 |
| 2026-06 | 4 | 1, 11, 18, 21 |
| 2026-07 | 4 | 6, 11, 21, 26 |
| 2026-08 | 4 | 7, 10, 25, 30 |
| 2026-09 | 4 | 4, 9, 19, 29 |
| 2026-10 | 2 | 4, 9 |

38 images in total, about 40 MB.

## The images

| Property | Value |
|---|---|
| Source | ESA Copernicus **Sentinel-2** (satellites S2A/S2B/S2C), Level-2A surface reflectance, true-color "visual" (TCI) product |
| Area | **56.331–56.633 °E, 26.431–26.649 °N**, the traffic separation lanes just north of the Musandam peninsula (Oman) and its Quoin islands |
| Resolution | **10 m per pixel**, Sentinel-2's native resolution |
| Size | 3018 × 2427 px for every image |
| Projection | UTM zone 40N (EPSG:32640), north up |
| Capture time | about **07:02 UTC** on every date (≈11:00 UAE/Oman time, ≈10:30 Iran time) |

**Every image covers exactly the same area.** The box is fixed and each date is resampled onto the same 10 m grid. Pixels line up from one date to the next, so you can compare dates directly or stack them as animation frames.

**All images are daytime.** Sentinel-2 is an optical, sun-synchronous satellite. It only captures in daylight, and it crosses this area at the same local time on every pass, roughly every 5 days, sometimes more often.

**Why this box:** the box was chosen by inspecting a 30 m mosaic of the whole strait (Qeshm/Bandar Abbas down to Musandam, 55.9–56.9 °E, 26.0–27.2 °N). Ship traffic concentrates here, in the inbound and outbound lanes north of the Quoin islands. At 30 m ships are only 1–3 px; at 10 m they are clearly recognisable.

## How dates were chosen

1. **Find every pass.** The script searches the public [Earth Search STAC catalog](https://earth-search.aws.element84.com/v1) (AWS-hosted, no account needed). Between Dec 2025 and mid-Oct 2026 it found 76 acquisition dates.
2. **Measure cloud over the box itself.** For each date the script reads the Sentinel-2 **scene classification (SCL)** band at 20 m. It counts the share of pixels in the box flagged as cloud shadow, medium- or high-probability cloud, or thin cirrus (classes 3, 8, 9, 10). This is much more accurate than the per-tile cloud figure in the catalog, which averages over a 110 km tile. A tile listed as 25% cloudy can be completely clear over the lanes, and the reverse is also true. Dates where the box is not fully imaged count as 100%.
3. **Pick about one date per week.** Each month is split into 4 roughly week-long windows. From each window, the script picks a **random** date among those with **≤ 5% cloud** over the box. The random seed is fixed (2026), so reruns give the same dates.
4. **Cloudy weeks borrow from the same month.** If a window has no clear date, the script uses the closest unused clear date from elsewhere in that month. It never borrows from neighbouring months, because those months need their own clear dates.
5. **Otherwise leave a gap.** If the month has run out of clear dates, the window stays empty rather than getting a cloudy image. This is why Feb, Mar and Apr (spring cloud season) and Oct (only half over) have fewer than 4 images.

A "tiny amount" of cloud is allowed. Every image here is ≤ 3.4% cloud over the box, and most are under 1%. One caveat: the cloud mask catches cloud well but **under-reports haze**. For example, 13 Mar 2026 measured only 10.75% but was visibly hazy with large cloud banks, so it was excluded.

## manifest.csv columns

| Column | Meaning |
|---|---|
| `date` | Acquisition date (UTC) |
| `time_utc` | Acquisition time (UTC) |
| `full` | Path to the whole-strait 30 m mosaic, if generated with `--full` (empty by default) |
| `ships` | Path to the ships image, relative to this folder |
| `tiles` | Sentinel-2 MGRS tiles mosaicked for that date |
| `ships_cloud_pct` | Cloud/shadow % over the ships box (from SCL), used for selection |
| `tile_cloud_pct` | Mean catalog cloud % across the tiles (for reference only) |
| `scene_ids` | Sentinel-2 scene IDs, for tracing back to the source data |

## Regenerating or changing the images

The images are produced by [`scripts/fetch_hormuz.py`](../scripts/fetch_hormuz.py). It runs in the project's virtualenv `.venv/`, which is built from the Anaconda Python and has `rasterio`, `numpy`, `pillow` and `requests` installed.

```bash
# from the project root
.venv/Scripts/python.exe scripts/fetch_hormuz.py
```

What it does, step by step:

1. Searches Earth Search for every Sentinel-2 L2A scene over the strait in the date range. When a tile was processed more than once, it keeps the newest version.
2. Computes the cloud % over the ships box for each date and caches the results in `zoom_cloud.json`.
3. Picks dates per month as described above.
4. For each picked date, it reads only the needed part of each tile's cloud-optimised GeoTIFF (no full-tile downloads). It mosaics the 10 m true-color pixels onto the fixed box and saves `images/YYYY-MM/hormuz_<date>_ships.jpg`. Images that already exist are skipped.
5. Writes `manifest.csv`.

Options:

| Flag | Default | Effect |
|---|---|---|
| `--start`, `--end` | `2025-12`, `2026-10` | Month range (YYYY-MM). Dates after today are ignored. |
| `--per-month` | `4` | Windows (images) per month |
| `--max-cloud` | `5` | Max cloud % over the box for a date to count as clear |
| `--fallback-cloud` | `5` | If a month runs out of clear dates, accept up to this % instead of leaving a gap. For example, `--fallback-cloud 25` fills more slots, with some cloud. |
| `--seed` | `2026` | Random seed for date choice. Change it to get a different random set. |
| `--full` | off | Also write a whole-strait mosaic per date (`*_full.jpg`, 30 m, ≈3340 × 4450 px) |
| `--res` | `30` | Resolution in metres per pixel for the `--full` mosaics |
| `--workers` | `4` | Parallel downloads |

Notes:
- **Stale files are not deleted.** If you change settings and rerun, the script writes new images and a new manifest, but it doesn't delete images from the old selection. Remove any `*_ships.jpg` not listed in `manifest.csv`.
- **Changing the area:** edit `ZOOM_BBOX` (lon/lat) in the script and delete `zoom_cloud.json`, because the cached cloud figures are specific to the box.

## Data credit

Contains modified Copernicus Sentinel data (2025–2026), processed by ESA. Accessed via Element 84's Earth Search on the AWS Registry of Open Data.
