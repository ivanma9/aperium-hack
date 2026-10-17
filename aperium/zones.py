"""Zone geometry from zones.yaml: point-in-zone, gate crossings, GeoJSON, land mask, static map.

Run: uv run python -m aperium.zones --map outputs/zones_map.png
"""
import argparse

from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import unary_union
from shapely.prepared import prep

from aperium.regions import REGIONS

try:
    from global_land_mask import globe
except ImportError:  # land filtering is then disabled
    globe = None

NEAR_ZONE_DEG = 0.02  # ~2 km: treat as water so the 1 km land mask cannot drop berthed ships
AREA_KINDS = ("terminal", "anchorage")


def _xy(points):
    return [(lon, lat) for lat, lon in points]


def _load():
    zones = {}
    for rid, region in REGIONS.items():
        zones[rid] = {}
        for zid, z in region["zones"].items():
            geom = Polygon(_xy(z["polygon"])) if "polygon" in z else LineString(_xy(z["line"]))
            side = z.get("inbound_side")
            zones[rid][zid] = dict(id=zid, name=z["name"], kind=z["kind"], geom=geom, prepared=prep(geom),
                                   inbound=Point(side[1], side[0]) if side else None)
    return zones


ZONES = _load()
_NEAR = prep(unary_union([z["geom"].buffer(NEAR_ZONE_DEG) for r in ZONES.values() for z in r.values()]))


def zone_region(zone_id):
    return next((rid for rid, zs in ZONES.items() if zone_id in zs), None)


def zone_at(region, lat, lon):
    point = Point(lon, lat)
    for z in ZONES.get(region, {}).values():
        if z["kind"] in AREA_KINDS and z["prepared"].contains(point):
            return z["id"], z["kind"]
    return None, None


def _side(line, point):
    (x1, y1), (x2, y2) = line.coords[0], line.coords[-1]
    return 1 if (x2 - x1) * (point.y - y1) - (y2 - y1) * (point.x - x1) >= 0 else -1


def gate_crossing(region, prev_latlon, cur_latlon):
    """(zone_id, "inbound"|"outbound") if the segment prev->cur crosses a gate/boundary line."""
    if prev_latlon is None or prev_latlon == cur_latlon:
        return None
    prev, cur = Point(prev_latlon[1], prev_latlon[0]), Point(cur_latlon[1], cur_latlon[0])
    segment = LineString([prev, cur])
    for z in ZONES.get(region, {}).values():
        if z["kind"] in AREA_KINDS or not z["prepared"].intersects(segment):
            continue
        before, after = _side(z["geom"], prev), _side(z["geom"], cur)
        if before != after:
            return z["id"], "inbound" if after == _side(z["geom"], z["inbound"]) else "outbound"
    return None


def geojson(region):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(z["geom"]),
         "properties": {"id": z["id"], "name": z["name"], "kind": z["kind"]}}
        for z in ZONES[region].values()]}


def is_land(lat, lon):
    if globe is None or _NEAR.contains(Point(lon, lat)):
        return False
    return bool(globe.is_land(lat, lon))


def render_map(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    colors = {"terminal": "#d62728", "anchorage": "#1f77b4", "gate": "#2ca02c", "boundary": "#2ca02c"}
    fig, axes = plt.subplots(1, len(REGIONS), figsize=(7 * len(REGIONS), 7))
    for ax, (rid, region) in zip(axes, REGIONS.items()):
        (s, w), (n, e) = region["bbox"]
        if globe is not None:
            lats, lons = np.linspace(s, n, 400), np.linspace(w, e, 400)
            land = globe.is_land(*np.meshgrid(lats, lons, indexing="ij"))
            ax.imshow(land, extent=(w, e, s, n), origin="lower", cmap="Greys", alpha=0.35, aspect="auto")
        ax.plot([w, e, e, w, w], [s, s, n, n, s], "k--", lw=1)
        for z in ZONES[rid].values():
            c = colors[z["kind"]]
            if z["kind"] in AREA_KINDS:
                x, y = z["geom"].exterior.xy
                ax.fill(x, y, color=c, alpha=0.35)
                ax.plot(x, y, color=c)
            else:
                x, y = z["geom"].xy
                ax.plot(x, y, color=c, lw=2.5)
                ax.plot(z["inbound"].x, z["inbound"].y, "o", color=c, mfc="none")
            ax.annotate(f'{z["id"]}\n({z["kind"]})', (z["geom"].centroid.x, z["geom"].centroid.y),
                        fontsize=7, ha="center", va="center")
        ax.set_xlim(w, e), ax.set_ylim(s, n)
        ax.set_title(f'{region["name"]} (circle = inbound side)')
        ax.set_xlabel("lon"), ax.set_ylabel("lat")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="output PNG path")
    args = ap.parse_args()
    from pathlib import Path
    Path(args.map).parent.mkdir(parents=True, exist_ok=True)
    render_map(args.map)
    print(f"wrote {args.map}; land mask {'on' if globe else 'off'}")
