#!/usr/bin/env python3
"""Tanker activity at Corpus Christi from Google Earth Engine.

Counts ship-like targets on every Sentinel-1 pass over the last N months,
server side: pixels on water that are much brighter than a static reference
(per-pixel 25th percentile of VV over earlier ascending passes, where moving
ships vanish but docks and platforms stay), merged and size filtered. Settings
are in config.py. Writes one row per Sentinel-1 image
(GRD slice; one per pass for this bbox) to ship_counts.csv with the real
acquisition time in UTC. Also saves an overlay image for the newest pass.
Needs EE_PROJECT in .env and a prior `earthengine authenticate`.
"""
import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ee
import numpy as np
from dotenv import load_dotenv
from PIL import Image, ImageDraw

import config

load_dotenv()

OVERLAY_MAX_PX = 2500


def init_ee():
    project = os.getenv("EE_PROJECT")
    if not project:
        sys.exit("EE_PROJECT is not set. Copy .env.example to .env and fill it in.")
    try:
        ee.Initialize(project=project)
    except Exception as e:
        sys.exit(f"Earth Engine initialisation failed:\n{e}\n"
                 "Run `earthengine authenticate` and check EE_PROJECT is registered for Earth Engine.")


def s1_collection(region, start, end):
    return (ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(region)
            .filterDate(ee.Date(int(start.timestamp() * 1000)), ee.Date(int(end.timestamp() * 1000)))
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .filter(ee.Filter.eq("orbitProperties_pass", config.ORBIT_DIRECTION))
            .select("VV")
            .sort("system:time_start"))


def parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def reference(region):
    """Static reference: per-pixel percentile of VV over the reference period."""
    return (s1_collection(region, parse(config.REFERENCE_FROM), parse(config.REFERENCE_TO))
            .reduce(ee.Reducer.percentile([config.REFERENCE_PCT])).rename("ref"))


def water_mask(ref):
    min_px = round(config.MIN_WATER_KM2 * 1e6 / config.RES_M ** 2)  # 1000
    assert min_px <= 1024  # connectedPixelCount limit
    water = ref.focalMedian(radius=config.WATER_SMOOTH_M / 2, kernelType="square", units="meters").lt(config.WATER_DB).selfMask()
    return water.updateMask(water.connectedPixelCount(maxSize=1024, eightConnected=False).gte(min_px))


def ship_targets(img, ref, water, region, proj):
    """Centroids of merged targets; `sum` is the candidate-pixel count of each."""
    vv = img.select("VV")
    cand = vv.gt(config.SHIP_DB).And(vv.subtract(ref).gt(config.CONTRAST_DB)).And(water).selfMask()
    merged = cand.unmask(0).focalMax(radius=config.MERGE_M, kernelType="circle", units="meters").selfMask()
    min_px = math.ceil(config.MIN_AREA_M2 / config.RES_M ** 2)
    max_px = math.floor(config.MAX_AREA_M2 / config.RES_M ** 2)
    vec = merged.toInt().rename("blob").addBands(cand.unmask(0).toInt().rename("n")).reduceToVectors(
        reducer=ee.Reducer.sum(), geometry=region, crs=proj, scale=config.RES_M, geometryType="centroid",
        eightConnected=True, maxPixels=1e9, tileScale=4)
    return vec.filter(ee.Filter.And(ee.Filter.gte("sum", min_px), ee.Filter.lte("sum", max_px)))


def coverage(img, region, proj):
    """Fraction of the area this pass actually imaged."""
    return (img.select("VV").mask().unmask(0, False)
            .reduceRegion(ee.Reducer.mean(), region, scale=100, crs=proj)
            .get("VV"))


