"""Sentinel-1 detection settings for copernicus_demo.py / gee_demo.py.

Values restored from sentinel_cache/*_params.json (the settings the cached passes were made with).
"""
BBOX = [-97.3, 27.75, -96.95, 27.9]          # lon0, lat0, lon1, lat1 (Corpus Christi)
RES_M = 10
REFERENCE_FROM = "2026-03-22T00:00:00Z"
REFERENCE_TO = "2026-09-22T00:00:00Z"
REFERENCE_PCT = 25
ORBIT_DIRECTION = "ASCENDING"
WATER_DB = -18.0
WATER_SMOOTH_M = 50
MIN_WATER_KM2 = 0.1
SHIP_DB = -5.0
CONTRAST_DB = 10.0
MERGE_M = 60
MIN_AREA_M2 = 1500
MAX_AREA_M2 = 40000
