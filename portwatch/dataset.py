"""Parquet outputs: append, dedupe, atomic write."""
from pathlib import Path

import pandas as pd

from .fsutil import atomic_path

PASS_KEY = ["port", "image_id", "params_hash", "reference_id"]
DET_KEY = PASS_KEY + ["det_id"]
NULLABLE_INT = ("ship_count", "n_rejected_large")   # null when the pass had no data


def normalise(df):
    """UTC nanosecond timestamps and nullable integer counts, whatever the caller passed."""
    df = df.copy()
    if "timestamp_utc" in df:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True).astype("datetime64[ns, UTC]")
    for col in NULLABLE_INT:
        if col in df:
            df[col] = pd.array(list(df[col]), dtype="Int64")
    return df


def read(path):
    path = Path(path)
    return normalise(pd.read_parquet(path)) if path.exists() else pd.DataFrame()


def _keys(df, cols):
    return list(zip(*(df[c] for c in cols))) if len(df) else []


def append(path, df, key=PASS_KEY, purge=None):
    """Add rows, newer rows win on `key`. `purge` (a frame with PASS_KEY columns) first removes every
    existing row of those passes, so a re-run that finds fewer targets leaves no stale rows."""
    path = Path(path)
    old = read(path)
    if purge is not None and len(old) and len(purge):
        drop = set(_keys(purge, PASS_KEY))
        old = old[[k not in drop for k in _keys(old, PASS_KEY)]]
    parts = [x for x in (old, normalise(df)) if len(x)]
    if not parts:
        if path.exists():
            _write(path, old)
        return
    combined = pd.concat(parts, ignore_index=True).drop_duplicates(subset=key, keep="last").reset_index(drop=True)
    _write(path, normalise(combined))


def _write(path, df):
    with atomic_path(path) as tmp:
        df.to_parquet(tmp, index=False)


def is_done(path, port, image_id, params_hash, reference_id):
    """True when this pass has a row with a count for exactly these parameters and reference.
    A null count (the pass had no data yet) is never done, so it is fetched again."""
    df = read(path)
    if not len(df):
        return False
    hit = ((df["port"] == port) & (df["image_id"] == image_id) & (df["params_hash"] == params_hash)
           & (df["reference_id"] == reference_id))
    return bool(df.loc[hit, "ship_count"].notna().any())
