"""Copernicus Data Space: catalogue search, token, tiled Process API fetch, on-disk pass cache."""
import hashlib
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from . import config
from .fsutil import atomic_path

log = logging.getLogger("portwatch.copernicus")

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

MAX_PX = 2500         # Process API limit per side
NODATA = 0            # UINT16 code for no data
DB_OFFSET, DB_SCALE = 50.0, 500.0  # dB = value / DB_SCALE - DB_OFFSET, covers -50 to ~+81 dB
TOKEN_MARGIN_S = 60   # refresh the token when fewer than this many seconds remain

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

# The request body minus the time range, which is per pass.
S1_DATA_TEMPLATE = {
    "type": "sentinel-1-grd",
    "dataFilter": {"acquisitionMode": "IW", "resolution": "HIGH", "polarization": "DV"},
    "processing": {"backCoeff": "SIGMA0_ELLIPSOID", "orthorectify": True, "demInstance": "COPERNICUS_30"},
}


class CopernicusError(RuntimeError):
    pass


class CacheMismatchError(CopernicusError):
    """A cached raster does not match the grid it is being used for."""


class UnexpectedResponseError(CopernicusError):
    """The service answered, but not with what the API documents (missing field, wrong tile shape...)."""


# ---------------------------------------------------------------- search

def _field(response, name, what):
    """response.json()[name], or an UnexpectedResponseError that says what was missing from what."""
    try:
        body = response.json()
    except ValueError as e:
        raise UnexpectedResponseError(f"{what}: response is not JSON ({e}); starts with {response.text[:200]!r}") from e
    if not isinstance(body, dict) or name not in body:
        shown = sorted(body) if isinstance(body, dict) else type(body).__name__
        raise UnexpectedResponseError(f"{what}: response has no {name!r} field (got {shown})")
    return body[name]


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


def search(collection, name_contains, bbox, since, until=None, max_cloud=None, page_size=200, get=requests.get):
    """Scenes intersecting bbox since `since`, newest first, one per acquisition.

    Pages with $skip until the catalogue returns a short page, so long windows are never truncated.
    One acquisition can appear several times: S1 as SAFE and COG copies, S2 as one product per
    tile. S1 keeps the SAFE copy; cloud cover is the worst tile.
    """
    filters = [
        f"Collection/Name eq '{collection}'",
        f"contains(Name,'{name_contains}')",
        f"OData.CSC.Intersects(area=geography'SRID=4326;{bbox_wkt(bbox)}')",
        f"ContentDate/Start gt {since:%Y-%m-%dT%H:%M:%S.000Z}",
    ]
    if until is not None:
        filters.append(f"ContentDate/Start lt {until:%Y-%m-%dT%H:%M:%S.000Z}")
    value, skip = [], 0
    while True:
        params = {"$filter": " and ".join(filters), "$orderby": "ContentDate/Start desc,Name asc",
                  "$top": page_size, "$skip": skip, "$expand": "Attributes"}
        r = get(CATALOGUE_URL, params=params, timeout=60)
        if not r.ok:
            raise CopernicusError(f"Catalogue search failed: HTTP {r.status_code}\n{r.text[:500]}")
        page = _field(r, "value", "Catalogue search")
        value.extend(page)
        if len(page) < page_size:
            break
        skip += page_size

    scenes = {}
    for p in value:
        start = parse_time(p["ContentDate"]["Start"])
        key = (p["Name"][:3], start.replace(microsecond=0))
        attrs = {a["Name"]: a["Value"] for a in p.get("Attributes", [])}
        orbit = attrs.get("relativeOrbitNumber")
        scene = {
            "name": p["Name"],
            "image_id": image_id_from_name(p["Name"]),
            "platform": p["Name"][:3],
            "start": start,
            "end": parse_time(p["ContentDate"]["End"]),
            "orbit_direction": attrs.get("orbitDirection"),
            "relative_orbit": int(orbit) if orbit is not None else None,
            "cloud_cover": attrs.get("cloudCover"),
        }
        prev = scenes.get(key)
        if prev is not None:
            if scene["cloud_cover"] is not None and prev["cloud_cover"] is not None:
                scene["cloud_cover"] = prev["cloud_cover"] = max(prev["cloud_cover"], scene["cloud_cover"])
            if not prev["name"].endswith("_COG.SAFE") or scene["name"].endswith("_COG.SAFE"):
                continue
        scenes[key] = scene
    out = [s for s in scenes.values() if max_cloud is None or (s["cloud_cover"] is not None and s["cloud_cover"] <= max_cloud)]
    return sorted(out, key=lambda s: s["start"], reverse=True)


