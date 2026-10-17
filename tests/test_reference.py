import numpy as np
import pytest

from conftest import SHAPE, paint
from portwatch import config, detect
from portwatch import copernicus as cop
from portwatch.reference import absorbed_berths, build_reference, compute_reference_id, percentile_stack


def stack_of(values):
    return np.array(values, dtype=float).reshape(len(values), 1, 1) * np.ones((1, 2, 2))


def test_12_percentile_index_rule():
    p, mn, n = percentile_stack(stack_of([-20, -10, 0, 10]), 25)
    assert p[0, 0] == -20 and mn[0, 0] == -20 and n[0, 0] == 4      # floor(0.25 * 3) = 0
    p, mn, n = percentile_stack(stack_of([-20, np.nan, 0, 10]), 25)
    assert p[0, 0] == -20 and n[0, 0] == 3                           # floor(0.25 * 2) = 0


def test_12b_index_moves_with_more_samples():
    p, _, _ = percentile_stack(stack_of([-40, -30, -20, -10, 0]), 50)
    assert p[0, 0] == -20                                           # floor(0.5 * 4) = 2


def test_13_fewer_than_three_valid_samples_is_nan():
    p, mn, n = percentile_stack(stack_of([-20, np.nan, np.nan, 10]), 25)
    assert np.isnan(p).all() and np.isnan(mn).all() and (n == 2).all()


def make_stack(rng, n, k, value=5.0):
    """n passes of calm water; a 10 x 10 px ship at (50:60, 50:60) is present in the first k."""
    stack = rng.normal(-22.0, 0.5, (n,) + SHAPE)
    for i in range(k):
        paint(stack[i], 50, 60, 50, 60, value)
    return stack


@pytest.mark.parametrize("k,flagged", [(12, True), (11, False), (2, False)])
def test_21_absorbed_berth_report(rng, k, flagged):
    p, mn, _ = percentile_stack(make_stack(rng, 15, k), 25)
    mask, count = absorbed_berths(p, mn)
    assert mask.shape == SHAPE
    assert bool(mask[55, 55]) is flagged
    assert count == (100 if flagged else 0)


def test_21b_report_uses_the_min_reference_water_mask(rng):
    # An absorbed berth sits inside the min-water mask but would be excluded from the p25 water mask.
    p, mn, _ = percentile_stack(make_stack(rng, 15, 14), 25)
    assert p[55, 55] > -18                                          # p25 says "land": it absorbed the berth
    mask, count = absorbed_berths(p, mn)
    assert mask[55, 55] and count == 100


def test_21c_speckle_and_sea_state_alone_flag_nothing(rng):
    # Real passes: ~2.5 dB speckle per pixel plus a per-pass sea-state offset. The minimum of 15 such
    # passes sits >10 dB under p25 almost everywhere, so p25 - min alone flags open water. An absorbed
    # berth must also be ship-bright in p25 itself.
    stack = rng.normal(-22.0, 2.5, (15,) + SHAPE) + rng.uniform(-2.0, 4.0, (15, 1, 1))
    p, mn, _ = percentile_stack(stack, 25)
    mask, count = absorbed_berths(p, mn)
    assert count == 0


def test_25_reference_id_changes_with_every_input():
    base = ("g1", 107, "2026-01-01", "2026-03-01", 25, ["a", "b", "c"])
    rid = compute_reference_id(*base)
    assert len(rid) == 12
    assert rid == compute_reference_id("g1", 107, "2026-01-01", "2026-03-01", 25, ["c", "a", "b"])   # order-free
    assert rid != compute_reference_id("g2", 107, "2026-01-01", "2026-03-01", 25, ["a", "b", "c"])
    assert rid != compute_reference_id("g1", 14, "2026-01-01", "2026-03-01", 25, ["a", "b", "c"])
    assert rid != compute_reference_id("g1", 107, "2026-01-02", "2026-03-01", 25, ["a", "b", "c"])
    assert rid != compute_reference_id("g1", 107, "2026-01-01", "2026-03-02", 25, ["a", "b", "c"])
    assert rid != compute_reference_id("g1", 107, "2026-01-01", "2026-03-01", 10, ["a", "b", "c"])
    assert rid != compute_reference_id("g1", 107, "2026-01-01", "2026-03-01", 25, ["a", "b", "c", "d"])


