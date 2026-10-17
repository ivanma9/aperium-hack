import logging

import numpy as np
import pytest

from conftest import SHAPE, blob_n, hull, paint
from portwatch.reference import percentile_stack
from portwatch.detect import detect_ships, pixel_to_lonlat, qc_columns, water_mask


def by_area(ships):
    return sorted(ships, key=lambda s: -s["area_m2"])


def test_01_ships_on_water(scene, ref):
    paint(scene, 100, 106, 100, 120, 12.0)    # 6 x 20 px
    paint(scene, 300, 304, 250, 260, 8.0)     # 4 x 10 px
    ships = by_area(detect_ships(scene, ref).ships)
    assert len(ships) == 2
    assert [s["area_m2"] for s in ships] == [12000, 4000]
    assert ships[0]["row"] == pytest.approx(102.5, abs=1) and ships[0]["col"] == pytest.approx(109.5, abs=1)
    assert ships[1]["row"] == pytest.approx(301.5, abs=1) and ships[1]["col"] == pytest.approx(254.5, abs=1)


def test_02_bright_land_is_not_a_ship(scene, ref):
    ref[:, :120] = -8.0
    scene[:, :120] = -8.0
    paint(scene, 200, 230, 40, 70, 10.0)
    res = detect_ships(scene, ref)
    assert res.ships == []
    assert not res.water[:, :120].any()


def test_03_static_bright_structure_on_water(scene, ref):
    paint(ref, 200, 202, 200, 240, 5.0)       # thin dock: survives as water after the median filter
    paint(scene, 200, 202, 200, 240, 6.0)
    res = detect_ships(scene, ref)
    assert res.water[200, 220], "the dock must still be inside the water mask, so only the contrast rule rejects it"
    assert res.ships == []


def test_04_speckle_and_noise(scene, ref, rng):
    paint(scene, 50, 51, 50, 51, 10.0)        # 1 px
    paint(scene, 300, 303, 300, 303, 10.0)    # 3 x 3 px
    assert detect_ships(scene, ref).ships == []
    noisy = ref + rng.normal(0.0, 3.0, SHAPE)
    assert detect_ships(noisy, ref).ships == []


class TestEdges:
    def test_05a_ship_touching_top_edge(self, scene, ref):
        paint(scene, 0, 6, 100, 120, 10.0)
        ships = detect_ships(scene, ref).ships
        assert len(ships) == 1 and ships[0]["area_m2"] == 12000
        assert ships[0]["row"] == pytest.approx(2.5, abs=1) and ships[0]["col"] == pytest.approx(109.5, abs=1)

    def test_05b_ship_inside_nan_area(self, scene, ref):
        paint(scene, 100, 106, 50, 70, 10.0)
        scene[:, :200] = np.nan
        assert detect_ships(scene, ref).ships == []

    def test_05c_ship_next_to_nan_boundary(self, scene, ref):
        scene[:, :200] = np.nan
        paint(scene, 100, 106, 200, 220, 10.0)
        ships = detect_ships(scene, ref).ships
        assert len(ships) == 1 and ships[0]["area_m2"] == 12000
        assert ships[0]["col"] == pytest.approx(209.5, abs=1)

    def test_05d_water_is_false_where_pass_is_nan_and_static_mask_unchanged(self, scene, ref):
        static = water_mask(ref)
        scene[:, :200] = np.nan
        res = detect_ships(scene, ref)
        assert not res.valid[:, :200].any() and res.valid[:, 200:].all()
        assert not (res.water & res.valid)[:, :200].any()
        assert np.array_equal(res.water, static)
        assert static.sum() > 0.9 * static.size

    def test_05e_nan_reference_is_never_water(self, scene, ref):
        ref[100:150, 100:150] = np.nan
        paint(scene, 120, 126, 110, 130, 10.0)
        res = detect_ships(scene, ref)
        assert not res.water[100:150, 100:150].any()
        assert res.ships == []


def test_06_merge_rule_boundary(scene, ref):
    paint(scene, 100, 104, 100, 110, 10.0)
    paint(scene, 100, 104, 122, 132, 10.0)    # 120 m gap (12 empty px)
    assert len(detect_ships(scene, ref).ships) == 1
    scene2 = scene.copy()
    scene2[100:104, 122:132] = ref[100:104, 122:132]
    paint(scene2, 100, 104, 123, 133, 10.0)   # 130 m gap
    assert len(detect_ships(scene2, ref).ships) == 2


