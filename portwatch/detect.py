"""Ship detection against a static reference (Phase 2 logic), plus per-target geometry and QC."""
import logging
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from . import config

log = logging.getLogger("portwatch.detect")
EIGHT = np.ones((3, 3))


@dataclass
class Detection:
    ships: list                 # dicts: row, col, area_m2, peak_db, length_m, width_m, orientation_deg, n_parts
    water: np.ndarray           # static water mask (from the reference alone)
    valid: np.ndarray           # pixels where both the pass and the reference are finite
    n_rejected_large: int       # blobs over MAX_AREA_M2 (including re-split parts) that were dropped


def disk(radius_px):
    r = int(math.ceil(radius_px))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= radius_px * radius_px


def water_mask(ref, res_m=None, water_db=None, water_smooth_m=None, min_water_km2=None):
    """Water from a reference image alone: smoothed reference darker than water_db, in bodies of at
    least min_water_km2. No-data in the reference is filled as land, so it is never water.
    Settings left as None are read from config at call time."""
    res_m = config.RES_M if res_m is None else res_m
    water_db = config.WATER_DB if water_db is None else water_db
    water_smooth_m = config.WATER_SMOOTH_M if water_smooth_m is None else water_smooth_m
    min_water_km2 = config.MIN_WATER_KM2 if min_water_km2 is None else min_water_km2
    valid = np.isfinite(ref)
    filled = np.where(valid, ref, water_db + 10)
    win = max(1, int(round(water_smooth_m / res_m)) | 1)
    water = valid & (ndimage.median_filter(filled, size=win, mode="nearest") < water_db)
    labels, n = ndimage.label(water)
    if n:
        km2 = ndimage.sum(water, labels, np.arange(1, n + 1)) * res_m ** 2 / 1e6
        water = np.concatenate([[False], km2 >= min_water_km2])[labels]
    return water


def apply_exclusions(water, bbox, boxes):
    """Copy of the water mask with every pixel whose centre lies inside one of `boxes`
    (lon0, lat0, lon1, lat1) set to False. Pixel centres follow pixel_to_lonlat; row 0 is the north edge."""
    water = water.copy()
    x0, y0, x1, y1 = bbox
    h, w = water.shape
    lons = x0 + (np.arange(w) + 0.5) / w * (x1 - x0)          # the same formulas as pixel_to_lonlat
    lats = y1 - (np.arange(h) + 0.5) / h * (y1 - y0)
    for lon0, lat0, lon1, lat1 in boxes:
        water[np.ix_((lats >= lat0) & (lats <= lat1), (lons >= lon0) & (lons <= lon1))] = False
    return water


def _geometry(mask, res_m, split_m):
    """Second-moment length/width (metres) and orientation (compass bearing of the long axis, [0, 180))
    of a boolean blob, plus its number of hull-scale parts."""
    rows, cols = np.nonzero(mask)
    x, y = cols.astype(float), -rows.astype(float)          # x east, y north
    cov = np.cov(np.vstack([x, y]), bias=True) if len(x) > 1 else np.zeros((2, 2))
    cov = cov + np.eye(2) / 12.0                             # a pixel is a unit square, not a point
    evals, evecs = np.linalg.eigh(cov)
    vx, vy = evecs[:, 1]
    n_parts = ndimage.label(ndimage.binary_dilation(mask, structure=disk(split_m / res_m)) if split_m else mask,
                            structure=EIGHT)[1]
    return {"length_m": float(math.sqrt(12 * max(evals[1], 0)) * res_m),
            "width_m": float(math.sqrt(12 * max(evals[0], 0)) * res_m),
            "orientation_deg": float(math.degrees(math.atan2(vx, vy)) % 180.0),
            "n_parts": int(n_parts)}


def _ship(mask, offset, filled, res_m, split_m):
    """Target record for a boolean blob located at `offset` (row0, col0) of the full image."""
    rows, cols = np.nonzero(mask)
    peak = filled[rows + offset[0], cols + offset[1]].max()
    return {"row": float(rows.mean() + offset[0]), "col": float(cols.mean() + offset[1]),
            "area_m2": float(mask.sum() * res_m ** 2), "peak_db": float(peak), **_geometry(mask, res_m, split_m)}


