"""Subprocess helper: run the FakeWorld pipeline with config.WATER_DB set before portwatch is imported,
as if config.py had been edited before the process started. Prints one JSON line.

usage: _world_run.py WATER_DB DATA_DIR
"""
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "tests")]
water_db, data_dir = float(sys.argv[1]), sys.argv[2]

import portwatch.config as cfg

cfg.WATER_DB = water_db

from conftest import NOW, UTC, FakeWorld, aux_tiny_port, every_12_days, two_level_background
from portwatch import dataset
from portwatch.pipeline import run_port

REF = every_12_days(datetime(2026, 1, 1, 0, 34, 38, tzinfo=UTC), 6)
TGT = [datetime(2026, 4, 1, 0, 34, 38, tzinfo=UTC), datetime(2026, 4, 13, 0, 34, 38, tzinfo=UTC)]
w = FakeWorld({107: (REF, TGT)}, background=two_level_background)
run_port(aux_tiny_port(), days=30, data_dir=data_dir, search_fn=w.search, fetch_fn=w.fetch, now=NOW,
         code_version="t", log=lambda *a, **k: None)
df = dataset.read(Path(data_dir) / "ship_counts.parquet")
df = df[df["p_water_db"] == water_db].sort_values("timestamp_utc")
print(json.dumps({"params_hash": df["params_hash"].iloc[0], "ship_count": [int(v) for v in df["ship_count"]]}))
