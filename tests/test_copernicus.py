from datetime import datetime, timezone

import numpy as np
import pytest

from conftest import TINY_BBOX, TINY_SHAPE
from portwatch import copernicus as cop


def test_encode_decode_round_trip():
    db = np.array([[-22.0, np.nan], [-8.123, 12.0]])
    raw = cop.encode_db(db)
    assert raw.dtype == np.uint16 and raw[0, 1] == cop.NODATA
    back = cop.decode_db(raw)
    assert np.isnan(back[0, 1])
    assert back[0, 0] == pytest.approx(-22.0, abs=0.002) and back[1, 0] == pytest.approx(-8.123, abs=0.002)


def test_grid_id_depends_on_the_bbox():
    a = cop.grid_id(TINY_BBOX)
    assert len(a) == 12 and a == cop.grid_id(TINY_BBOX)
    assert a != cop.grid_id((-97.0, 27.80, -96.99, 27.82))


def scene(image_id="S1A_X"):
    t = datetime(2026, 4, 1, tzinfo=timezone.utc)
    return {"image_id": image_id, "start": t, "end": t}


class Fetcher:
    def __init__(self, raw):
        self.raw, self.calls = raw, 0

    def __call__(self, scene, bbox):
        self.calls += 1
        return self.raw.copy()


def good_raw():
    return cop.encode_db(np.full(TINY_SHAPE, -22.0))


def test_pass_cache_hit_refresh_and_path(tmp_path):
    f = Fetcher(good_raw())
    a = cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)
    b = cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)
    assert f.calls == 1 and np.array_equal(a, b) and a.dtype == np.uint16
    expected = tmp_path / "cache" / "tiny" / cop.grid_id(TINY_BBOX) / "S1A_X.npz"
    assert expected.exists() and cop.pass_path(tmp_path, "tiny", cop.grid_id(TINY_BBOX), "S1A_X") == expected
    cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f, refresh=True)
    assert f.calls == 2


def test_no_data_pass_is_not_cached(tmp_path):
    f = Fetcher(np.zeros(TINY_SHAPE, dtype=np.uint16))
    raw = cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)
    assert not raw.any()
    cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)
    assert f.calls == 2
    assert not list((tmp_path / "cache").rglob("*.npz"))


def test_refresh_with_an_empty_refetch_keeps_the_cached_raster(tmp_path):
    cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), Fetcher(good_raw()))
    path = cop.pass_path(tmp_path, "tiny", cop.grid_id(TINY_BBOX), "S1A_X")
    before = path.read_bytes()
    with pytest.raises(cop.CopernicusError, match="S1A_X"):
        cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), Fetcher(np.zeros(TINY_SHAPE, dtype=np.uint16)), refresh=True)
    assert path.read_bytes() == before


def test_refresh_with_an_empty_refetch_is_fine_when_nothing_is_cached(tmp_path):
    raw = cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), Fetcher(np.zeros(TINY_SHAPE, dtype=np.uint16)), refresh=True)
    assert not raw.any()


def test_cache_is_never_reused_across_bboxes(tmp_path):
    f = Fetcher(good_raw())
    cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)
    other = (-97.0, 27.80, -96.99, 27.8101)           # same port name, slightly different box and a different grid shape (112 rows, not 111)
    f2 = Fetcher(cop.encode_db(np.full(cop.grid(other)[::-1], -20.0)))
    cop.get_pass(tmp_path, "tiny", other, scene(), f2)
    assert f2.calls == 1


def test_cached_file_with_wrong_bbox_or_shape_is_refused(tmp_path):
    f = Fetcher(good_raw())
    cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)
    path = cop.pass_path(tmp_path, "tiny", cop.grid_id(TINY_BBOX), "S1A_X")
    np.savez_compressed(path, raw=good_raw(), bbox=np.array([1.0, 2.0, 3.0, 4.0]), shape=np.array(TINY_SHAPE))
    with pytest.raises(cop.CacheMismatchError):
        cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), f)


def test_fetch_result_with_wrong_shape_is_refused(tmp_path):
    with pytest.raises(cop.UnexpectedResponseError):
        cop.get_pass(tmp_path, "tiny", TINY_BBOX, scene(), Fetcher(np.zeros((5, 5), dtype=np.uint16)))


