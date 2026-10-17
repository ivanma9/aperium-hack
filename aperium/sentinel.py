"""Publish the latest Sentinel-1 radar pass per region as {region}/sentinel.json.

Reads passes already produced by copernicus_demo.py (sentinel_cache/ship_counts.csv and
s1_<stamp>_ships.png). `--refresh` re-runs copernicus_demo.py for the newest pass first
(needs CDSE_CLIENT_ID / CDSE_CLIENT_SECRET). Only Corpus Christi has a radar pipeline;
Hormuz gets image: null.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

import config
from aperium.contract import SCHEMA_VERSION, validate
from aperium.regions import REGIONS

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sentinel_cache"
MAX_IMAGE_PX = 1600
REVISIT_NOTE = "Sentinel-1 revisits Corpus Christi about every 12 days (relative orbit 107, ascending, ~00:34 UTC)."


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_pass(cache=CACHE):
    """Newest pass with a ship count and an overlay image, or None."""
    counts = cache / "ship_counts.csv"
    rows = list(csv.DictReader(counts.open())) if counts.exists() else []
    for params in sorted(cache.glob("s1_*_params.json")):  # single-pass runs may be newer than the series
        p = json.loads(params.read_text())
        rows.append({"timestamp_utc": p["timestamp_utc"], "platform": p["image_id"][:3], "ship_count": p.get("ship_count")})
    for row in sorted(rows, key=lambda r: r["timestamp_utc"], reverse=True):
        stamp = row["timestamp_utc"].replace("-", "").replace(":", "")
        image = cache / f"s1_{stamp}_ships.png"
        if image.exists():
            count = row.get("ship_count")
            return {"acquired_utc": row["timestamp_utc"], "satellite": row.get("platform") or None,
                    "image": image, "ship_count": int(count) if count not in (None, "") else None}
    return None


def build(region, out_dir, now=None):
    now = now or datetime.now(timezone.utc)
    doc = {"schema_version": SCHEMA_VERSION, "as_of_utc": iso(now), "calibrated": False,
           "region": region, "image": None, "next_pass_note": None}
    if region == "corpus_christi":
        found = latest_pass()
        if found:
            target = Path(region) / found["image"].name
            (out_dir / region).mkdir(parents=True, exist_ok=True)
            if not (out_dir / target).exists():
                with Image.open(found["image"]) as im:  # full-res overlays are ~9 MB; 1600 px is plenty for a map layer
                    im.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
                    im.save(out_dir / target, optimize=True)
            lon0, lat0, lon1, lat1 = config.BBOX
            doc["image"] = {"acquired_utc": found["acquired_utc"], "satellite": found["satellite"],
                            "image_path": target.as_posix(), "bbox": [[lat0, lon0], [lat1, lon1]],
                            "ship_count": found["ship_count"]}
        doc["next_pass_note"] = REVISIT_NOTE
    else:
        doc["next_pass_note"] = "No radar pipeline for this region yet."
    validate("sentinel", doc)
    return doc


def write(out_dir):
    out_dir = Path(out_dir)
    for region in REGIONS:
        doc = build(region, out_dir)
        path = out_dir / region / "sentinel.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2))
        os.replace(tmp, path)


def refresh():
    """Fetch and detect the newest pass; errors from the Copernicus APIs are shown verbatim."""
    subprocess.run([sys.executable, str(ROOT / "copernicus_demo.py"), "--out", str(CACHE)], cwd=ROOT, check=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("outputs/latest"))
    ap.add_argument("--refresh", action="store_true", help="run copernicus_demo.py for the newest pass first")
    args = ap.parse_args()
    if args.refresh:
        refresh()
    write(args.out)
    print((args.out / "corpus_christi" / "sentinel.json").read_text())
