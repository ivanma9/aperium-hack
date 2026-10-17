"""Monitor regions loaded from zones.yaml; bboxes are [[lat_sw, lon_sw], [lat_ne, lon_ne]]."""
from pathlib import Path

import yaml

ZONES_FILE = Path(__file__).resolve().parent.parent / "zones.yaml"
REGIONS = yaml.safe_load(ZONES_FILE.read_text())["regions"]


def region_of(lat, lon):
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    for rid, r in REGIONS.items():
        (s, w), (n, e) = r["bbox"]
        if s <= lat <= n and w <= lon <= e:
            return rid
    return None
