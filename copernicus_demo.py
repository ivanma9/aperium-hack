#!/usr/bin/env python3
"""Tanker activity at Corpus Christi from the Copernicus Data Space.

--search-only lists recent Sentinel-1 (radar) and Sentinel-2 (optical) scenes
from the public OData catalogue; no credentials needed.

Without it, a static reference (per-pixel 25th percentile of VV dB over six
months of earlier passes, where moving ships vanish but docks and platforms
stay) and the chosen Sentinel-1 pass are fetched through the Sentinel Hub
Process API at 10 m. Targets on water that are much brighter than the
reference are merged, size filtered and counted, and the newest low-cloud
Sentinel-2 scene is saved as a true-colour image for visual checking.
Settings are in config.py. Needs CDSE_CLIENT_ID / CDSE_CLIENT_SECRET in .env.
"""
import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from scipy import ndimage

import config

load_dotenv()

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

MAX_PX = 2500         # Process API limit per side
NODATA = 0            # UINT16 code for no data
DB_OFFSET, DB_SCALE = 50.0, 500.0  # dB = value / DB_SCALE - DB_OFFSET, covers -50 to ~+81 dB

S1_EVALSCRIPT = f"""//VERSION=3
function setup() {{
  return {{input: ["VV", "dataMask"], output: {{bands: 1, sampleType: "UINT16"}}}};
}}
function evaluatePixel(s) {{
  if (s.dataMask == 0) return [{NODATA}];
  var db = 10 * Math.log(Math.max(s.VV, 1e-6)) / Math.LN10;
  return [Math.max(1, Math.min(65535, Math.round((db + {DB_OFFSET}) * {DB_SCALE})))];
}}
"""

REF_EVALSCRIPT = f"""//VERSION=3
function setup() {{
  return {{input: [{{bands: ["VV", "dataMask"]}}], mosaicking: "ORBIT", output: {{bands: 1, sampleType: "UINT16"}}}};
}}
function evaluatePixel(samples) {{
  var v = [];
  for (var i = 0; i < samples.length; i++) if (samples[i].dataMask == 1) v.push(samples[i].VV);
  if (v.length < 3) return [{NODATA}];
  v.sort(function(a, b) {{ return a - b; }});
  var db = 10 * Math.log(Math.max(v[Math.floor({config.REFERENCE_PCT} / 100 * (v.length - 1))], 1e-6)) / Math.LN10;
  return [Math.max(1, Math.min(65535, Math.round((db + {DB_OFFSET}) * {DB_SCALE})))];
}}
"""

S2_EVALSCRIPT = """//VERSION=3
function setup() {
  return {input: ["B02", "B03", "B04", "dataMask"], output: {bands: 4}};
}
function evaluatePixel(s) {
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02, s.dataMask];
}
"""


# ---------------------------------------------------------------- search

