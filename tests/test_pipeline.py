import fcntl
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import (NOW, UTC, FakeWorld, aux_tiny_port, every_12_days, half_land_background,
                      land_background, qc_background)
from portwatch import config, copernicus as cop, dataset, detect, pipeline
from portwatch.pipeline import run_port
from portwatch.ports import Exclusion

REF_DATES = every_12_days(datetime(2026, 1, 1, 0, 34, 38, tzinfo=UTC), 6)      # Jan 1 .. Mar 2
TARGETS = [datetime(2026, 4, 1, 0, 34, 38, tzinfo=UTC), datetime(2026, 4, 13, 0, 34, 38, tzinfo=UTC)]


def world(**kw):
    return FakeWorld({107: (REF_DATES, TARGETS)}, **kw)


def go(w, tmp_path, port=None, detect_fn=detect.detect_ships, days=30, log=lambda *a, **k: None, **kw):
    return run_port(port or aux_tiny_port(), days=days, data_dir=tmp_path, search_fn=w.search, fetch_fn=w.fetch,
                    detect_fn=detect_fn, now=NOW, code_version="test", log=log, **kw)


class Spy:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        return detect.detect_ships(*a, **k)


def status(summary, orbit=107):
    return summary["orbits"].get(orbit, {}).get("status")


def counts(tmp_path):
    return dataset.read(tmp_path / "ship_counts.parquet")


def test_run_counts_the_ship_and_writes_every_column(tmp_path):
    w = world()
    summary = go(w, tmp_path)
    assert status(summary) == "ok"
    df = counts(tmp_path)
    assert len(df) == 2
    assert list(df["ship_count"]) == [1, 1]
    expected = {"port", "timestamp_utc", "satellite", "relative_orbit", "orbit_direction", "image_id", "coverage",
                "water_coverage", "ship_count", "n_rejected_large", "cal_proxy_db", "sea_state_db",
                "in_reference_period", "code_version", "params_hash", "reference_id"}
    expected |= {"p_" + k.lower() for k in config.DETECTION_KEYS}
    assert expected <= set(df.columns)
    row = df.iloc[0]
    assert row["port"] == "tiny" and row["relative_orbit"] == 107 and row["code_version"] == "test"
    assert row["params_hash"] == config.params_hash() and not row["in_reference_period"]
    assert row["coverage"] == pytest.approx(1.0) and row["water_coverage"] == pytest.approx(1.0)
    assert str(row["timestamp_utc"]) == "2026-04-01 00:34:38+00:00"
    dets = dataset.read(tmp_path / "detections.parquet")
    assert len(dets) == 2 and set(dets["area_m2"]) == {12000.0}
    assert dets["lon"].between(-97.0, -96.99).all() and dets["lat"].between(27.80, 27.81).all()
    assert {"det_id", "length_m", "width_m", "orientation_deg", "n_parts", "reference_id", "params_hash"} <= set(dets.columns)
    assert dets["det_id"].is_unique
    assert (tmp_path / "overlays" / "tiny" / "20260401T003438Z_orbit107.png").exists()
    assert list((tmp_path / "overlays" / "tiny").glob("absorbed_orbit107_*.png"))


def test_23_resume_skips_done_passes_without_fetch_detect_or_writes(tmp_path):
    go(world(), tmp_path)
    path = tmp_path / "ship_counts.parquet"
    assert path.exists()
    before = path.stat().st_mtime_ns
    w2, spy = world(), Spy()
    go(w2, tmp_path, detect_fn=spy)
    assert w2.calls == []                       # target and reference passes are cached or done
    assert spy.calls == 0
    assert path.stat().st_mtime_ns == before and len(counts(tmp_path)) == 2


def test_25_new_reference_recomputes_without_refetching(tmp_path):
    go(world(), tmp_path)
    shorter = aux_tiny_port(reference_to="2026-02-20T00:00:00Z")      # 5 passes instead of 6
    w2, spy = world(), Spy()
    go(w2, tmp_path, port=shorter, detect_fn=spy)
    assert w2.calls == [] and spy.calls == 2
    df = counts(tmp_path)
    assert len(df) == 4 and df["reference_id"].nunique() == 2