class Resp:
    def __init__(self, payload, ok=True, status=200):
        self.payload, self.ok, self.status_code, self.text = payload, ok, status, str(payload)

    def json(self):
        return self.payload


def test_token_is_reused_then_refreshed_inside_the_last_60_seconds():
    posts, now = [], [1000.0]

    def post(url, data=None, timeout=None):
        posts.append(data)
        return Resp({"access_token": f"tok{len(posts)}", "expires_in": 300})

    ts = cop.TokenSource("id", "secret", post=post, clock=lambda: now[0])
    assert ts.get() == "tok1" and ts.get() == "tok1" and len(posts) == 1
    now[0] += 239                                      # 61 s left
    assert ts.get() == "tok1" and len(posts) == 1
    now[0] += 2                                        # 59 s left
    assert ts.get() == "tok2" and len(posts) == 2
    assert posts[0]["grant_type"] == "client_credentials"


def test_token_response_without_access_token_is_named():
    ts = cop.TokenSource("id", "secret", post=lambda *a, **k: Resp({"error": "bad"}), clock=lambda: 0.0)
    with pytest.raises(cop.UnexpectedResponseError, match="access_token"):
        ts.get()


def test_token_error_is_loud():
    ts = cop.TokenSource("id", "secret", post=lambda *a, **k: Resp({"error": "bad"}, ok=False, status=401),
                         clock=lambda: 0.0)
    with pytest.raises(RuntimeError, match="401"):
        ts.get()


def product(name, start):
    return {"Name": name, "ContentDate": {"Start": start, "End": start},
            "Attributes": [{"Name": "orbitDirection", "Value": "ASCENDING"},
                           {"Name": "relativeOrbitNumber", "Value": 107}]}


def test_search_pages_with_skip_until_exhausted_and_dedupes_cog_copies():
    pages = [
        [product("S1A_IW_GRDH_1SDV_20260401T003438_20260401T003503_000001_AAAA_1111.SAFE", "2026-04-01T00:34:38.000Z"),
         product("S1A_IW_GRDH_1SDV_20260401T003438_20260401T003503_000001_AAAA_2222_COG.SAFE", "2026-04-01T00:34:38.000Z")],
        [product("S1A_IW_GRDH_1SDV_20260320T003438_20260320T003503_000002_BBBB_3333.SAFE", "2026-03-20T00:34:38.000Z"),
         product("S1A_IW_GRDH_1SDV_20260308T003438_20260308T003503_000003_CCCC_4444.SAFE", "2026-03-08T00:34:38.000Z")],
        [product("S1A_IW_GRDH_1SDV_20260224T003438_20260224T003503_000004_DDDD_5555.SAFE", "2026-02-24T00:34:38.000Z")],
    ]
    skips = []

    def get(url, params=None, timeout=None):
        skips.append(params["$skip"])
        return Resp({"value": pages[len(skips) - 1]})

    out = cop.search("SENTINEL-1", "IW_GRDH", TINY_BBOX, datetime(2026, 1, 1, tzinfo=timezone.utc),
                     page_size=2, get=get)
    assert skips == [0, 2, 4]
    assert len(out) == 4                               # 5 products, one acquisition had a COG twin
    assert out[0]["image_id"].endswith("_1111") and out[0]["relative_orbit"] == 107
    assert [s["start"].strftime("%m-%d") for s in out] == ["04-01", "03-20", "03-08", "02-24"]


def test_search_response_without_value_is_named():
    with pytest.raises(cop.UnexpectedResponseError, match="value"):
        cop.search("SENTINEL-1", "IW_GRDH", TINY_BBOX, datetime(2026, 1, 1, tzinfo=timezone.utc),
                   get=lambda *a, **k: Resp({"unexpected": 1}))


def test_search_orders_ties_by_name():
    seen = []

    def get(url, params=None, timeout=None):
        seen.append(params["$orderby"])
        return Resp({"value": []})
    cop.search("SENTINEL-1", "IW_GRDH", TINY_BBOX, datetime(2026, 1, 1, tzinfo=timezone.utc), get=get)
    assert seen == ["ContentDate/Start desc,Name asc"]


def test_search_http_error_is_loud():
    with pytest.raises(RuntimeError, match="500"):
        cop.search("SENTINEL-1", "IW_GRDH", TINY_BBOX, datetime(2026, 1, 1, tzinfo=timezone.utc),
                   get=lambda *a, **k: Resp({}, ok=False, status=500))