def search_s1(bbox, since, until=None, **kw):
    # 1SDV = dual-pol VV+VH, matching "polarization": "DV" in the fetch request
    return search("SENTINEL-1", "IW_GRDH_1SDV", bbox, since, until=until, **kw)


# ---------------------------------------------------------------- token

class TokenSource:
    """OAuth client-credentials token, refreshed when fewer than 60 s of expires_in remain."""

    def __init__(self, client_id, client_secret, post=requests.post, clock=time.monotonic):
        self.client_id, self.client_secret = client_id, client_secret
        self._post, self._clock = post, clock
        self._token, self._expires_at = None, 0.0

    @classmethod
    def from_env(cls):
        client_id, client_secret = os.getenv("CDSE_CLIENT_ID"), os.getenv("CDSE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise CopernicusError("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET are not set. "
                                  "Copy .env.example to .env and fill them in.")
        return cls(client_id, client_secret)

    def get(self):
        if self._token is None or self._expires_at - self._clock() < TOKEN_MARGIN_S:
            r = self._post(TOKEN_URL, timeout=30, data={
                "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
            if not r.ok:
                raise CopernicusError(f"CDSE token request failed: HTTP {r.status_code}\n{r.text[:500]}")
            self._token = _field(r, "access_token", "CDSE token request")
            self._expires_at = self._clock() + float(r.json().get("expires_in", 300))
        return self._token


# ---------------------------------------------------------------- grid, tiling, fetch

def grid(bbox, res_m=config.RES_M):
    """Pixel grid (w, h) for bbox at res_m."""
    x0, y0, x1, y1 = bbox
    width_m = (x1 - x0) * 111_320 * math.cos(math.radians((y0 + y1) / 2))
    height_m = (y1 - y0) * 110_540
    return round(width_m / res_m), round(height_m / res_m)


def tile_edges(n, max_px):
    """Split n pixels into ceil(n/max_px) near-equal spans."""
    k = math.ceil(n / max_px)
    return [round(i * n / k) for i in range(k + 1)]


def tile_bboxes(bbox, w, h, max_px=MAX_PX):
    """Tiles of the w x h grid as (r0, r1, c0, c1, tile_bbox), row-major. Each tile bbox spans exactly
    its own pixel range of the full grid; outer edges are the bbox edges themselves."""
    x0, y0, x1, y1 = bbox
    dlon, dlat = (x1 - x0) / w, (y1 - y0) / h

    def lon(c):
        return x1 if c == w else x0 + c * dlon

    def lat(r):                       # row 0 is the north edge
        return y0 if r == h else y1 - r * dlat

    rows, cols = tile_edges(h, max_px), tile_edges(w, max_px)
    return [(r0, r1, c0, c1, (lon(c0), lat(r1), lon(c1), lat(r0)))
            for r0, r1 in zip(rows[:-1], rows[1:]) for c0, c1 in zip(cols[:-1], cols[1:])]


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
    r = requests.post(PROCESS_URL, json=body, timeout=300, headers={"Authorization": f"Bearer {token}"})
    if not r.ok:
        raise CopernicusError(f"Process API request failed: HTTP {r.status_code}\n{r.text[:500]}")
    pu = r.headers.get("x-processingunits-spent")
    return np.asarray(Image.open(BytesIO(r.content))), float(pu) if pu is not None else None


def fetch_tiled(bbox, data, evalscript, get_token, process_fn=None, max_px=MAX_PX):
    """Fetch bbox at RES_M as tiles of at most max_px on both axes, stitched. Returns 2-D uint16."""
    process_fn = process_fn or process
    w, h = grid(bbox)
    tiles = tile_bboxes(bbox, w, h, max_px)
    arrays, spent = {}, []
    for r0, r1, c0, c1, tile_bbox in tiles:
        arr, pu = process_fn(get_token(), tile_bbox, data, evalscript, c1 - c0, r1 - r0)
        arr = np.asarray(arr)
        if arr.shape != (r1 - r0, c1 - c0) or arr.dtype != np.uint16:
            raise UnexpectedResponseError(f"tile {(r0, r1, c0, c1)}: expected uint16 {(r1 - r0, c1 - c0)}, "
                             f"got {arr.dtype} {arr.shape}")
        arrays[(r0, c0)] = arr
        if pu is not None:
            spent.append(pu)
    rows = sorted({t[0] for t in tiles})
    cols = sorted({t[2] for t in tiles})
    log.info("%d tile(s), %.1f processing units spent", len(tiles), sum(spent))
    return np.block([[arrays[(r, c)] for c in cols] for r in rows])


def scene_window(scene, pad=timedelta(minutes=1)):
    return {"from": (scene["start"] - pad).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": (scene["end"] + pad).strftime("%Y-%m-%dT%H:%M:%SZ")}


def s1_data(scene):
    data = json.loads(json.dumps(S1_DATA_TEMPLATE))
    data["dataFilter"]["timeRange"] = scene_window(scene)
    return data


def fetch_s1_raw(scene, bbox, get_token):
    """Raw uint16 dB encoding of one S1 pass over bbox (0 = no data)."""
    return fetch_tiled(bbox, s1_data(scene), S1_EVALSCRIPT, get_token)


def encode_db(db):
    db = np.asarray(db, dtype=np.float64)
    raw = np.clip(np.round((np.nan_to_num(db, nan=-DB_OFFSET) + DB_OFFSET) * DB_SCALE), 1, 65535)
    return np.where(np.isfinite(db), raw, NODATA).astype(np.uint16)


def decode_db(raw):
    db = raw.astype(np.float32) / np.float32(DB_SCALE) - np.float32(DB_OFFSET)
    db[raw == NODATA] = np.nan
    return db


# ---------------------------------------------------------------- pass cache

def grid_id(bbox):
    """Identifies everything that decides what a cached raster contains."""
    blob = json.dumps({"bbox": [float(v) for v in bbox], "res_m": config.RES_M,
                       "request": S1_DATA_TEMPLATE, "evalscript": S1_EVALSCRIPT}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def pass_path(data_dir, port, gid, image_id):
    return Path(data_dir) / "cache" / port / gid / f"{image_id}.npz"


def atomic_savez(path, **arrays):
    with atomic_path(path) as tmp:
        with open(tmp, "wb") as f:
            np.savez_compressed(f, **arrays)


def expected_shape(bbox):
    w, h = grid(bbox)
    return h, w


def load_pass(path, bbox):
    with np.load(path) as z:
        raw, saved_bbox, shape = z["raw"], z["bbox"], tuple(int(v) for v in z["shape"])
    if not np.array_equal(saved_bbox, np.asarray(bbox, dtype=np.float64)) or shape != expected_shape(bbox) \
            or raw.shape != shape or raw.dtype != np.uint16:
        raise CacheMismatchError(f"{path} does not match bbox {tuple(bbox)} / grid {expected_shape(bbox)}; delete it or use --refresh")
    return raw


def get_pass(data_dir, port, bbox, scene, fetch_fn, refresh=False):
    """Raw uint16 raster of one pass: from the cache, or fetched and cached.

    A pass with no data at all is returned but not cached, so it is retried on the next run. With
    refresh=True an all-no-data refetch of a pass that is already cached raises instead: the cache holds
    the only good copy, and replacing a result with null on the strength of a transient empty answer
    would lose it.
    """
    path = pass_path(data_dir, port, grid_id(bbox), scene["image_id"])
    if path.exists() and not refresh:
        return load_pass(path, bbox)
    raw = np.asarray(fetch_fn(scene, bbox))
    if raw.shape != expected_shape(bbox) or raw.dtype != np.uint16:
        raise UnexpectedResponseError(f"fetch for {scene['image_id']}: expected uint16 {expected_shape(bbox)}, "
                         f"got {raw.dtype} {raw.shape}")
    if not raw.any() and refresh and path.exists():
        raise CopernicusError(f"refresh of {scene['image_id']} returned no data (it may not be processed again yet); "
                              f"keeping the cached raster {path}")
    if raw.any():
        atomic_savez(path, raw=raw, bbox=np.asarray(bbox, dtype=np.float64), shape=np.asarray(raw.shape))
    return raw