def test_26_no_data_pass_is_retried_then_left_alone(tmp_path):
    w = world()
    w.nodata_once = {s["image_id"] for s in w.scenes if s["start"] == TARGETS[0]}
    target0 = next(iter(w.nodata_once))
    go(w, tmp_path)
    assert len(counts(tmp_path)) == 2
    df = counts(tmp_path).set_index("image_id")
    assert str(df.loc[target0, "ship_count"]) == "<NA>" and df.loc[target0, "coverage"] == 0
    assert not list((tmp_path / "cache").rglob(f"{target0}.npz"))     # not cached
    w.calls.clear()
    go(w, tmp_path)
    assert w.calls == [target0]                                       # only the empty pass is fetched again
    assert len(counts(tmp_path)) == 2
    df = counts(tmp_path).set_index("image_id")
    assert df.loc[target0, "ship_count"] == 1
    w.calls.clear()
    go(w, tmp_path)
    assert w.calls == []


def test_refresh_refetches_everything(tmp_path):
    go(world(), tmp_path)
    w2 = world()
    go(w2, tmp_path, refresh=True)
    assert len(w2.calls) == 8 and len(counts(tmp_path)) == 2


def test_too_few_reference_passes_means_no_count(tmp_path):
    w = FakeWorld({107: (REF_DATES[:2], TARGETS)})
    summary = go(w, tmp_path)
    assert status(summary) == "insufficient_reference"
    assert not (tmp_path / "ship_counts.parquet").exists()
    assert all("20260401" not in c and "20260413" not in c for c in w.calls)      # target passes never fetched


def test_each_orbit_gets_its_own_reference_and_one_bad_orbit_does_not_block_the_other(tmp_path):
    w = FakeWorld({107: (REF_DATES, TARGETS), 14: (REF_DATES[:2], TARGETS)})
    summary = go(w, tmp_path)
    assert status(summary, 107) == "ok" and status(summary, 14) == "insufficient_reference"
    df = counts(tmp_path)
    assert set(df["relative_orbit"]) == {107} and len(df) == 2


def test_two_good_orbits_have_distinct_reference_ids(tmp_path):
    w = FakeWorld({107: (REF_DATES, TARGETS), 14: (REF_DATES, TARGETS)})
    go(w, tmp_path)
    df = counts(tmp_path)
    assert len(df) == 4 and df.groupby("relative_orbit")["reference_id"].nunique().eq(1).all()
    assert df["reference_id"].nunique() == 2


# ---------------------------------------------------------------- C1: the water mask is never cached

WORLD_RUN = Path(__file__).with_name("_world_run.py")


