"""Download Sentinel-2 true-color mosaics of the Strait of Hormuz.

Searches the public Earth Search STAC catalog (no account needed), picks one
random clear date in each ~weekly window per month (cloud measured over the
ships square with the SCL mask; cloudy weeks borrow another clear date from
the same month), mosaics the
Sentinel-2 L2A "visual" (TCI) tiles over the bbox, and writes JPEGs into
images/YYYY-MM/ plus a manifest CSV. For each date it also renders a 10 m
zoom of the traffic separation lanes north of Musandam, where ships are visible.

Usage: python scripts/fetch_hormuz.py [--start 2025-12] [--end 2026-10] [--per-month 4] [--max-cloud 5] [--full]
"""
import argparse
import calendar
import csv
import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.merge import merge
from rasterio.warp import transform_bounds

STAC = "https://earth-search.aws.element84.com/v1/search"
BBOX = (55.9, 26.0, 56.9, 27.2)  # lon/lat: Qeshm/Bandar Abbas to Musandam
ZOOM_BBOX = (56.331, 26.431, 56.633, 26.649)  # shipping lanes, ~30x24 km
ZOOM_RES = 10
UTM = "EPSG:32640"
OUT = Path(__file__).resolve().parent.parent / "images"

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")


def search(start, end):
    body = {
        "collections": ["sentinel-2-l2a"],
        "bbox": list(BBOX),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 200,
    }
    items, url = [], STAC
    while url:
        r = requests.post(url, json=body, timeout=60)
        r.raise_for_status()
        js = r.json()
        items += js["features"]
        nxt = next((l for l in js.get("links", []) if l["rel"] == "next"), None)
        url, body = (nxt["href"], nxt.get("body", body)) if nxt else (None, None)
    return items


def group_by_date(items):
    """date -> {tile: item}, keeping the newest processing of duplicate tiles."""
    by_date = defaultdict(dict)
    for it in items:
        p = it["properties"]
        d, tile = p["datetime"][:10], p["grid:code"]
        prev = by_date[d].get(tile)
        if prev is None or p.get("updated", "") > prev["properties"].get("updated", ""):
            by_date[d][tile] = it
    return by_date


CLOUD_CLASSES = [3, 8, 9, 10]  # SCL: cloud shadow, cloud medium/high prob, thin cirrus


def zoom_cloud(tiles):
    """% of the ships square flagged cloud/shadow by the SCL mask (100 if not fully imaged)."""
    bounds = transform_bounds("EPSG:4326", UTM, *ZOOM_BBOX)
    srcs = [rasterio.open(t["assets"]["scl"]["href"]) for t in tiles.values()]
    try:
        scl, _ = merge(srcs, bounds=bounds, res=20, nodata=0)
    finally:
        for s in srcs:
            s.close()
    scl = scl[0]
    valid = scl > 0
    if valid.mean() < 0.95:
        return 100.0
    return round(100 * np.isin(scl[valid], CLOUD_CLASSES).mean(), 2)


def cloud_table(by_date, workers):
    """date -> ships-square cloud %, cached in images/zoom_cloud.json."""
    cache_path = OUT / "zoom_cloud.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = [d for d in by_date if d not in cache]
    with ThreadPoolExecutor(workers) as ex:
        for d, pct in zip(todo, ex.map(lambda d: zoom_cloud(by_date[d]), todo)):
            cache[d] = pct
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), indent=1))
    return cache


