"""Detection settings.

Tuned in Phase 2 against Sentinel-1 passes of 2026-09-23, 10-05 and 10-17 over
Corpus Christi (orbit 107 ascending), checked visually against overlays and a
Sentinel-2 image. VV sigma0 in dB throughout.
"""
import hashlib
import json

RES_M = 10                    # analysis grid (Sentinel-1 GRD native pixel)

# Static reference: per-(port, relative orbit) percentile of VV over earlier passes of
# that orbit. Moving ships vanish from it; docks, bridges, platforms stay.
# Ports can override the window in ports.yaml.
REFERENCE_FROM = "2026-03-22T00:00:00Z"
REFERENCE_TO = "2026-09-22T00:00:00Z"
REFERENCE_PCT = 25
MIN_REF_PASSES = 3            # fewer passes than this and a track is not counted
REFERENCE_FORMAT = 2          # bump when the arrays in a reference npz change; part of reference_id

WATER_DB = -18.0              # smoothed reference darker than this is water
WATER_SMOOTH_M = 50           # side of the square median window on the reference
MIN_WATER_KM2 = 0.1           # drop ponds and marsh pools smaller than this
SHIP_DB = -5.0                # a ship pixel must be brighter than this
CONTRAST_DB = 10.0            # ...and this far above the reference
MERGE_M = 60                  # dilation radius: candidates up to ~2*MERGE_M (~130 m) apart are one target
SPLIT_M = 20                  # oversize merged blobs are re-split at this radius (~one hull)
MIN_AREA_M2 = 1500            # smaller targets are small craft or speckle
MAX_AREA_M2 = 40_000

# QC columns (they do not change counts, but they change cal_proxy_db, so they are part of params_hash)
STABLE_MIN_DB = -5.0          # stable target for the calibration proxy: reference p25 above this...
STABLE_IQR_DB = 1.5           # ...and p75 - p25 below this
MIN_STABLE_PX = 100           # fewer stable pixels than this and cal_proxy_db is NaN

# Diagnostics (do not change counts, so not part of params_hash)
ABSORBED_DB = 10.0            # absorbed berth: water pixel with p25 > SHIP_DB and p25 - min above this
                              # (p25 - min alone flags speckle: 287,794 pixels on real open water)

DETECTION_KEYS = ("RES_M", "WATER_DB", "WATER_SMOOTH_M", "MIN_WATER_KM2", "SHIP_DB", "CONTRAST_DB",
                  "MERGE_M", "SPLIT_M", "MIN_AREA_M2", "MAX_AREA_M2", "STABLE_MIN_DB", "STABLE_IQR_DB",
                  "MIN_STABLE_PX")


def detection_params():
    """All settings that affect counts, for recording next to the results."""
    g = globals()
    return {k: g[k] for k in DETECTION_KEYS}


def params_hash(params=None):
    """First 12 hex chars of the sha256 of the sorted-key JSON of the detection parameters."""
    params = detection_params() if params is None else params
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
