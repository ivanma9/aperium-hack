"""run_port: the whole per-port run, with the catalogue search, the fetch and the detector injected."""
import fcntl
import logging
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, dataset, detect
from . import copernicus as cop
from . import reference as refmod
from .fsutil import atomic_path

logger = logging.getLogger("portwatch.pipeline")


class DataDirBusyError(cop.CopernicusError):
    """Another run holds the lock on this data directory."""


@contextmanager
def _locked(data_dir):
    """Exclusive lock on data_dir/.lock for the whole run: the parquet files are read, merged and
    rewritten on every pass, so two runs on one data dir would lose each other's rows."""
    with open(data_dir / ".lock", "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataDirBusyError(f"another portwatch run is using {data_dir} (lock file {data_dir / '.lock'}); "
                                   "one run at a time per data directory") from None
        yield


def get_code_version():
    """Git short SHA of the code that produced the rows, "<sha>-dirty" if the tree has uncommitted changes."""
    root = Path(__file__).resolve().parent.parent
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _save_png(img, path):
    with atomic_path(path) as tmp:
        img.save(tmp, format="PNG")


def run_port(port, *, data_dir, **kw):
    """Count ships in every pass of the last `days` days over `port`, per relative orbit.

    search_fn(bbox, since) -> scenes newest first; fetch_fn(scene, bbox) -> raw uint16 raster.
    Appends to data_dir/ship_counts.parquet and detections.parquet after every pass, so an
    interrupted run resumes where it stopped. Returns a summary dict. Holds an exclusive lock on
    data_dir for the whole run (DataDirBusyError when another run has it).
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with _locked(data_dir):
        return _run_port(port, data_dir=data_dir, **kw)


def _run_port(port, *, days, data_dir, search_fn, fetch_fn, detect_fn=detect.detect_ships, refresh=False,
              now=None, code_version=None, log=print):
    now = now or datetime.now(timezone.utc)
    code_version = code_version or get_code_version()
    ref_from_s, ref_to_s = port.reference_window
    ref_from, ref_to = cop.parse_time(ref_from_s), cop.parse_time(ref_to_s)
    since = now - timedelta(days=days)
    pct = config.REFERENCE_PCT
    params, phash = config.detection_params(), config.params_hash()
    gid = cop.grid_id(port.bbox)
    counts_path, dets_path = data_dir / "ship_counts.parquet", data_dir / "detections.parquet"
    refreshed = set()

    def fetch(scene):
        """Pass raster from the cache, or fetched (and cached when it has data)."""
        again = refresh and scene["image_id"] not in refreshed
        path = cop.pass_path(data_dir, port.name, gid, scene["image_id"])
        if again or not path.exists():
            log(f"  fetching {scene['platform']} {scene['start']:%Y-%m-%d %H:%M}Z "
                f"({scene['image_id'][-14:]}); about 15 PU")
        refreshed.add(scene["image_id"])
        return cop.get_pass(data_dir, port.name, port.bbox, scene, fetch_fn, refresh=again)

    scenes = search_fn(port.bbox, min(ref_from, since))
    by_orbit = {}
    for s in scenes:
        if s.get("relative_orbit") is not None:
            by_orbit.setdefault(s["relative_orbit"], []).append(s)
    log(f"{port.name}: {len(scenes)} Sentinel-1 pass(es) found, relative orbit(s) {sorted(by_orbit) or 'none'}")

    summary = {"orbits": {}}
    for orbit in sorted(by_orbit):
        group = sorted(by_orbit[orbit], key=lambda s: s["start"])
        targets = [s for s in group if s["start"] >= since]
        if not targets:
            continue
        info = summary["orbits"][orbit] = {"status": "ok", "processed": 0, "skipped": 0}

        # -- reference for this (port, orbit): passes of this orbit inside the reference window
        ref_ids = []
        for s in (s for s in group if ref_from <= s["start"] < ref_to):
            cached = cop.pass_path(data_dir, port.name, gid, s["image_id"]).exists() and not refresh
            if cached or fetch(s).any():       # only passes with data are ever cached
                ref_ids.append(s["image_id"])
            else:
                log(f"orbit {orbit}: reference pass {s['image_id']} has no data (it may not be processed yet); "
                    "left out of the reference")
        info["n_reference"] = len(ref_ids)
        if len(ref_ids) < config.MIN_REF_PASSES:
            info["status"] = "insufficient_reference"
            log(f"orbit {orbit}: only {len(ref_ids)} pass(es) with data in the reference window "
                f"{ref_from_s[:10]} to {ref_to_s[:10]}; need {config.MIN_REF_PASSES}. Not counting this orbit.")
            continue
        boxes = [e.bbox for e in port.exclude]
        rid = refmod.compute_reference_id(gid, orbit, ref_from_s, ref_to_s, pct, ref_ids, exclude=boxes)
        info["reference_id"] = rid
        ref_file = refmod.reference_path(data_dir, port.name, gid, rid)
        if ref_file.exists() and not refresh:
            ref = refmod.load_reference(ref_file)
        else:
            by_id = {s["image_id"]: s for s in group}
            ref = refmod.build_reference([fetch(by_id[i]) for i in ref_ids], pct)
            refmod.save_reference(ref_file, ref)
            log(f"orbit {orbit}: built reference {rid} from {len(ref_ids)} passes")
        p_ref = ref[f"p{pct}"]

        # The water mask depends on settings that are part of params_hash, so it is never cached with the reference.
        water = detect.apply_exclusions(detect.water_mask(p_ref), port.bbox, boxes)
        if not water.any():
            info["status"] = "no_water"
            log(f"orbit {orbit}: no water in the reference (WATER_DB {config.WATER_DB:g} dB"
                f"{', after the exclude boxes' if boxes else ''}); not counting this orbit.")
            continue

        absorbed, n_absorbed = refmod.absorbed_berths(p_ref, ref["min"])
        n_blobs, largest_m2 = refmod.blob_stats(absorbed)
        info["absorbed_pixels"] = n_absorbed
        map_path = data_dir / "overlays" / port.name / f"absorbed_orbit{orbit}_{rid}.png"
        refmod.save_absorbed_map(map_path, p_ref, absorbed)             # cheap, so always rewritten
        log(f"orbit {orbit}: {n_absorbed} water pixel(s) where p{pct} > {config.SHIP_DB:g} dB and "
            f"p{pct} - min > {config.ABSORBED_DB:g} dB (possibly absorbed berths), {n_blobs} blob(s), "
            f"largest {largest_m2:.0f} m2; map {map_path}")

        # -- the passes themselves, oldest first
        for scene in targets:
            image_id = scene["image_id"]
            if not refresh and dataset.is_done(counts_path, port.name, image_id, phash, rid):
                info["skipped"] += 1
                continue
            stamp = f"{scene['start']:%Y%m%dT%H%M%SZ}"
            log(f"{stamp} {image_id}")
            db = cop.decode_db(fetch(scene))
            valid = np.isfinite(db) & np.isfinite(p_ref)
            coverage = float(valid.mean())
            row = {"port": port.name, "timestamp_utc": scene["start"], "satellite": scene["platform"],
                   "relative_orbit": orbit, "orbit_direction": scene["orbit_direction"], "image_id": image_id,
                   "coverage": round(coverage, 4), "water_coverage": 0.0, "ship_count": None,
                   "n_rejected_large": None, "cal_proxy_db": np.nan, "sea_state_db": np.nan,
                   "in_reference_period": image_id in ref_ids,
                   "code_version": code_version, "params_hash": phash, "reference_id": rid,
                   **{f"p_{k.lower()}": v for k, v in params.items()}}
            dets = pd.DataFrame()
            if coverage == 0:
                log(f"  {stamp}: no data (it may not be processed yet); ship_count left empty, will retry next run")
            else:
                if coverage < 0.5:
                    log(f"  WARNING {stamp}: covers only {coverage:.0%} of the area; count not comparable to a full pass")
                cal, sea = detect.qc_columns(db, ref, water)
                row.update(water_coverage=round(float(np.isfinite(db)[water].mean()), 4), cal_proxy_db=cal,
                           sea_state_db=sea)
                if not (water & valid).any():
                    log(f"  {stamp}: this pass images no reference water (coverage {coverage:.0%}); "
                        "ship_count left empty, will retry next run")
                    _save_png(detect.draw_overlay(db, water & valid, [], config.RES_M),
                              data_dir / "overlays" / port.name / f"{stamp}_orbit{orbit}.png")
                else:
                    res = detect_fn(db, p_ref, water=water)
                    row.update(ship_count=len(res.ships), n_rejected_large=res.n_rejected_large)
                    _save_png(detect.draw_overlay(db, water & res.valid, res.ships, config.RES_M),
                              data_dir / "overlays" / port.name / f"{stamp}_orbit{orbit}.png")
                    recs = []
                    for i, s in enumerate(res.ships):
                        lon, lat = detect.pixel_to_lonlat(port.bbox, db.shape, s["row"], s["col"])
                        recs.append({"port": port.name, "timestamp_utc": scene["start"], "image_id": image_id,
                                     "det_id": f"{image_id}-{i}", "lon": round(lon, 5), "lat": round(lat, 5),
                                     "area_m2": round(s["area_m2"]), "peak_db": round(s["peak_db"], 1),
                                     "length_m": round(s["length_m"]), "width_m": round(s["width_m"]),
                                     "orientation_deg": round(s["orientation_deg"], 1), "n_parts": s["n_parts"],
                                     "params_hash": phash, "reference_id": rid})
                    dets = pd.DataFrame(recs)
                    log(f"  {stamp}: coverage {coverage:.0%}, {len(res.ships)} ship-like target(s), "
                        f"{res.n_rejected_large} oversize rejected, cal {cal:+.2f} dB, sea {sea:+.2f} dB")
            # detections first: a crash between the two writes leaves the pass undone, so it is redone.
            # The purge always runs, so a null count never leaves the targets of an earlier run behind.
            dataset.append(dets_path, dets, key=dataset.DET_KEY, purge=pd.DataFrame([row]))
            dataset.append(counts_path, pd.DataFrame([row]))
            info["processed"] += 1
    return summary