@pytest.mark.parametrize("n,width,expected", [(15, 5, 1), (14, 7, 0), (400, 20, 1), (401, 20, 0)])
def test_07_size_limits(scene, ref, n, width, expected):
    blob_n(scene, 100, 100, n, width)
    ships = detect_ships(scene, ref).ships
    assert [s["area_m2"] for s in ships] == [n * 100] * expected


def test_08_small_water_body(scene, ref):
    ref[:] = -8.0
    scene[:] = -8.0
    ref[180:200, 180:205] = -22.0             # 500 px = 0.05 km2
    scene[180:200, 180:205] = -22.0
    paint(scene, 185, 189, 190, 200, 10.0)    # a ship inside the pond
    assert detect_ships(scene, ref).ships == []


def test_09_pixel_to_lonlat():
    bbox = (-97.3, 27.75, -96.95, 27.9)
    x0, y0, x1, y1 = bbox
    dx, dy = (x1 - x0) / 200, (y1 - y0) / 100
    lon, lat = pixel_to_lonlat(bbox, (100, 200), 0, 0)
    assert (lon, lat) == pytest.approx((x0 + 0.5 * dx, y1 - 0.5 * dy))
    lon, lat = pixel_to_lonlat(bbox, (100, 200), 99, 199)
    assert (lon, lat) == pytest.approx((x1 - 0.5 * dx, y0 + 0.5 * dy))


class TestFallback:
    """Test 20 with the A4 cases: oversize merged blobs are re-split at SPLIT_M."""

    @pytest.mark.parametrize("n_hulls,expected", [(1, 1), (2, 1), (3, 3)])
    def test_20a_tankers_with_dark_gaps(self, scene, ref, n_hulls, expected):
        for i in range(n_hulls):
            hull(scene, 100, 20 + i * 38)     # 30 px hulls, 80 m (8 px) apart
        res = detect_ships(scene, ref)
        assert len(res.ships) == expected     # 2 -> 1 is the documented step: two hulls under MAX_AREA stay merged
        assert res.n_rejected_large == 0

    def test_20b_three_solid_ships(self, scene, ref):
        for i in range(3):
            paint(scene, 100, 106, 20 + i * 38, 50 + i * 38, 10.0)
        res = detect_ships(scene, ref)
        assert len(res.ships) == 3 and res.n_rejected_large == 0

    def test_20c_huge_single_blob_is_rejected_and_counted(self, scene, ref):
        paint(scene, 100, 125, 100, 125, 10.0)   # 25 x 25 px = 62,500 m2
        res = detect_ships(scene, ref)
        assert res.ships == [] and res.n_rejected_large == 1

    def test_20d_44000_m2_ship_split_by_a_20_m_gap(self, scene, ref):
        paint(scene, 100, 111, 100, 120, 10.0)
        paint(scene, 100, 111, 122, 142, 10.0)   # 2 px gap, 440 px in all
        res = detect_ships(scene, ref)
        assert res.ships == [] and res.n_rejected_large == 1

    def test_20e_fallbacks_are_logged(self, scene, ref, caplog):
        for i in range(3):
            hull(scene, 100, 20 + i * 38)
        with caplog.at_level(logging.INFO, logger="portwatch.detect"):
            detect_ships(scene, ref)
        msgs = [r.getMessage() for r in caplog.records if "fallback" in r.getMessage().lower()]
        assert len(msgs) == 1 and "3 part" in msgs[0]