def bbox_wkt(bbox):
    x0, y0, x1, y1 = bbox
    return f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def image_id_from_name(name):
    """Product name without the SAFE suffix. For the original (non-COG) S1 GRD copy this
    is the stable id of the acquisition; the COG copy has a different product code."""
    for suffix in ("_COG.SAFE", ".SAFE"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def search(collection, name_contains, bbox, since, max_cloud=None, top=200):
    """Scenes intersecting bbox since `since`, newest first, one per acquisition.

    One acquisition can appear several times: S1 as SAFE and COG copies, S2 as one
    product per tile. S1 keeps the SAFE copy; cloud cover is the worst tile, so an
    acquisition passes max_cloud only if every tile over the area does.
    """
    filters = [
        f"Collection/Name eq '{collection}'",
        f"contains(Name,'{name_contains}')",
        f"OData.CSC.Intersects(area=geography'SRID=4326;{bbox_wkt(bbox)}')",
        f"ContentDate/Start gt {since:%Y-%m-%dT%H:%M:%S.000Z}",
    ]
    params = {
        "$filter": " and ".join(filters),
        "$orderby": "ContentDate/Start desc",
        "$top": top,
        "$expand": "Attributes",
    }
    r = requests.get(CATALOGUE_URL, params=params, timeout=60)
    if not r.ok:
        sys.exit(f"Catalogue search failed: HTTP {r.status_code}\n{r.text[:500]}")

    value = r.json()["value"]
    if len(value) == top:
        print(f"WARNING: catalogue returned the maximum {top} rows for {collection}; "
              "older scenes may be missing. Shorten --days.", file=sys.stderr)

    scenes = {}
    for p in value:
        start = parse_time(p["ContentDate"]["Start"])
        key = (p["Name"][:3], start.replace(microsecond=0))
        attrs = {a["Name"]: a["Value"] for a in p.get("Attributes", [])}
        scene = {
            "name": p["Name"],
            "image_id": image_id_from_name(p["Name"]),
            "platform": p["Name"][:3],
            "start": start,
            "end": parse_time(p["ContentDate"]["End"]),
            "orbit_direction": attrs.get("orbitDirection"),
            "relative_orbit": attrs.get("relativeOrbitNumber"),
            "cloud_cover": attrs.get("cloudCover"),
        }
        prev = scenes.get(key)
        if prev is not None:
            if scene["cloud_cover"] is not None and prev["cloud_cover"] is not None:
                scene["cloud_cover"] = prev["cloud_cover"] = max(prev["cloud_cover"], scene["cloud_cover"])
            if not prev["name"].endswith("_COG.SAFE") or scene["name"].endswith("_COG.SAFE"):
                continue
        scenes[key] = scene
    return [s for s in scenes.values()
            if max_cloud is None or (s["cloud_cover"] is not None and s["cloud_cover"] <= max_cloud)]


def print_scenes(title, scenes):
    print(f"\n{title}: {len(scenes)} scene(s)")
    for i, s in enumerate(scenes):
        extra = f"cloud {s['cloud_cover']:.0f}% (worst tile)" if s["cloud_cover"] is not None else ""
        print(f"  [{i}] {s['start']:%Y-%m-%d %H:%M:%SZ}  {s['platform']}  "
              f"{s['orbit_direction'] or '':<10} rel.orbit {s['relative_orbit'] or '-':<4} {extra}")
        print(f"      {s['name']}")


# ---------------------------------------------------------------- fetch

def get_token():
    client_id = os.getenv("CDSE_CLIENT_ID")
    client_secret = os.getenv("CDSE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET are not set. Copy .env.example to .env and fill them in.")
    r = requests.post(TOKEN_URL, timeout=30, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    })
    if not r.ok:
        sys.exit(f"CDSE token request failed: HTTP {r.status_code}\n{r.text[:500]}")
    return r.json()["access_token"]


def grid(bbox, res_m=config.RES_M):
    """Pixel grid (w, h) for bbox at res_m."""
    x0, y0, x1, y1 = bbox
    width_m = (x1 - x0) * 111_320 * math.cos(math.radians((y0 + y1) / 2))
    height_m = (y1 - y0) * 110_540
    w, h = round(width_m / res_m), round(height_m / res_m)
    if h > MAX_PX:
        sys.exit(f"Area is {h} px tall at {res_m} m; the Process API allows {MAX_PX}. Use a smaller --bbox.")
    return w, h