def pick_dates(dates, cloud, year, month, per_month, rng, max_cloud, fallback_cloud):
    """One random clear date per ~week-long window of the month.

    A window with no clear date borrows the closest unused clear date from
    elsewhere in the month; failing that, the least cloudy unused date up to
    fallback_cloud; failing that, the window is left empty.
    """
    ym = f"{year}-{month:02d}"
    month_dates = [d for d in dates if d[:7] == ym]
    days = calendar.monthrange(year, month)[1]
    edges = np.linspace(1, days + 1, per_month + 1)
    windows = [(int(edges[i]), int(edges[i + 1])) for i in range(per_month)]
    used = set()

    picks = [None] * per_month
    for i, (lo, hi) in enumerate(windows):
        ok = [d for d in month_dates if lo <= int(d[8:]) < hi and cloud[d] <= max_cloud]
        if ok:
            picks[i] = str(rng.choice(ok))
            used.add(picks[i])
    for i, (lo, hi) in enumerate(windows):
        if picks[i]:
            continue
        mid = (lo + hi) / 2
        spare = [d for d in month_dates if d not in used]
        near = sorted((d for d in spare if cloud[d] <= max_cloud), key=lambda d: abs(int(d[8:]) - mid))
        meh = sorted((d for d in spare if cloud[d] <= fallback_cloud), key=cloud.get)
        if near or meh:
            picks[i] = (near or meh)[0]
            used.add(picks[i])
    return sorted(d for d in picks if d)


def mosaic(tiles, bbox, res, path):
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    bounds = transform_bounds("EPSG:4326", UTM, *bbox)
    srcs = [rasterio.open(t["assets"]["visual"]["href"]) for t in tiles.values()]
    try:
        arr, _ = merge(srcs, bounds=bounds, res=res, nodata=0)
    finally:
        for s in srcs:
            s.close()
    Image.fromarray(np.moveaxis(arr[:3], 0, -1)).save(path, quality=90)
    return path


def render(d, tiles, res, with_full):
    month_dir = OUT / d[:7]
    full = mosaic(tiles, BBOX, res, month_dir / f"hormuz_{d}_full.jpg") if with_full else None
    zoom = mosaic(tiles, ZOOM_BBOX, ZOOM_RES, month_dir / f"hormuz_{d}_ships.jpg")
    return full, zoom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-12")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--per-month", type=int, default=4)
    ap.add_argument("--max-cloud", type=float, default=5, help="max cloud %% over the ships square")
    ap.add_argument("--fallback-cloud", type=float, default=5, help="accept up to this if a month runs out of clear dates")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--full", action="store_true", help="also write whole-strait mosaics")
    ap.add_argument("--res", type=float, default=30, help="whole-strait metres/pixel")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    sy, sm = map(int, a.start.split("-"))
    ey, em = map(int, a.end.split("-"))
    end_day = min(date(ey, em, calendar.monthrange(ey, em)[1]), date.today())
    items = search(f"{sy}-{sm:02d}-01", end_day.isoformat())
    by_date = group_by_date(items)
    print(f"{len(items)} items, {len(by_date)} dates")
    cloud = cloud_table(by_date, a.workers)
    dates = sorted(by_date)

    rng = np.random.default_rng(a.seed)
    picks = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        picks += pick_dates(dates, cloud, y, m, a.per_month, rng, a.max_cloud, a.fallback_cloud)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(render, d, by_date[d], a.res, a.full): d for d in picks}
        for f in as_completed(futs):
            d = futs[f]
            tiles = by_date[d]
            try:
                full, zoom = f.result()
                print("ok  ", d)
            except Exception as e:  # keep going; report at the end
                full = zoom = None
                print("FAIL", d, e)
            rows.append({
                "date": d,
                "time_utc": min(t["properties"]["datetime"][11:19] for t in tiles.values()),
                "full": full.relative_to(OUT).as_posix() if full else "",
                "ships": zoom.relative_to(OUT).as_posix() if zoom else "",
                "tiles": " ".join(sorted(tiles)),
                "ships_cloud_pct": cloud[d],
                "tile_cloud_pct": round(np.mean([t["properties"].get("eo:cloud_cover", -1)
                                                 for t in tiles.values()]), 1),
                "scene_ids": " ".join(t["id"] for t in tiles.values()),
            })

    rows.sort(key=lambda r: r["date"])
    with open(OUT / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {sum(bool(r['ships']) for r in rows)}/{len(rows)} dates to {OUT}")


if __name__ == "__main__":
    main()
