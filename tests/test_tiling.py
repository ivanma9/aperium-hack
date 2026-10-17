import numpy as np
import pytest

from conftest import TINY_BBOX
from portwatch import copernicus as cop


def test_10_tile_edges():
    assert cop.tile_edges(3446, 2500) == [0, 1723, 3446]
    assert cop.tile_edges(1658, 2500) == [0, 1658]
    assert cop.tile_edges(5000, 2500) == [0, 2500, 5000]


def test_11_tile_bboxes_cover_the_box_exactly():
    bbox = (-97.30, 27.75, -96.95, 27.90)
    w, h = 5000, 3000
    tiles = cop.tile_bboxes(bbox, w, h, 2500)
    assert len(tiles) == 4                      # 2 x 2
    x0, y0, x1, y1 = bbox
    # union is the full bbox, exactly
    assert min(t[4][0] for t in tiles) == x0 and max(t[4][2] for t in tiles) == x1
    assert min(t[4][1] for t in tiles) == y0 and max(t[4][3] for t in tiles) == y1
    # adjacent tiles share edges exactly
    by_pos = {(t[0], t[2]): t for t in tiles}          # keyed by (r0, c0)
    assert by_pos[(0, 0)][4][2] == by_pos[(0, 2500)][4][0]       # left/right neighbours
    assert by_pos[(0, 0)][4][1] == by_pos[(1500, 0)][4][3]       # top/bottom neighbours
    # pixel size equals span / global d
    dlon, dlat = (x1 - x0) / w, (y1 - y0) / h
    for r0, r1, c0, c1, (a, b, c, d) in tiles:
        assert (c - a) / dlon == pytest.approx(c1 - c0)
        assert (d - b) / dlat == pytest.approx(r1 - r0)


def test_grid_of_the_tiny_test_port():
    assert cop.grid(TINY_BBOX) == (98, 111)


def test_fetch_tiled_stitches_in_row_major_order():
    seen = []

    def fake_process(token, bbox, data, evalscript, w, h):
        k = len(seen)
        seen.append((bbox, w, h))
        return np.full((h, w), k + 1, dtype=np.uint16), 1.0

    out = cop.fetch_tiled(TINY_BBOX, {}, "es", lambda: "tok", process_fn=fake_process, max_px=60)
    assert out.shape == (111, 98) and out.dtype == np.uint16
    assert len(seen) == 4                        # 2 x 2 tiles
    assert out[0, 0] == 1 and out[0, -1] == 2 and out[-1, 0] == 3 and out[-1, -1] == 4


def test_fetch_tiled_asserts_tile_shape_and_dtype():
    with pytest.raises(cop.UnexpectedResponseError):
        cop.fetch_tiled(TINY_BBOX, {}, "es", lambda: "t",
                        process_fn=lambda t, b, d, e, w, h: (np.zeros((h + 1, w), dtype=np.uint16), None))
    with pytest.raises(cop.UnexpectedResponseError):
        cop.fetch_tiled(TINY_BBOX, {}, "es", lambda: "t",
                        process_fn=lambda t, b, d, e, w, h: (np.zeros((h, w), dtype=np.float32), None))
    with pytest.raises(cop.UnexpectedResponseError):             # 3-D (h, w, 1) is not accepted either
        cop.fetch_tiled(TINY_BBOX, {}, "es", lambda: "t",
                        process_fn=lambda t, b, d, e, w, h: (np.zeros((h, w, 1), dtype=np.uint16), None))