def process(token, bbox, data, evalscript, w, h):
    body = {
        "input": {
            "bounds": {"bbox": list(bbox), "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
            "data": [data],
        },
        "output": {"width": w, "height": h,
                   "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": evalscript,
    }
    r = requests.post(PROCESS_URL, json=body, timeout=300,
                      headers={"Authorization": f"Bearer {token}"})
    if not r.ok:
        sys.exit(f"Process API request failed: HTTP {r.status_code}\n{r.text[:500]}")
    pu = r.headers.get("x-processingunits-spent")
    return np.asarray(Image.open(BytesIO(r.content))), float(pu) if pu is not None else None


def fetch_tiled(token, bbox, data, evalscript):
    """Fetch bbox at config.RES_M as column tiles of at most MAX_PX width, stitched."""
    x0, y0, x1, y1 = bbox
    w, h = grid(bbox)
    n = math.ceil(w / MAX_PX)
    edges = [round(i * w / n) for i in range(n + 1)]
    dlon = (x1 - x0) / w
    tiles, spent = [], []
    for c0, c1 in zip(edges[:-1], edges[1:]):
        tile_bbox = (x0 + c0 * dlon, y0, x0 + c1 * dlon, y1)
        arr, pu = process(token, tile_bbox, data, evalscript, c1 - c0, h)
        tiles.append(arr)
        if pu is not None:
            spent.append(pu)
    print(f"  {n} tile(s), {sum(spent):.1f} processing units spent")
    return np.hstack(tiles)


def scene_window(scene, after=timedelta(minutes=1)):
    # Sentinel-2 OData times are the datatake start; the tile is sensed 9-17 min later
    pad = timedelta(minutes=1)
    return {"from": (scene["start"] - pad).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": (scene["end"] + after).strftime("%Y-%m-%dT%H:%M:%SZ")}


def fetch_s1_db(token, scene, bbox):
    data = {
        "type": "sentinel-1-grd",
        "dataFilter": {"timeRange": scene_window(scene), "acquisitionMode": "IW", "resolution": "HIGH"},
        "processing": {"backCoeff": "SIGMA0_ELLIPSOID", "orthorectify": True, "demInstance": "COPERNICUS_30"},
    }
    raw = fetch_tiled(token, bbox, data, S1_EVALSCRIPT).astype(np.float64)
    db = raw / DB_SCALE - DB_OFFSET
    db[raw == NODATA] = np.nan
    return db


def fetch_reference(token, bbox, out_dir):
    """Static reference: per-pixel percentile of VV dB over the reference period, cached on disk."""
    x0, y0, x1, y1 = bbox
    path = out_dir / (f"reference_{x0}_{y0}_{x1}_{y1}_{config.REFERENCE_FROM[:10]}_{config.REFERENCE_TO[:10]}"
                      f"_p{config.REFERENCE_PCT}_{config.RES_M}m.npy")
    if path.exists():
        print(f"Loaded cached reference {path}")
        return np.load(path)
    print(f"Fetching reference (p{config.REFERENCE_PCT}, {config.REFERENCE_FROM[:10]} to "
          f"{config.REFERENCE_TO[:10]}); this takes about 1.5 minutes")
    data = {
        "type": "sentinel-1-grd",
        "dataFilter": {"timeRange": {"from": config.REFERENCE_FROM, "to": config.REFERENCE_TO},
                       "acquisitionMode": "IW", "resolution": "HIGH", "orbitDirection": config.ORBIT_DIRECTION},
        "processing": {"backCoeff": "SIGMA0_ELLIPSOID", "orthorectify": True, "demInstance": "COPERNICUS_30"},
    }
    raw = fetch_tiled(token, bbox, data, REF_EVALSCRIPT).astype(np.float64)
    ref = raw / DB_SCALE - DB_OFFSET
    ref[raw == NODATA] = np.nan
    np.save(path, ref)
    print(f"Saved {path}")
    return ref


def fetch_s2_truecolor(token, scene, bbox, max_cloud):
    data = {
        "type": "sentinel-2-l2a",
        "dataFilter": {"timeRange": scene_window(scene, after=timedelta(minutes=60)),
                       "maxCloudCoverage": max_cloud, "mosaickingOrder": "leastCC"},
    }
    arr = fetch_tiled(token, bbox, data, S2_EVALSCRIPT)
    coverage = float((arr[..., 3] > 0).mean())
    if coverage == 0:
        sys.exit(f"Sentinel Hub returned no Sentinel-2 data for {scene['name']}.")
    if coverage < 0.5:
        print(f"WARNING: this Sentinel-2 image covers only {coverage:.0%} of the area.")
    return Image.fromarray(arr), coverage


# ---------------------------------------------------------------- detect

def disk(radius_px):
    r = int(math.ceil(radius_px))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= radius_px * radius_px


def detect_ships(db, ref, res_m=config.RES_M, ship_db=config.SHIP_DB, contrast_db=config.CONTRAST_DB,
                 water_db=config.WATER_DB, water_smooth_m=config.WATER_SMOOTH_M, min_water_km2=config.MIN_WATER_KM2,
                 merge_m=config.MERGE_M, split_m=config.SPLIT_M, min_area_m2=config.MIN_AREA_M2,
                 max_area_m2=config.MAX_AREA_M2):
    """Targets brighter than the static reference, on water. Returns (ships, water_mask)."""
    valid = np.isfinite(db) & np.isfinite(ref)
    # No-data is filled as land so it is never water and never a ship
    land = water_db + 10
    filled = np.where(valid, db, land)
    ref_filled = np.where(valid, ref, land)
    win = max(1, int(round(water_smooth_m / res_m)) | 1)
    water = valid & (ndimage.median_filter(ref_filled, size=win, mode="nearest") < water_db)
    labels, n = ndimage.label(water)
    if n:
        km2 = ndimage.sum(water, labels, np.arange(1, n + 1)) * res_m ** 2 / 1e6
        water = np.concatenate([[False], km2 >= min_water_km2])[labels]
    candidates = water & (filled > ship_db) & (filled - ref_filled > contrast_db)
    grown = ndimage.binary_dilation(candidates, structure=disk(merge_m / res_m)) if merge_m else candidates
    labels, n = ndimage.label(grown, structure=np.ones((3, 3)))
    labels = np.where(candidates, labels, 0)
    if n == 0:
        return [], water
    idx = np.arange(1, n + 1)
    areas = ndimage.sum(candidates, labels, idx) * res_m ** 2
    centres = ndimage.center_of_mass(candidates, labels, idx)
    peaks = ndimage.maximum(filled, labels, idx)
    ships = []
    objects = ndimage.find_objects(labels)
    for i, ((r, c), a, p) in enumerate(zip(centres, areas, peaks), start=1):
        if min_area_m2 <= a <= max_area_m2:
            ships.append({"row": r, "col": c, "area_m2": float(a), "peak_db": float(p)})
        elif a > max_area_m2 and objects[i - 1] is not None:
            # Merging can join separate ships into one oversize blob. Re-split it at hull scale
            # (fragments of one hull within ~2*SPLIT_M stay together) and judge each part on its own.
            sl = objects[i - 1]
            parts = labels[sl] == i
            sub, m = ndimage.label(ndimage.binary_dilation(parts, structure=disk(split_m / res_m)),
                                   structure=np.ones((3, 3)))
            sub = np.where(parts, sub, 0)
            sidx = np.arange(1, m + 1)
            for (sr, sc), sa, sp in zip(ndimage.center_of_mass(parts, sub, sidx),
                                        ndimage.sum(parts, sub, sidx) * res_m ** 2,
                                        ndimage.maximum(filled[sl], sub, sidx)):
                if min_area_m2 <= sa <= max_area_m2:
                    ships.append({"row": sr + sl[0].start, "col": sc + sl[1].start,
                                  "area_m2": float(sa), "peak_db": float(sp)})
    return ships, water


def pixel_to_lonlat(bbox, shape, row, col):
    x0, y0, x1, y1 = bbox
    h, w = shape
    return x0 + (col + 0.5) / w * (x1 - x0), y1 - (row + 0.5) / h * (y1 - y0)


def db_to_grey(db, lo=-25.0, hi=5.0):
    grey = np.clip((np.nan_to_num(db, nan=lo) - lo) / (hi - lo), 0, 1) * 255
    return Image.fromarray(grey.astype(np.uint8)).convert("RGB")


def draw_overlay(db, water, ships, res_m):
    img = db_to_grey(db)
    # Faint blue tint on what the detector treated as water
    tint = Image.new("RGB", img.size, (0, 90, 255))
    img = Image.composite(Image.blend(img, tint, 0.25), img,
                          Image.fromarray((water * 255).astype(np.uint8)))
    draw = ImageDraw.Draw(img)
    for s in ships:
        r = max(8, math.sqrt(s["area_m2"]) / res_m)
        draw.ellipse([s["col"] - r, s["row"] - r, s["col"] + r, s["row"] + r], outline=(255, 40, 40), width=2)
    return img


# ---------------------------------------------------------------- main

PASS_FIELDS = ["timestamp_utc", "image_id", "platform", "orbit_direction", "relative_orbit", "coverage", "ship_count"]
DETECTION_FIELDS = ["timestamp_utc", "image_id", "lon", "lat", "area_m2", "peak_db"]


def run_pass(token, scene, bbox, ref, out_dir):
    """Fetch one S1 pass, detect, save its overlay. Returns (pass_row, detection_rows, db, water, ships)."""
    stamp = f"{scene['start']:%Y%m%dT%H%M%SZ}"
    ts = scene["start"].strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\nFetching Sentinel-1 {scene['platform']} {scene['start']:%Y-%m-%d %H:%M:%SZ} at {config.RES_M} m")
    db = fetch_s1_db(token, scene, bbox)
    coverage = float(np.isfinite(db).mean())
    row = {"timestamp_utc": ts, "image_id": scene["image_id"], "platform": scene["platform"],
           "orbit_direction": scene["orbit_direction"], "relative_orbit": scene["relative_orbit"],
           "coverage": round(coverage, 3), "ship_count": None}
    if coverage == 0:
        print(f"No data for {scene['image_id']} (it may not be processed yet); ship_count left empty.")
        return row, [], db, None, []
    if coverage < 0.5:
        print(f"WARNING: this pass covers only {coverage:.0%} of the area; "
              "its ship count is not comparable to a full pass.")
    ships, water = detect_ships(db, ref)
    row["ship_count"] = len(ships)
    print(f"Coverage {coverage:.0%}, water {water.mean():.0%} of area, {len(ships)} ship-like target(s)")
    detections = []
    for s in ships:
        lon, lat = pixel_to_lonlat(bbox, db.shape, s["row"], s["col"])
        detections.append({"timestamp_utc": ts, "image_id": scene["image_id"], "lon": round(lon, 5),
                           "lat": round(lat, 5), "area_m2": round(s["area_m2"]), "peak_db": round(s["peak_db"], 1)})
    draw_overlay(db, water, ships, config.RES_M).save(out_dir / f"s1_{stamp}_ships.png")
    return row, detections, db, water, ships


def write_csv(path, fields, rows):
    # Written under a temporary name and renamed, so a crashed run never leaves a half file
    tmp = path.with_suffix(".partial.csv")
    with open(tmp, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def run_series(token, scenes, bbox, ref, out_dir):
    """Every pass in the window, oldest first: ship_counts.csv (one row per pass) + detections.csv."""
    passes, detections = [], []
    for scene in sorted(scenes, key=lambda s: s["start"]):
        row, dets, *_ = run_pass(token, scene, bbox, ref, out_dir)
        passes.append(row)
        detections.extend(dets)
    write_csv(out_dir / "ship_counts.csv", PASS_FIELDS, passes)
    write_csv(out_dir / "detections.csv", DETECTION_FIELDS, detections)
    with open(out_dir / "ship_counts_params.json", "w") as f:
        json.dump(config.detection_params(), f, indent=1)
    print(f"\nSaved {out_dir}/ship_counts.csv ({len(passes)} passes), detections.csv ({len(detections)} targets), "
          "ship_counts_params.json")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search-only", action="store_true", help="list scenes, no download (no credentials)")
    ap.add_argument("--days", type=int, default=30, help="search window in days (default 30)")
    ap.add_argument("--bbox", type=float, nargs=4, default=config.BBOX, metavar=("LON0", "LAT0", "LON1", "LAT1"))
    ap.add_argument("--max-cloud", type=float, default=30, help="Sentinel-2 cloud cover limit, %%")
    ap.add_argument("--scene", type=int, default=0, help="which Sentinel-1 scene to fetch, 0 = newest")
    ap.add_argument("--series", action="store_true",
                    help="process every Sentinel-1 pass in --days into ship_counts.csv (no Sentinel-2)")
    ap.add_argument("--out", type=Path, default=Path("output"))
    args = ap.parse_args()
    bbox = tuple(args.bbox)

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    s1 = search("SENTINEL-1", "IW_GRDH", bbox, since)
    # The reference is built from one orbit direction; other geometries would be compared against the wrong one
    skipped = [s for s in s1 if s["orbit_direction"] != config.ORBIT_DIRECTION]
    s1 = [s for s in s1 if s["orbit_direction"] == config.ORBIT_DIRECTION]
    s2 = search("SENTINEL-2", "MSIL2A", bbox, since, max_cloud=args.max_cloud)
    print(f"Area {bbox}, since {since:%Y-%m-%d}")
    print_scenes(f"Sentinel-1 IW GRD, {config.ORBIT_DIRECTION}", s1)
    if skipped:
        print_scenes(f"Skipped (not {config.ORBIT_DIRECTION}; the reference is {config.ORBIT_DIRECTION} only)", skipped)
    print_scenes(f"Sentinel-2 L2A (cloud <= {args.max_cloud:.0f}%)", s2)
    if args.search_only:
        return
    if not s1:
        sys.exit("No Sentinel-1 scenes in the search window; try a larger --days.")

    if not 0 <= args.scene < len(s1):
        sys.exit(f"--scene {args.scene} is out of range; found {len(s1)} Sentinel-1 scene(s) (0-{len(s1) - 1}).")

    token = get_token()
    args.out.mkdir(parents=True, exist_ok=True)
    ref = fetch_reference(token, bbox, args.out)
    if args.series:
        run_series(token, s1, bbox, ref, args.out)
        return

    scene = s1[args.scene]
    stamp = f"{scene['start']:%Y%m%dT%H%M%SZ}"
    row, detections, db, water, ships = run_pass(token, scene, bbox, ref, args.out)
    if row["ship_count"] is None:
        sys.exit(f"Sentinel Hub returned no data for {scene['image_id']}. "
                 f"Try --scene {args.scene + 1} for the previous pass.")
    db_to_grey(db).save(args.out / f"s1_{stamp}_vv.png")
    write_csv(args.out / f"s1_{stamp}_ships.csv", DETECTION_FIELDS, detections)
    with open(args.out / f"s1_{stamp}_params.json", "w") as f:
        json.dump({**config.detection_params(), **row}, f, indent=1)
    print(f"Saved {args.out}/s1_{stamp}_vv.png, _ships.png, _ships.csv, _params.json")

    if s2:
        scene = s2[0]
        stamp = f"{scene['start']:%Y%m%d}_{scene['platform']}"
        print(f"\nFetching Sentinel-2 {scene['platform']} {scene['start']:%Y-%m-%d} "
              f"(datatake start {scene['start']:%H:%M:%S}Z, cloud {scene['cloud_cover']:.0f}%)")
        img, s2_coverage = fetch_s2_truecolor(token, scene, bbox, args.max_cloud)
        img.save(args.out / f"s2_{stamp}_truecolor.png")
        print(f"Saved {args.out}/s2_{stamp}_truecolor.png (coverage {s2_coverage:.0%})")
    else:
        print("\nNo low-cloud Sentinel-2 scene in the window; skipping true colour.")


if __name__ == "__main__":
    main()