def test_m2_chunked_build_is_bit_identical_to_the_unchunked_one(rng):
    dbs = [rng.normal(-15.0, 6.0, (450, 37)) for _ in range(7)]
    for d in dbs[2:5]:
        d[rng.random(d.shape) < 0.3] = np.nan                        # no-data scattered over some passes
    dbs[0][100:260] = np.nan                                         # and a block spanning chunk borders
    raws = [cop.encode_db(d) for d in dbs]
    p, mn, n = percentile_stack(np.stack([cop.decode_db(r) for r in raws]), 25)
    for chunk_rows in (None, 200, 64, 1, 450, 1000):
        ref = build_reference(raws, 25) if chunk_rows is None else build_reference(raws, 25, chunk_rows=chunk_rows)
        np.testing.assert_array_equal(ref["p25"], p)
        np.testing.assert_array_equal(ref["min"], mn)
        np.testing.assert_array_equal(ref["n_samples"], n)
        assert ref["p25"].dtype == p.dtype and ref["n_samples"].dtype == n.dtype
        for q in (50, 75):
            expect = percentile_stack(np.stack([cop.decode_db(r) for r in raws]), q)[0]
            np.testing.assert_array_equal(ref[f"p{q}"], expect)
        assert set(ref) == {"p25", "p50", "p75", "min", "n_samples"}


def test_i5_reference_stores_the_quartiles():
    stack = stack_of([-20, -10, 0, 10, 20])
    raws = [cop.encode_db(layer) for layer in stack]
    ref = build_reference(raws, 25)
    assert ref["p25"][0, 0] == pytest.approx(-10, abs=0.01)        # floor(0.25 * 4) = 1
    assert ref["p50"][0, 0] == pytest.approx(0, abs=0.01)
    assert ref["p75"][0, 0] == pytest.approx(10, abs=0.01)         # floor(0.75 * 4) = 3
    assert ref["min"][0, 0] == pytest.approx(-20, abs=0.01)


def test_m10_reference_id_changes_with_min_ref_passes_and_format(monkeypatch):
    assert getattr(config, "REFERENCE_FORMAT", None) == 2
    base = ("g1", 107, "2026-01-01", "2026-03-01", 25, ["a", "b", "c"])
    rid = compute_reference_id(*base)
    monkeypatch.setattr(config, "MIN_REF_PASSES", config.MIN_REF_PASSES + 1)
    assert compute_reference_id(*base) != rid
    monkeypatch.undo()
    monkeypatch.setattr(config, "REFERENCE_FORMAT", config.REFERENCE_FORMAT + 1)
    assert compute_reference_id(*base) != rid


def test_x1_reference_id_changes_with_the_exclude_boxes():
    base = ("g1", 107, "2026-01-01", "2026-03-01", 25, ["a", "b", "c"])
    rid = compute_reference_id(*base)
    assert rid == compute_reference_id(*base, exclude=[])
    boxes = [(-95.295, 29.635, -95.262, 29.660)]
    other = compute_reference_id(*base, exclude=boxes)
    assert other != rid
    assert other != compute_reference_id(*base, exclude=[(-95.295, 29.635, -95.262, 29.661)])
    two = [(-95.175, 29.600, -95.140, 29.625)] + boxes
    assert compute_reference_id(*base, exclude=two) == compute_reference_id(*base, exclude=list(reversed(two)))


def test_x1_apply_exclusions_uses_pixel_centres():
    water = np.ones((10, 10), dtype=bool)
    out = detect.apply_exclusions(water, (0.0, 0.0, 10.0, 10.0), [(2.0, 2.0, 4.0, 4.0)])
    expect = np.ones((10, 10), dtype=bool)
    expect[6:8, 2:4] = False                  # centres lon 2.5, 3.5 and lat 3.5, 2.5 (row 0 is the north edge)
    np.testing.assert_array_equal(out, expect)
    assert water.all()                         # the input is not modified
    np.testing.assert_array_equal(detect.apply_exclusions(water, (0.0, 0.0, 10.0, 10.0), []), water)
