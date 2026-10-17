"""Synthetic scene helpers. Everything is numeric and seeded; nothing touches the network."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from portwatch import copernicus
from portwatch.ports import Port

SHAPE = (400, 400)            # 400 x 400 px at 10 m

# A tiny port for pipeline tests: about 1 km x 1.1 km, so rasters are 111 x 98 px.
TINY_BBOX = (-97.0, 27.80, -96.99, 27.81)
TINY_SHAPE = (111, 98)        # (rows, cols) of grid(TINY_BBOX)
UTC = timezone.utc
NOW = datetime(2026, 4, 20, tzinfo=UTC)


@pytest.fixture
def rng():
    return np.random.default_rng(20261017)


@pytest.fixture
def ref(rng):
    """Calm water, N(-22, 0.5) dB."""
    return rng.normal(-22.0, 0.5, SHAPE)


@pytest.fixture
def scene(ref, rng):
    """A pass over `ref`: ref + N(0, 1)."""
    return ref + rng.normal(0.0, 1.0, SHAPE)


def paint(db, r0, r1, c0, c1, value=10.0):
    """Set rows r0:r1, cols c0:c1 to an absolute dB value (a ship, a dock...)."""
    db[r0:r1, c0:c1] = value
    return db


def blob_n(db, r0, c0, n, width, value=10.0):
    """Paint exactly n connected pixels: full rows of `width`, then a partial row."""
    full, rest = divmod(n, width)
    db[r0:r0 + full, c0:c0 + width] = value
    if rest:
        db[r0 + full, c0:c0 + rest] = value
    return db


def hull(db, r0, c0, rows=6, value=10.0):
    """A 30 px (300 m) tanker made of 3 bright clusters with 20 m and 30 m dark gaps."""
    for a, b in ((0, 8), (10, 19), (22, 30)):
        db[r0:r0 + rows, c0 + a:c0 + b] = value
    return db


def aux_tiny_port(**kw):
    kw.setdefault("reference_from", "2026-01-01T00:00:00Z")
    kw.setdefault("reference_to", "2026-03-15T00:00:00Z")
    return Port(name="tiny", bbox=TINY_BBOX, notes="test", **kw)


class FakeWorld:
    """Stands in for the catalogue and the Process API. Counts every fetch."""

    def __init__(self, orbits, seed=7, background=None, mutate=None):
        """orbits: {relative_orbit: (reference_dates, target_dates)}

        background(rng) -> dB array of TINY_SHAPE for one pass (default: calm water, N(-22, 0.5)).
        mutate(db, start, is_target) edits the pass in place before the ship is painted.
        """
        self.rng = np.random.default_rng(seed)
        self.background, self.mutate = background, mutate
        self.scenes, self.rasters, self.calls = [], {}, []
        self.nodata_once = set()
        for orbit, (ref_dates, target_dates) in orbits.items():
            for d in ref_dates:
                self._add(orbit, d, ship=False)
            for d in target_dates:
                self._add(orbit, d, ship=True)

    def _add(self, orbit, start, ship):
        image_id = f"S1A_IW_GRDH_1SDV_{start:%Y%m%dT%H%M%S}_{orbit}"
        self.scenes.append({"name": image_id + ".SAFE", "image_id": image_id, "platform": "S1A", "start": start,
                            "end": start + timedelta(seconds=25), "orbit_direction": "ASCENDING",
                            "relative_orbit": orbit, "cloud_cover": None})
        db = self.background(self.rng) if self.background else self.rng.normal(-22.0, 0.5, TINY_SHAPE)
        if self.mutate:
            self.mutate(db, start, ship)
        if ship:
            db[50:56, 30:50] = 10.0          # one 6 x 20 px ship = 12,000 m2
        self.rasters[image_id] = copernicus.encode_db(db)

    def search(self, bbox, since):
        return sorted((s for s in self.scenes if s["start"] >= since), key=lambda s: s["start"], reverse=True)

    def fetch(self, scene, bbox):
        self.calls.append(scene["image_id"])
        if scene["image_id"] in self.nodata_once:
            self.nodata_once.discard(scene["image_id"])
            return np.zeros(TINY_SHAPE, dtype=np.uint16)
        return self.rasters[scene["image_id"]].copy()


def every_12_days(start, n):
    return [start + timedelta(days=12 * i) for i in range(n)]


def two_level_background(rng):
    """Cols 0:60 at -22 dB, cols 60: at -35 dB. Water at WATER_DB=-18 (all of it), but at -30 only the right part."""
    db = rng.normal(-22.0, 0.5, TINY_SHAPE)
    db[:, 60:] = rng.normal(-35.0, 0.5, db[:, 60:].shape)
    return db


def land_background(rng):
    """No water anywhere."""
    return rng.normal(-8.0, 0.5, TINY_SHAPE)


def half_land_background(rng):
    """Water in cols 0:49, land in cols 49:."""
    db = rng.normal(-22.0, 0.5, TINY_SHAPE)
    db[:, 49:] = rng.normal(-8.0, 0.5, db[:, 49:].shape)
    return db


def qc_background(stable_rows):
    """Water in cols 0:50. Land in cols 50: with `stable_rows` rows of steady bright pixels (-2 dB, sigma 0.2)
    on top and noisy bright land below (+2 dB, sigma 4): the noisy part must not feed the calibration proxy."""
    def background(rng):
        db = rng.normal(-22.0, 0.5, TINY_SHAPE)
        db[:, 50:] = rng.normal(2.0, 4.0, db[:, 50:].shape)
        db[:stable_rows, 50:] = rng.normal(-2.0, 0.2, db[:stable_rows, 50:].shape)
        return db
    return background
