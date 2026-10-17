"""Static reference per (port, relative orbit), built locally from cached passes."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import config
from .copernicus import atomic_savez, decode_db
from .detect import db_to_grey, water_mask
from .fsutil import atomic_path


def _percentiles(stack, pcts):
    """{pct: percentile} and the minimum and sample count of a (n, h, w) dB stack, NaN for no-data.
    Index rule per pixel: sort the valid samples (NaN sorts last), take v[floor(pct/100*(n-1))]."""
    stack = np.asarray(stack)
    n = np.isfinite(stack).sum(axis=0)
    srt = np.sort(stack, axis=0)
    thin = n < config.MIN_REF_PASSES
    out = {}
    for pct in pcts:
        idx = np.clip(np.floor(pct / 100 * (n - 1)), 0, None).astype(np.intp)
        p = np.take_along_axis(srt, idx[None], axis=0)[0]
        p[thin] = np.nan
        out[pct] = p
    mn = srt[0].copy()
    mn[thin] = np.nan
    return out, mn, n.astype(np.int16)


def percentile_stack(stack, pct):
    """Per-pixel percentile of a (n, h, w) dB stack with NaN for no-data.

    Same index rule as the Phase 2 evalscript: sort the valid samples, take v[floor(pct/100*(n-1))],
    NaN when fewer than MIN_REF_PASSES are valid. Returns (percentile, minimum, n_samples).
    """
    out, mn, n = _percentiles(stack, [pct])
    return out[pct], mn, n


CHUNK_ROWS = 200


def build_reference(raws, pct=config.REFERENCE_PCT, chunk_rows=CHUNK_ROWS):
    """raws: list of 2-D uint16 rasters (one per pass, as cached). Returns the arrays that make up a
    reference: p25, p50, p75 (and p{pct} when pct is another), min and n_samples.

    Works in bands of chunk_rows rows, decoding each band on its own, so the float stack never exists in full:
    15 passes of a 3446 x 1658 px box would be ~340 MB as float32 plus the sorted copy.
    """
    pcts = sorted({pct, 25, 50, 75})
    h, w = raws[0].shape
    out = {f"p{q}": np.empty((h, w), np.float32) for q in pcts}
    out["min"] = np.empty((h, w), np.float32)
    out["n_samples"] = np.empty((h, w), np.int16)
    for r0 in range(0, h, chunk_rows):
        band = slice(r0, min(r0 + chunk_rows, h))
        ps, mn, n = _percentiles(np.stack([decode_db(r[band]) for r in raws]), pcts)
        for q in pcts:
            out[f"p{q}"][band] = ps[q]
        out["min"][band], out["n_samples"][band] = mn, n
    return out


def compute_reference_id(gid, relative_orbit, ref_from, ref_to, pct, image_ids, exclude=()):
    """Identifies a reference and everything computed against it: the grid, the track, the window, the
    passes that went in, the exclusion boxes, and the format of the arrays and the pass minimum."""
    blob = json.dumps({"grid_id": gid, "orbit": int(relative_orbit), "from": ref_from, "to": ref_to,
                       "pct": pct, "image_ids": sorted(image_ids),
                       "exclude": sorted([float(v) for v in box] for box in exclude),
                       "min_ref_passes": config.MIN_REF_PASSES, "format": config.REFERENCE_FORMAT}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def reference_path(data_dir, port, gid, rid):
    return Path(data_dir) / "cache" / port / gid / f"reference_{rid}.npz"


def save_reference(path, ref):
    atomic_savez(path, **ref)


def load_reference(path):
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def absorbed_berths(ref_p, ref_min, thresh_db=config.ABSORBED_DB):
    """Water pixels that are ship-bright in the percentile reference (> SHIP_DB) and more than
    thresh_db above the min: a ship was present often enough to be absorbed into the reference.
    The water mask comes from the *min* reference, because the p25 mask excludes absorbed berths by
    construction. p25 - min alone is not enough: speckle puts the min of ~15 passes >10 dB under p25
    on most open water. Returns (mask, n_pixels)."""
    with np.errstate(invalid="ignore"):
        mask = water_mask(ref_min) & (ref_p > config.SHIP_DB) & ((ref_p - ref_min) > thresh_db)
    return mask, int(mask.sum())


def blob_stats(mask, res_m=config.RES_M):
    """(number of 8-connected blobs, area in m2 of the largest) of a boolean mask."""
    labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if not n:
        return 0, 0.0
    return int(n), float(np.bincount(labels.ravel())[1:].max() * res_m ** 2)


def save_absorbed_map(path, ref_p, mask):
    img = db_to_grey(ref_p)
    arr = np.asarray(img).copy()
    arr[mask] = (255, 40, 40)
    with atomic_path(path) as tmp:
        Image.fromarray(arr).save(tmp, format="PNG")