class TestGeometry:
    def test_22a_horizontal_blob(self, scene, ref):
        paint(scene, 100, 106, 100, 130, 10.0)   # 6 x 30 px
        s = detect_ships(scene, ref).ships[0]
        assert s["length_m"] == pytest.approx(300, rel=0.02)
        assert s["width_m"] == pytest.approx(60, rel=0.02)
        assert s["orientation_deg"] == pytest.approx(90, abs=1)

    def test_22b_vertical_blob(self, scene, ref):
        paint(scene, 100, 130, 100, 106, 10.0)
        s = detect_ships(scene, ref).ships[0]
        assert s["length_m"] == pytest.approx(300, rel=0.02)
        o = s["orientation_deg"]
        assert 0 <= o < 180 and min(o, 180 - o) < 1

    def test_22c_ne_sw_diagonal_blob_is_45_degrees(self, scene, ref):
        rr, cc = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
        diag = (np.abs((cc - 200) + (rr - 200)) <= 3) & (np.abs((cc - 200) - (rr - 200)) <= 20)
        scene[diag] = 10.0                        # long axis runs up and to the right
        o = detect_ships(scene, ref).ships[0]["orientation_deg"]
        assert o == pytest.approx(45, abs=3)

    def test_n_parts_counts_hull_scale_pieces(self, scene, ref):
        hull(scene, 100, 20)
        paint(scene, 200, 206, 20, 50, 10.0)
        ships = sorted(detect_ships(scene, ref).ships, key=lambda s: s["row"])
        assert len(ships) == 2
        a, b = ships
        assert a["n_parts"] == 1 and b["n_parts"] == 1   # SPLIT_M joins 20 m gaps, so one hull is one part

    def test_n_parts_two_hulls_merged(self, scene, ref):
        hull(scene, 100, 20)
        hull(scene, 100, 58)                      # 80 m apart: merged at MERGE_M, 2 parts at SPLIT_M
        s = detect_ships(scene, ref).ships
        assert len(s) == 1 and s[0]["n_parts"] == 2


class TestQC:
    """cal_proxy_db: median(db - p50) over stable non-water pixels; sea_state_db: the same over water."""

    @pytest.fixture
    def stats(self, rng):
        """12 passes: water on the left, steady bright land top right, noisy bright land bottom right."""
        stack = rng.normal(-22.0, 0.5, (12,) + (100, 200))
        stack[:, :, 100:] = rng.normal(2.0, 4.0, stack[:, :, 100:].shape)
        stack[:, :50, 100:] = rng.normal(-2.0, 0.2, stack[:, :50, 100:].shape)
        p25, _, _ = percentile_stack(stack, 25)
        p50, _, _ = percentile_stack(stack, 50)
        p75, _, _ = percentile_stack(stack, 75)
        return {"p25": p25, "p50": p50, "p75": p75}, rng

    def fresh(self, stats, offset, rng):
        db = rng.normal(-22.0, 0.5, (100, 200))
        db[:, 100:] = rng.normal(2.0, 4.0, db[:, 100:].shape)
        db[:50, 100:] = rng.normal(-2.0, 0.2, db[:50, 100:].shape)
        return db + offset

    @pytest.mark.parametrize("offset", [1.0, 0.0])
    def test_24a_offset_shows_up_in_both_columns(self, stats, offset):
        st, rng = stats
        cal, sea = qc_columns(self.fresh(st, offset, rng), st, water_mask(st["p25"]))
        assert cal == pytest.approx(offset, abs=0.1) and sea == pytest.approx(offset, abs=0.1)

    def test_24b_offset_on_water_only(self, stats):
        st, rng = stats
        water = water_mask(st["p25"])
        db = self.fresh(st, 0.0, rng)
        db[water] += 1.0
        cal, sea = qc_columns(db, st, water)
        assert sea == pytest.approx(1.0, abs=0.1) and cal == pytest.approx(0.0, abs=0.1)

    def test_noisy_land_is_not_a_calibration_target(self, stats):
        st, rng = stats
        db = self.fresh(st, 0.0, rng)
        db[50:, 100:] += 5.0                      # noisy land jumps; stable targets do not
        cal, _ = qc_columns(db, st, water_mask(st["p25"]))
        assert cal == pytest.approx(0.0, abs=0.1)

    @pytest.mark.parametrize("n_stable,is_nan", [(99, True), (100, False)])
    def test_fewer_than_100_stable_pixels_gives_nan(self, stats, n_stable, is_nan):
        st, rng = stats
        p25 = st["p25"].copy()
        p25[:, 100:] = np.nan                     # drop the land reference...
        p25[0, 100:100 + n_stable] = st["p25"][0, 100:100 + n_stable]      # ...except n_stable steady pixels
        st = {**st, "p25": p25}
        cal, sea = qc_columns(self.fresh(st, 1.0, rng), st, water_mask(p25))
        assert bool(np.isnan(cal)) is is_nan and sea == pytest.approx(1.0, abs=0.1)

    def test_no_land_gives_nan_cal_proxy(self, ref, scene):
        p = np.full(ref.shape, -22.0)
        cal, sea = qc_columns(scene, {"p25": p, "p50": p, "p75": p}, water_mask(ref))
        assert np.isnan(cal) and sea == pytest.approx(0.0, abs=0.1)
