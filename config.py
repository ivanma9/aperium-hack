"""Shared detection settings for copernicus_demo.py.

Tuned in Phase 2 against Sentinel-1 passes of 2026-09-23, 10-05 and 10-17 over
Corpus Christi (orbit 107 ascending), checked visually against overlays and a
Sentinel-2 image. VV sigma0 in dB throughout.
"""
# Corpus Christi ship channel, Ingleside terminals, Port Aransas inlet and the
# near-shore Gulf anchorage. lon_min, lat_min, lon_max, lat_max (WGS84).
BBOX = (-97.30, 27.75, -96.95, 27.90)
RES_M = 10                    # analysis grid (Sentinel-1 GRD native pixel)

# Static reference: per-pixel percentile of VV over earlier passes of the same
# orbit direction. Moving ships vanish from it; docks, bridges, platforms stay.
REFERENCE_FROM = "2026-03-22T00:00:00Z"
REFERENCE_TO = "2026-09-22T00:00:00Z"
REFERENCE_PCT = 25
ORBIT_DIRECTION = "ASCENDING"

WATER_DB = -18.0              # smoothed reference darker than this is water
WATER_SMOOTH_M = 50           # side of the square median window on the reference
MIN_WATER_KM2 = 0.1           # drop ponds and marsh pools smaller than this
SHIP_DB = -5.0                # a ship pixel must be brighter than this
CONTRAST_DB = 10.0            # ...and this far above the reference
MERGE_M = 60                  # dilation radius: candidates up to ~2*MERGE_M (~130 m) apart are one target
SPLIT_M = 20                  # oversize merged blobs are re-split at this radius (~one hull)
MIN_AREA_M2 = 1500            # smaller targets are small craft or speckle
MAX_AREA_M2 = 40_000


def detection_params():
    """All settings that affect counts, for recording next to the results."""
    return {k: v for k, v in globals().items() if k.isupper()}