def detect_ships(db, ref, water=None, res_m=config.RES_M, ship_db=config.SHIP_DB, contrast_db=config.CONTRAST_DB,
                 water_db=config.WATER_DB, water_smooth_m=config.WATER_SMOOTH_M, min_water_km2=config.MIN_WATER_KM2,
                 merge_m=config.MERGE_M, split_m=config.SPLIT_M, min_area_m2=config.MIN_AREA_M2,
                 max_area_m2=config.MAX_AREA_M2):
    """Targets brighter than the static reference, on water.

    `water` is the static mask for this reference (built from `ref` when not given). Pixels where the
    pass or the reference is NaN are never candidates. Returns a Detection.
    """
    if water is None:
        water = water_mask(ref, res_m, water_db, water_smooth_m, min_water_km2)
    valid = np.isfinite(db) & np.isfinite(ref)
    land = water_db + 10                                  # no-data is filled as land
    filled = np.where(valid, db, land)
    ref_filled = np.where(valid, ref, land)
    candidates = water & valid & (filled > ship_db) & (filled - ref_filled > contrast_db)
    grown = ndimage.binary_dilation(candidates, structure=disk(merge_m / res_m)) if merge_m else candidates
    labels, n = ndimage.label(grown, structure=EIGHT)
    labels = np.where(candidates, labels, 0)
    ships, rejected = [], 0
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        mask = labels[sl] == i
        area = mask.sum() * res_m ** 2
        offset = (sl[0].start, sl[1].start)
        if min_area_m2 <= area <= max_area_m2:
            ships.append(_ship(mask, offset, filled, res_m, split_m))
        elif area > max_area_m2 and split_m:
            # Merging can join separate ships into one oversize blob. Re-split it at hull scale
            # (fragments of one hull within ~2*SPLIT_M stay together) and judge each part on its own.
            sub, m = ndimage.label(ndimage.binary_dilation(mask, structure=disk(split_m / res_m)), structure=EIGHT)
            sub = np.where(mask, sub, 0)
            kept = lost = 0
            for j in range(1, m + 1):
                part = sub == j
                part_area = part.sum() * res_m ** 2
                if min_area_m2 <= part_area <= max_area_m2:
                    ships.append(_ship(part, offset, filled, res_m, split_m))
                    kept += 1
                elif part_area > max_area_m2:
                    lost += 1
            rejected += lost
            log.info("fallback: blob of %.0f m2 at row %d col %d split into %d part(s), kept %d, rejected %d oversize",
                     area, offset[0], offset[1], m, kept, lost)
        elif area > max_area_m2:
            rejected += 1
    return Detection(ships, water, valid, rejected)


def qc_columns(db, stats, water):
    """(cal_proxy_db, sea_state_db): median of db - p50 over stable targets (reference p25 above
    STABLE_MIN_DB and p75 - p25 below STABLE_IQR_DB, not water) and over water.

    Stable targets are bright, steady scatterers (dock steel, roofs, tank farms): their return does not
    depend on the weather, so a shift in them is the instrument. Measured against the median, not
    the p25 that the detector uses, so the speckle in the reference does not bias it. `stats` is a mapping with
    the reference's p25, p50 and p75. cal_proxy_db is NaN with fewer than MIN_STABLE_PX such pixels,
    sea_state_db with no water pixels."""
    p25, p50, p75 = stats["p25"], stats["p50"], stats["p75"]
    valid = np.isfinite(db) & np.isfinite(p25) & np.isfinite(p50) & np.isfinite(p75)
    diff = db - p50
    with np.errstate(invalid="ignore"):
        stable = valid & ~water & (p25 > config.STABLE_MIN_DB) & ((p75 - p25) < config.STABLE_IQR_DB)
    sea = valid & water
    return (float(np.median(diff[stable])) if stable.sum() >= config.MIN_STABLE_PX else float("nan"),
            float(np.median(diff[sea])) if sea.any() else float("nan"))


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
    img = Image.composite(Image.blend(img, tint, 0.25), img, Image.fromarray((water * 255).astype(np.uint8)))
    draw = ImageDraw.Draw(img)
    for s in ships:
        r = max(8, math.sqrt(s["area_m2"]) / res_m)
        draw.ellipse([s["col"] - r, s["row"] - r, s["col"] + r, s["row"] + r], outline=(255, 40, 40), width=2)
    return img