def run_world(water_db, data_dir):
    """The pipeline in a fresh process whose config.WATER_DB was set before portwatch was imported."""
    out = subprocess.run([sys.executable, str(WORLD_RUN), str(water_db), str(data_dir)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_c1_changed_water_db_is_not_stuck_to_a_cached_reference(tmp_path):
    a18 = run_world(-18.0, tmp_path / "a")
    a30 = run_world(-30.0, tmp_path / "a")           # same data dir: the reference is loaded from disk
    b30 = run_world(-30.0, tmp_path / "b")           # fresh data dir
    assert a18["params_hash"] != a30["params_hash"]
    assert a18["ship_count"] == [1, 1]               # at -18 the whole raster is water, ship included
    assert b30["ship_count"] == [0, 0]               # at -30 the ship sits on "land"
    assert a30["ship_count"] == b30["ship_count"]


def test_c1_reference_file_holds_no_water_mask(tmp_path):
    go(world(), tmp_path)
    (ref_file,) = (tmp_path / "cache").rglob("reference_*.npz")
    with np.load(ref_file) as z:
        assert "water" not in z.files
        assert {"p25", "p50", "p75", "min", "n_samples"} <= set(z.files)


# ---------------------------------------------------------------- I1: no imaged water is a null count

def test_i1_land_only_track_is_no_water_and_writes_no_rows(tmp_path):
    logs = []
    summary = go(FakeWorld({107: (REF_DATES, TARGETS)}, background=land_background), tmp_path, log=logs.append)
    assert status(summary) == "no_water"
    assert not (tmp_path / "ship_counts.parquet").exists()
    assert not (tmp_path / "detections.parquet").exists()
    assert any("no water" in line for line in logs)


def test_i1_pass_whose_valid_area_misses_all_the_water_has_a_null_count(tmp_path):
    w = FakeWorld({107: (REF_DATES, TARGETS)}, background=half_land_background)
    for s in w.scenes:
        if s["start"] in TARGETS:
            w.rasters[s["image_id"]][:, :49] = cop.NODATA        # the pass only covers the land half
    logs = []
    summary = go(w, tmp_path, log=logs.append)
    assert status(summary) == "ok"
    df = counts(tmp_path)
    assert len(df) == 2
    assert df["ship_count"].isna().all() and df["n_rejected_large"].isna().all()
    assert (df["water_coverage"] == 0).all() and df["coverage"].between(0.4, 0.6).all()
    assert any("images no reference water" in line for line in logs)


# ---------------------------------------------------------------- I2: a refresh never replaces good data with null

def test_i2_refresh_with_an_empty_refetch_raises_and_keeps_old_rows_and_cache(tmp_path):
    go(world(), tmp_path)
    before = counts(tmp_path)
    cache = {p: p.read_bytes() for p in (tmp_path / "cache").rglob("*.npz")}
    w2 = world()
    target0 = next(s["image_id"] for s in w2.scenes if s["start"] == TARGETS[0])
    w2.nodata_once = {target0}
    with pytest.raises(cop.CopernicusError, match=target0):
        go(w2, tmp_path, refresh=True)
    pd.testing.assert_frame_equal(counts(tmp_path), before)
    assert {p: p.read_bytes() for p in (tmp_path / "cache").rglob("*.npz")} == cache


def test_i2_null_row_for_a_pass_that_had_detections_purges_them(tmp_path):
    go(world(), tmp_path)
    w2 = world()
    target0 = next(s["image_id"] for s in w2.scenes if s["start"] == TARGETS[0])
    assert (dataset.read(tmp_path / "detections.parquet")["image_id"] == target0).sum() == 1
    w2.nodata_once = {target0}
    for p in (tmp_path / "cache").rglob(f"{target0}.npz"):
        p.unlink()                                             # nothing cached, so the empty refetch is accepted
    go(w2, tmp_path, refresh=True)
    assert str(counts(tmp_path).set_index("image_id").loc[target0, "ship_count"]) == "<NA>"
    dets = dataset.read(tmp_path / "detections.parquet")
    assert (dets["image_id"] == target0).sum() == 0 and len(dets) == 1


# ---------------------------------------------------------------- I4: the log tells which pass is which

def test_i4_pass_line_names_the_image(tmp_path):
    logs = []
    go(world(), tmp_path, log=logs.append)
    assert "20260401T003438Z S1A_IW_GRDH_1SDV_20260401T003438_107" in [line.strip() for line in logs]


# ---------------------------------------------------------------- I5: calibration proxy on stable targets

def qc_world(stable_rows, offset):
    def mutate(db, start, is_target):
        if is_target:
            db += offset
    return FakeWorld({107: ([datetime(2026, 1, 1, 0, 34, 38, tzinfo=UTC) + timedelta(days=5 * i) for i in range(12)],
                            TARGETS)},
                     background=qc_background(stable_rows), mutate=mutate)


@pytest.mark.parametrize("offset", [1.0, 0.0])
def test_i5_cal_proxy_follows_stable_targets_not_noisy_land(tmp_path, offset):
    go(qc_world(stable_rows=55, offset=offset), tmp_path)
    df = counts(tmp_path)
    assert len(df) == 2
    assert df["cal_proxy_db"].tolist() == pytest.approx([offset, offset], abs=0.1)
    assert df["sea_state_db"].tolist() == pytest.approx([offset, offset], abs=0.1)


def test_i5_fewer_than_100_stable_pixels_gives_nan(tmp_path):
    go(qc_world(stable_rows=1, offset=1.0), tmp_path)               # 1 row x 48 cols = 48 stable pixels
    df = counts(tmp_path)
    assert df["cal_proxy_db"].isna().all()
    assert df["sea_state_db"].tolist() == pytest.approx([1.0, 1.0], abs=0.1)


def test_i5_qc_parameters_are_part_of_params_hash(monkeypatch):
    base = config.params_hash()
    for key in ("STABLE_MIN_DB", "STABLE_IQR_DB"):
        monkeypatch.setattr(config, key, getattr(config, key) + 0.5)
        assert config.params_hash() != base, key
        monkeypatch.undo()


# ---------------------------------------------------------------- X1: exclusion boxes

BOX_OVER_SHIP = (-97.0, 27.804, -96.994, 27.806)        # rows ~45-66, cols 0-58 of the tiny port


class WaterSpy:
    def __init__(self):
        self.water = None

    def __call__(self, db, ref, water=None, **k):
        self.water = water
        return detect.detect_ships(db, ref, water=water, **k)


def test_x1_ship_inside_an_exclude_box_is_not_counted_and_water_is_false_there(tmp_path):
    spy = WaterSpy()
    port = aux_tiny_port(exclude=(Exclusion(BOX_OVER_SHIP, "runway"),))
    go(world(), tmp_path, port=port, detect_fn=spy)
    assert list(counts(tmp_path)["ship_count"]) == [0, 0]
    assert not spy.water[50:56, 30:50].any()
    assert spy.water[0:40, :].all() and spy.water[70:, :].all()      # untouched outside the box


def test_x1_changing_the_exclude_list_changes_reference_id_and_recomputes(tmp_path):
    go(world(), tmp_path)
    go(world(), tmp_path, port=aux_tiny_port(exclude=(Exclusion(BOX_OVER_SHIP, "runway"),)))
    df = counts(tmp_path)
    assert len(df) == 4 and df["reference_id"].nunique() == 2
    assert sorted(df["ship_count"]) == [0, 0, 1, 1]


# ---------------------------------------------------------------- M1: one run at a time per data dir

def test_m1_a_second_run_on_a_locked_data_dir_is_refused(tmp_path):
    with open(tmp_path / ".lock", "a") as other:
        fcntl.flock(other, fcntl.LOCK_EX)
        with pytest.raises(pipeline.DataDirBusyError):
            go(world(), tmp_path)
    assert not (tmp_path / "ship_counts.parquet").exists()
    go(world(), tmp_path)                                 # the lock is released with the other holder
    assert len(counts(tmp_path)) == 2


def test_m1_lock_is_released_when_a_run_fails(tmp_path):
    def boom(*a, **k):
        raise cop.CopernicusError("boom")
    with pytest.raises(cop.CopernicusError):
        go(world(), tmp_path, detect_fn=boom)
    with open(tmp_path / ".lock", "a") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)         # would raise if the run still held it



# ---------------------------------------------------------------- M3, M4: reference passes without data

def dead_reference_world():
    w = world()
    dead = next(s["image_id"] for s in w.scenes if s["start"] == REF_DATES[2])
    w.rasters[dead][:] = cop.NODATA
    return w, dead


def test_m3_a_reference_pass_without_data_is_logged(tmp_path):
    w, dead = dead_reference_world()
    logs = []
    go(w, tmp_path, log=logs.append)
    assert any(dead in line and "no data" in line and "reference" in line for line in logs)


def test_m4_in_reference_period_means_the_pass_built_the_reference(tmp_path):
    w, dead = dead_reference_world()
    go(w, tmp_path, days=120)                              # every pass is a target now
    df = counts(tmp_path).set_index("image_id")
    assert len(df) == 8
    assert not df.loc[dead, "in_reference_period"]         # inside the window but not in the reference
    assert df.loc[[s["image_id"] for s in w.scenes if s["start"] in REF_DATES and s["image_id"] != dead],
                  "in_reference_period"].all()
    assert not df.loc[[s["image_id"] for s in w.scenes if s["start"] in TARGETS], "in_reference_period"].any()


# ---------------------------------------------------------------- M5: absorbed-berth map and log

def absorbed_world():
    def mutate(db, start, is_target):
        if not is_target and start != REF_DATES[0]:            # a ship moored in 5 of the 6 reference passes
            db[80:90, 10:20] = 5.0
    return FakeWorld({107: (REF_DATES, TARGETS)}, mutate=mutate)


def test_m5_log_states_the_full_rule_and_the_blobs(tmp_path):
    logs = []
    go(absorbed_world(), tmp_path, log=logs.append)
    (line,) = [line for line in logs if "absorbed" in line]
    for part in ("100 water pixel(s)", "p25 > -5 dB", "p25 - min > 10 dB", "1 blob(s)", "largest 10000 m2"):
        assert part in line, part


def test_m5_absorbed_map_is_always_regenerated(tmp_path):
    go(world(), tmp_path)
    (png,) = (tmp_path / "overlays" / "tiny").glob("absorbed_orbit107_*.png")
    png.write_bytes(b"stale")
    go(world(), tmp_path)
    assert png.read_bytes() != b"stale"


# ---------------------------------------------------------------- M9: code version

class Done:
    def __init__(self, stdout):
        self.stdout = stdout


@pytest.mark.parametrize("porcelain,expected", [("", "abc1234"), (" M portwatch/x.py\n", "abc1234-dirty")])
def test_m9_dirty_tree_keeps_the_sha(monkeypatch, porcelain, expected):
    def fake_run(cmd, **k):
        return Done("abc1234\n" if "rev-parse" in cmd else porcelain)
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    assert pipeline.get_code_version() == expected