def fetch_overlay(img, ref, water, bbox, centroids):
    x0, y0, x1, y1 = bbox
    width_m = (x1 - x0) * 111_320 * math.cos(math.radians((y0 + y1) / 2))
    height_m = (y1 - y0) * 110_540
    res = max(config.RES_M, max(width_m, height_m) / OVERLAY_MAX_PX)
    w, h = round(width_m / res), round(height_m / res)

    stack = ee.Image.cat([
        img.select("VV").unmask(-99, False).toFloat().rename("VV"),
        water.unmask(0, False).toByte().rename("water"),
    ])
    arr = ee.data.computePixels({
        "expression": stack,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": w, "height": h},
            "affineTransform": {"scaleX": (x1 - x0) / w, "shearX": 0, "translateX": x0,
                                "shearY": 0, "scaleY": -(y1 - y0) / h, "translateY": y1},
            "crsCode": "EPSG:4326",
        },
    })
    db = np.where(arr["VV"] <= -98, np.nan, arr["VV"].astype(np.float64))
    water = arr["water"].astype(bool)

    grey = np.clip((np.nan_to_num(db, nan=-25.0) + 25.0) / 30.0, 0, 1) * 255
    out = Image.fromarray(grey.astype(np.uint8)).convert("RGB")
    tint = Image.new("RGB", out.size, (0, 90, 255))
    out = Image.composite(Image.blend(out, tint, 0.25), out,
                          Image.fromarray((water * 255).astype(np.uint8)))
    draw = ImageDraw.Draw(out)
    for lon, lat in centroids:
        c = (lon - x0) / (x1 - x0) * w
        r = (y1 - lat) / (y1 - y0) * h
        draw.ellipse([c - 8, r - 8, c + 8, r + 8], outline=(255, 40, 40), width=2)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=int, default=6, help="history to scan (default 6)")
    ap.add_argument("--bbox", type=float, nargs=4, default=config.BBOX, metavar=("LON0", "LAT0", "LON1", "LAT1"))
    ap.add_argument("--out", type=Path, default=Path("output_gee"))
    ap.add_argument("--no-overlay", action="store_true", help="skip the newest-pass overlay image")
    args = ap.parse_args()
    bbox = tuple(args.bbox)

    init_ee()
    region = ee.Geometry.Rectangle(list(bbox))
    proj = f"EPSG:{config.utm_epsg(bbox)}"
    ref = reference(region)
    water = water_mask(ref)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=round(args.months * 30.44))
    coll = s1_collection(region, start, end)

    feats = ee.FeatureCollection(coll.map(lambda im: ee.Feature(None, {
        "id": im.get("system:index"),
        "time": im.get("system:time_start"),
        "platform": im.get("platform_number"),
        "pass": im.get("orbitProperties_pass"),
        "orbit": im.get("relativeOrbitNumber_start"),
    }))).getInfo()["features"]
    n = len(feats)
    print(f"Area {bbox}, {start:%Y-%m-%d} to {end:%Y-%m-%d}: {n} Sentinel-1 image(s)")
    if n == 0:
        sys.exit("No Sentinel-1 passes found.")

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "ship_counts.csv"
    # Rows are flushed as they arrive; the file only gets its final name once every pass is done
    partial_path = args.out / "ship_counts.partial.csv"
    with open(args.out / "ship_counts_params.json", "w") as f:
        json.dump(config.detection_params(), f, indent=1)
    fields = ["timestamp_utc", "image_id", "platform", "orbit_pass", "relative_orbit", "coverage", "ship_count"]
    with open(partial_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i, feat in enumerate(feats):
            p = feat["properties"]
            image_id = p.get("id")
            img = ee.Image(f"COPERNICUS/S1_GRD/{image_id}").select("VV")
            ts = datetime.fromtimestamp(p.get("time") / 1000, tz=timezone.utc)
            res = ee.Dictionary({
                "ship_count": ship_targets(img, ref, water, region, proj).size(),
                "coverage": coverage(img, region, proj),
            }).getInfo()
            row = {
                "timestamp_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "image_id": image_id,
                "platform": f"S1{p.get('platform') or '?'}",
                "orbit_pass": p.get("pass"),
                "relative_orbit": p.get("orbit"),
                "coverage": round(res["coverage"] or 0.0, 3),
                "ship_count": res["ship_count"],
            }
            writer.writerow(row)
            f.flush()
            print(f"  [{i + 1}/{n}] {row['timestamp_utc']}  {row['platform']}  {row['orbit_pass'] or '-':<10} "
                  f"orbit {row['relative_orbit'] or '-':<4} coverage {row['coverage']:.0%}  ships {row['ship_count']}")
    partial_path.replace(csv_path)
    print(f"Saved {csv_path}")

    if not args.no_overlay:
        newest = row
        img = ee.Image(f"COPERNICUS/S1_GRD/{newest['image_id']}").select("VV")
        feats = ship_targets(img, ref, water, region, proj).getInfo()["features"]
        centroids = [tuple(f["geometry"]["coordinates"]) for f in feats]
        stamp = newest["timestamp_utc"].replace("-", "").replace(":", "")
        path = args.out / f"s1_{stamp}_ships.png"
        fetch_overlay(img, ref, water, bbox, centroids).save(path)
        print(f"Saved {path} ({len(centroids)} targets)")


if __name__ == "__main__":
    main()
