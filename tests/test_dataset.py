import os

import numpy as np
import pandas as pd
import pytest

from portwatch import config, dataset
from portwatch import copernicus as cop


def pass_row(image_id="img1", count=3, params_hash="aaa", reference_id="r1", port="p", coverage=1.0):
    return pd.DataFrame({
        "port": [port], "timestamp_utc": [pd.Timestamp("2026-04-01T00:34:38Z")], "satellite": ["S1A"],
        "relative_orbit": [107], "orbit_direction": ["ASCENDING"], "image_id": [image_id],
        "coverage": [coverage], "ship_count": pd.array([count], dtype="Int64"),
        "params_hash": [params_hash], "reference_id": [reference_id],
    })


def read_n(path, n):
    df = dataset.read(path)
    assert len(df) == n
    return df


def two_rows():
    return pd.concat([pass_row("img1", 3), pass_row("img2", 5)], ignore_index=True)


def test_14_append_twice_dedupes_and_newer_wins(tmp_path):
    path = tmp_path / "ship_counts.parquet"
    dataset.append(path, two_rows())
    dataset.append(path, two_rows())
    assert len(dataset.read(path)) == 2
    dataset.append(path, pass_row("img1", 9))
    df = read_n(path, 2).set_index("image_id")
    assert df.loc["img1", "ship_count"] == 9 and df.loc["img2", "ship_count"] == 5


def test_15_null_count_and_utc_survive_a_round_trip(tmp_path):
    path = tmp_path / "ship_counts.parquet"
    dataset.append(path, pd.concat([pass_row("img1", None, coverage=0.0), pass_row("img2", 0)], ignore_index=True))
    df = read_n(path, 2).set_index("image_id")
    assert str(df.loc["img1", "ship_count"]) == "<NA>"
    assert df.loc["img2", "ship_count"] == 0           # zero is not null
    assert str(df["ship_count"].dtype) == "Int64"
    assert str(df["timestamp_utc"].dtype) == "datetime64[ns, UTC]"


def test_16_different_params_hash_keeps_both(tmp_path):
    path = tmp_path / "ship_counts.parquet"
    dataset.append(path, pass_row("img1", 3, params_hash="aaa"))
    dataset.append(path, pass_row("img1", 4, params_hash="bbb"))
    assert sorted(read_n(path, 2)["ship_count"]) == [3, 4]


def test_25_different_reference_id_is_a_new_row_and_not_done(tmp_path):
    path = tmp_path / "ship_counts.parquet"
    dataset.append(path, pass_row("img1", 3, reference_id="r1"))
    assert dataset.is_done(path, "p", "img1", "aaa", "r1")
    assert not dataset.is_done(path, "p", "img1", "aaa", "r2")
    assert not dataset.is_done(path, "p", "img1", "zzz", "r1")
    assert not dataset.is_done(path, "other", "img1", "aaa", "r1")
    dataset.append(path, pass_row("img1", 4, reference_id="r2"))
    assert len(dataset.read(path)) == 2


def test_26a_null_count_is_never_done(tmp_path):
    path = tmp_path / "ship_counts.parquet"
    assert not dataset.is_done(path, "p", "img1", "aaa", "r1")      # no file yet
    dataset.append(path, pass_row("img1", None, coverage=0.0))
    assert not dataset.is_done(path, "p", "img1", "aaa", "r1")
    dataset.append(path, pass_row("img1", 2))                       # replaces the null row
    assert dataset.is_done(path, "p", "img1", "aaa", "r1")
    assert len(dataset.read(path)) == 1


def det_rows(image_id, n):
    return pd.DataFrame({"port": ["p"] * n, "image_id": [image_id] * n, "params_hash": ["aaa"] * n,
                         "reference_id": ["r1"] * n, "det_id": [f"{image_id}-{i}" for i in range(n)],
                         "lon": [-97.0] * n, "lat": [27.8] * n})


def test_detections_of_a_rerun_replace_the_old_ones(tmp_path):
    path = tmp_path / "detections.parquet"
    dataset.append(path, det_rows("img1", 3), key=dataset.DET_KEY, purge=pass_row("img1"))
    dataset.append(path, det_rows("img2", 1), key=dataset.DET_KEY, purge=pass_row("img2"))
    dataset.append(path, det_rows("img1", 1), key=dataset.DET_KEY, purge=pass_row("img1"))   # rerun found fewer
    df = read_n(path, 2)
    assert sorted(df["image_id"]) == ["img1", "img2"]
    dataset.append(path, det_rows("img1", 0), key=dataset.DET_KEY, purge=pass_row("img1"))   # rerun found none
    assert list(read_n(path, 1)["image_id"]) == ["img2"]


def test_write_is_atomic_no_partial_file_left(tmp_path):
    path = tmp_path / "ship_counts.parquet"
    dataset.append(path, two_rows())
    assert [p.name for p in tmp_path.iterdir()] == ["ship_counts.parquet"]


def test_params_hash():
    h = config.params_hash()
    assert len(h) == 12 and int(h, 16) >= 0
    assert h == config.params_hash(dict(reversed(list(config.detection_params().items()))))
    assert h != config.params_hash({**config.detection_params(), "SHIP_DB": -4.0})


def record_replace_sources(monkeypatch):
    sources, real = [], os.replace

    def spy(src, dst, *a, **k):
        sources.append(os.fspath(src))
        return real(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", spy)
    return sources


def test_m1_two_appends_use_distinct_tmp_names_in_the_same_directory(tmp_path, monkeypatch):
    sources = record_replace_sources(monkeypatch)
    path = tmp_path / "sub" / "ship_counts.parquet"
    dataset.append(path, pass_row("img1"))
    dataset.append(path, pass_row("img2"))
    assert len(sources) == 2 and len(set(sources)) == 2
    assert all(os.path.dirname(s) == str(path.parent) for s in sources)
    assert [p.name for p in path.parent.iterdir()] == ["ship_counts.parquet"]


def test_m1_two_savez_use_distinct_tmp_names_in_the_same_directory(tmp_path, monkeypatch):
    sources = record_replace_sources(monkeypatch)
    path = tmp_path / "cache" / "x.npz"
    cop.atomic_savez(path, a=np.arange(3))
    cop.atomic_savez(path, a=np.arange(4))
    assert len(sources) == 2 and len(set(sources)) == 2
    assert all(os.path.dirname(s) == str(path.parent) for s in sources)
    assert [p.name for p in path.parent.iterdir()] == ["x.npz"]


def test_failed_write_leaves_neither_target_nor_tmp(tmp_path, monkeypatch):
    path = tmp_path / "ship_counts.parquet"

    def boom(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError):
        dataset.append(path, pass_row("img1"))
    assert list(tmp_path.iterdir()) == []
