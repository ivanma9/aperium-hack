"""Energy-CPI nowcast: official-price baseline + Hormuz disruption shock chain.

AIS cannot measure the CPI level; it only supplies a disruption fraction.
Usage: python -m aperium.cpi_nowcast [--out outputs/latest] [--offline]
Contract v2: see aperium/contract.py (CPI, SHOCK, MONTH).
"""
import argparse
import json
import os
import calendar
import statistics
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

from .contract import SCHEMA_VERSION, validate

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
CACHE_DIR = ROOT / "cache"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_ENERGY, BLS_GASOLINE = "CUUR0000SA0E", "CUUR0000SETB01"
EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
EIA_SERIES = "EMM_EPMR_PTE_NUS_DPG"
# region -> (BLS energy, BLS gasoline, EIA weekly retail regular). PADDs only approximate census regions.
REGION_SERIES = {
    "national": (BLS_ENERGY, BLS_GASOLINE, EIA_SERIES),
    "northeast": ("CUUR0100SA0E", "CUUR0100SETB01", "EMM_EPMR_PTE_R10_DPG"),
    "midwest": ("CUUR0200SA0E", "CUUR0200SETB01", "EMM_EPMR_PTE_R20_DPG"),
    "south": ("CUUR0300SA0E", "CUUR0300SETB01", "EMM_EPMR_PTE_R30_DPG"),
    "west": ("CUUR0400SA0E", "CUUR0400SETB01", "EMM_EPMR_PTE_R50_DPG"),
}
_REGIONS_LOCK, _regions_thread = threading.Lock(), None
EIA_MISSING ="missing_key: get a free key at https://www.eia.gov/opendata/"


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def load_config(path=CONFIG_PATH):
    return yaml.safe_load(Path(path).read_text())


# ---------------------------------------------------------------- fetching / caching
def _cached(name, fetch, now, ttl_h, offline, cache_dir):
    """Return (payload, fetched_utc, status). Never raises."""
    path = Path(cache_dir) / f"{name}.json"
    cached = None
    try:
        cached = json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    if cached:
        age = now - _parse(cached["fetched_utc"])
        if offline or age < timedelta(hours=ttl_h):
            return cached["payload"], cached["fetched_utc"], "ok (cache)" if not offline else "ok (offline cache)"
    if offline:
        return None, None, "unavailable: offline and no cache"
    try:
        payload = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_utc": _iso(now), "payload": payload}))
        os.replace(tmp, path)
        return payload, _iso(now), "ok"
    except Exception as e:  # noqa: BLE001 - surface message verbatim in source status
        if cached:
            return cached["payload"], cached["fetched_utc"], f"stale_cache: {e}"
        return None, None, f"error: {e}"


def _bls_latest(series):
    """POST to BLS; {series_id: {value, period}} for the latest monthly print of each series returned."""
    r = requests.post(BLS_URL, json={"seriesid": series}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS: " + "; ".join(j.get("message") or [str(j.get("status"))]))
    out = {}
    for s in j["Results"]["series"]:
        rows = [d for d in s["data"] if d["period"].startswith("M") and d["period"] != "M13"]
        if rows:
            d = max(rows, key=lambda d: (int(d["year"]), d["period"]))
            out[s["seriesID"]] = {"value": float(d["value"]), "period": f"{d['year']}-{d['period'][1:]}"}
    return out, j


def fetch_bls():
    out, j = _bls_latest([BLS_ENERGY, BLS_GASOLINE])
    if BLS_ENERGY not in out:
        raise RuntimeError("BLS: no data returned for " + BLS_ENERGY +
                           ("; " + "; ".join(j["message"]) if j.get("message") else ""))
    return out


def fetch_bls_regions():
    out, j = _bls_latest([s for r in REGION_SERIES.values() for s in r[:2]])
    if not out:
        raise RuntimeError("BLS: no regional data returned" + ("; " + "; ".join(j["message"]) if j.get("message") else ""))
    return out


def make_fetch_eia(key):
    def fetch():
        params = {"api_key": key, "frequency": "weekly", "data[0]": "value", "facets[series][]": EIA_SERIES,
                  "sort[0][column]": "period", "sort[0][direction]": "desc", "length": 12}
        r = requests.get(EIA_URL, params=params, timeout=30)
        if not r.ok:
            raise RuntimeError(f"EIA HTTP {r.status_code}: {r.text[:300].replace(key, '***')}")
        rows = r.json()["response"]["data"]
        return [{"period": d["period"], "value": float(d["value"])} for d in rows if d.get("value") is not None]
    return fetch


def make_fetch_eia_regions(key, now):
    """{series: [{period, value}]} for the regional retail series. Multi-series ignores `length`: filter by `start`. EIA takes ~1 min for this query."""
    def fetch():
        params = {"api_key": key, "frequency": "weekly", "data[0]": "value", "start": (now - timedelta(days=120)).date().isoformat(),
                  "facets[series][]": [r[2] for r in REGION_SERIES.values()], "sort[0][column]": "period",
                  "sort[0][direction]": "desc", "length": 5000}
        r = requests.get(EIA_URL, params=params, timeout=120)
        if not r.ok:
            raise RuntimeError(f"EIA HTTP {r.status_code}: {r.text[:300].replace(key, '***')}")
        out = {}
        for d in r.json()["response"]["data"]:
            if d.get("value") is not None:
                out.setdefault(d["series"], []).append({"period": d["period"], "value": float(d["value"])})
        if not out:
            raise RuntimeError("EIA: no regional rows returned")
        return out
    return fetch


# ---------------------------------------------------------------- baseline
def _month_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def compute_baseline(bls, eia, cfg, now):
    """bls: {series: {value, period}} | None; eia: [{period,value}] | None."""
    ri = cfg["relative_importance"]
    if ri.get("energy") and ri.get("gasoline"):
        share, share_src = ri["gasoline"] / ri["energy"], "bls"
    else:
        share, share_src = cfg["gasoline_share_fallback"], "fallback"
    b = {"cpi_energy_last": None, "cpi_energy_period": None, "cpi_gasoline_last": None,
         "gasoline_share_of_energy": round(share, 4), "gasoline_share_source": share_src,
         "retail_gasoline_this_month_usd_gal": None, "retail_gasoline_last_month_usd_gal": None,
         "retail_gasoline_mom_pct": None, "nowcast_period": None, "nowcast_cpi_energy": None,
         "nowcast_mom_pct": None, "status": "unavailable"}
    if bls:
        e = bls[BLS_ENERGY]
        b["cpi_energy_last"], b["cpi_energy_period"] = e["value"], e["period"]
        if BLS_GASOLINE in bls:
            b["cpi_gasoline_last"] = bls[BLS_GASOLINE]["value"]
    # EIA weekly -> monthly averages
    months = {}
    for r in eia or []:
        months.setdefault(r["period"][:7], []).append(r["value"])
    avg = {m: statistics.mean(v) for m, v in months.items()}
    cur = max(avg) if avg else None
    if bls:
        # nowcast month: month after the last print, or the latest month with EIA data if that is newer
        nm = _month_add(b["cpi_energy_period"], 1)
        if cur and cur > nm:
            nm = cur
        b["nowcast_period"] = nm
        if nm in avg and _month_add(nm, -1) in avg:
            b["retail_gasoline_this_month_usd_gal"] = round(avg[nm], 4)
            b["retail_gasoline_last_month_usd_gal"] = round(avg[_month_add(nm, -1)], 4)
            mom = (avg[nm] / avg[_month_add(nm, -1)] - 1) * 100
            b["retail_gasoline_mom_pct"] = round(mom, 3)
            b["nowcast_mom_pct"] = round(share * mom, 3)
            b["nowcast_cpi_energy"] = round(b["cpi_energy_last"] * (1 + share * mom / 100), 3)
            b["status"] = "ok"
        else:
            if nm in avg:
                b["retail_gasoline_this_month_usd_gal"] = round(avg[nm], 4)
            elif cur:
                b["retail_gasoline_this_month_usd_gal"] = round(avg[cur], 4)
            b["nowcast_cpi_energy"] = b["cpi_energy_last"]  # no gasoline move available: carry last print
            b["nowcast_mom_pct"] = 0.0
            b["status"] = "partial"
    return b


# ---------------------------------------------------------------- shock chain
CASES = ("low", "central", "high")


def _month_start(y, m):
    return datetime(y, m, 1, tzinfo=timezone.utc)


def _next_month(y, m):
    return (y + (m == 12), m % 12 + 1)


def _overlap_days(a0, a1, b0, b1):
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds() / 86400)


def shock_months(net, days, start, cfg, base, now):
    """`months` block for a total net supply loss `net` (mb/d) lasting `days` from `start`.

    Price-shock magnitude does not depend on duration; duration only sets how many elevated
    pump days fall in the current and next calendar month (after the pass-through lag).
    """
    share = base["gasoline_share_of_energy"]
    gas_price = base["retail_gasoline_this_month_usd_gal"] or cfg["reference_gasoline_usd_gal"]
    nowcast = base["nowcast_cpi_energy"]
    pct_lost = net / cfg["global_demand_mbd"] * 100
    crude = {c: pct_lost * cfg["sensitivity_usd_bbl_per_pct"][c] for c in CASES}
    gas = {c: crude[c] / 42 * cfg["gasoline_pass_through"] for c in CASES}
    full_pct = {c: share * gas[c] / gas_price * 100 for c in CASES}

    lag = timedelta(days=cfg.get("pump_lag_days", 10))
    w0 = start + lag
    w1 = w0 + timedelta(days=days)
    y, m = now.year, now.month
    months = {}
    for key, (yy, mm) in (("current_month", (y, m)), ("next_month", _next_month(y, m))):
        m0, m1 = _month_start(yy, mm), _month_start(*_next_month(yy, mm))
        dim = calendar.monthrange(yy, mm)[1]
        el = _overlap_days(w0, w1, m0, m1)
        mo = {"period": f"{yy:04d}-{mm:02d}", "elevated_pump_days": round(el, 4), "days_in_month": dim,
              "baseline_cpi_energy": nowcast}
        for c in CASES:
            pct = full_pct[c] * el / dim
            mo[c] = {"crude_shock_usd_bbl": round(crude[c], 3), "gasoline_shock_usd_gal": round(gas[c], 4),
                     "energy_cpi_shock_pct": round(pct, 5),
                     "energy_cpi_index": None if nowcast is None else round(nowcast * (1 + pct / 100), 3)}
        months[key] = mo
    return months


def shock(fraction, days, start, cfg, base, now):
    """SHOCK object (contract) for a Hormuz disruption `fraction` lasting `days` from `start`."""
    h, off = cfg["hormuz"], cfg["offsets"]
    at_risk = fraction * h["flow_mbd"]
    bypass = off["bypass_capacity_mbd"]
    net = max(0.0, at_risk - bypass)
    net = max(0.0, net - off["strategic_release_mbd"] * off.get("scale", 1.0))
    return {"disruption_fraction": round(fraction, 4), "days": float(days), "start_utc": _iso(start),
            "supply_at_risk_mbd": round(at_risk, 3), "bypass_capacity_mbd": float(bypass),
            "net_supply_loss_mbd": round(net, 3), "months": shock_months(net, days, start, cfg, base, now)}


def scenario_grid(cfg, base, now):
    dv = [round(i / 10, 1) for i in range(11)]
    days_v = [3, 7, 14, 30]
    cells = []
    for d in dv:
        for n in days_v:
            s = shock(d, n, now, cfg, base, now)
            cells.append({"disruption_fraction": d, "days": n, "net_supply_loss_mbd": s["net_supply_loss_mbd"],
                          **{k: {c: s["months"][k][c]["energy_cpi_shock_pct"] for c in CASES}
                             for k in ("current_month", "next_month")}})
    return {"disruption_values": dv, "days_values": days_v, "start_utc": _iso(now), "cells": cells}


# ---------------------------------------------------------------- live Hormuz observation
def _clamp01(x):
    return max(0.0, min(1.0, x))


def read_metrics(out_dir):
    try:
        return json.loads((Path(out_dir) / "hormuz" / "metrics.json").read_text())
    except (OSError, ValueError):
        return None


def days_since_drop(daily, now, baseline, drop_threshold):
    """Consecutive UTC days (ending today/yesterday) below (1 - threshold) x baseline.
    Returns (n|None, first_dropped_date|None). A day with < 6 h of recorded AIS is unknown and stops
    the walk, except today's partial day, which is skipped."""
    today = now.date().isoformat()
    n, first = 0, None
    for d in reversed(daily or []):
        h = d.get("observed_h") or 0
        if h < 6:
            if d.get("date") == today and n == 0:
                continue
            break
        if d["count"] / h * 24 < (1 - drop_threshold) * baseline:
            n, first = n + 1, d["date"]
        else:
            break
    return (n or None), first


def recovery_trend(r24, r3d, band):
    if r24 is None or r3d is None or r3d <= 0:
        return None
    ratio = r24 / r3d
    return "improving" if ratio > 1 + band else "worsening" if ratio < 1 - band else "flat"


def hormuz_live(metrics, cfg, base, now):
    hc = cfg["hormuz"]
    baseline = float(hc.get("baseline_laden_out_per_day", 20))
    thr = hc.get("drop_threshold", 0.25)
    out = {"status": "no_data", "coverage_status": "data_gap", "laden_out_per_day_24h": None,
           "laden_out_per_day_24h_ci90": None, "laden_out_per_day_3d": None, "baseline_laden_out_per_day": baseline,
           "disruption_fraction": None, "disruption_fraction_ci90": None, "days_since_drop": None,
           "recovery_trend": None, "projection": None}
    if not metrics or metrics.get("data_coverage", {}).get("status") == "no_data":
        return out
    out["coverage_status"] = metrics.get("coverage_status", "data_gap")
    if out["coverage_status"] == "data_gap":
        out["status"] = "data_gap"
        return out
    # Too little history: zero crossings in an hour would otherwise read as a full closure.
    if metrics["crossings"]["24h"]["observed_h"] < hc.get("min_observed_h", 12):
        return out
    out["status"] = "ok"
    c24 = metrics["crossings"]["24h"]["laden_out"]
    c3 = metrics["crossings"]["3d"]["laden_out"]
    r24, r3 = c24.get("per_day"), c3.get("per_day")
    out["laden_out_per_day_24h"], out["laden_out_per_day_24h_ci90"], out["laden_out_per_day_3d"] = r24, c24.get("per_day_ci90"), r3
    out["recovery_trend"] = recovery_trend(r24, r3, hc.get("trend_band", 0.15))
    if r24 is None:
        return out
    frac = _clamp01(1 - r24 / baseline)
    out["disruption_fraction"] = round(frac, 4)
    ci = c24.get("per_day_ci90")
    if ci:
        out["disruption_fraction_ci90"] = [round(_clamp01(1 - ci[1] / baseline), 4), round(_clamp01(1 - ci[0] / baseline), 4)]
    n, first = days_since_drop(metrics.get("laden_out_daily"), now, baseline, thr)
    if frac < thr:
        n, first = None, None
    out["days_since_drop"] = n
    days = max(n or 0, hc.get("projection_min_days", 7))
    start = datetime.fromisoformat(first).replace(tzinfo=timezone.utc) if first else now
    out["projection"] = shock(frac, days, start, cfg, base, now)
    return out


# ---------------------------------------------------------------- scenario on request
def _cached_baseline(out_dir, cfg, now, cache_dir=None):
    """Baseline from the last cpi_nowcast.json, else recomputed from the on-disk cache (never the network)."""
    try:
        return json.loads((Path(out_dir) / "cpi_nowcast.json").read_text())["baseline"]
    except (OSError, ValueError, KeyError):
        pass
    cd = Path(cache_dir or CACHE_DIR)

    def read(name):
        try:
            return json.loads((cd / f"{name}.json").read_text())["payload"]
        except (OSError, ValueError, KeyError):
            return None
    return compute_baseline(read("bls"), read("eia"), cfg, now)


def scenario(disruption, days, out_dir, now=None, cfg=None, cache_dir=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = cfg or load_config()
    base = _cached_baseline(out_dir, cfg, now, cache_dir)
    doc = {"schema_version": SCHEMA_VERSION, "as_of_utc": _iso(now), "calibrated": False,
           **shock(float(disruption), float(days), now, cfg, base, now),
           "label": f"{disruption:.0%} Hormuz disruption for {days:g} days", "baseline_status": base["status"]}
    validate("cpi_scenario", doc)
    return doc


# ---------------------------------------------------------------- build / write
def build(out_dir, now=None, offline=False, cfg=None, fetchers=None, cache_dir=None):
    """fetchers: optional {'bls': callable, 'eia': callable} for tests."""
    load_dotenv(ROOT / ".env")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = cfg or load_config()
    cache_dir = cache_dir or CACHE_DIR
    ttl = cfg.get("cache_ttl_hours", 12)
    fetchers = fetchers or {}

    bls, bls_ts, bls_st = _cached("bls", fetchers.get("bls", fetch_bls), now, ttl, offline, cache_dir)
    key = os.environ.get("EIA_API_KEY", "").strip()
    if "eia" in fetchers:
        eia, eia_ts, eia_st = _cached("eia", fetchers["eia"], now, ttl, offline, cache_dir)
    elif key:
        eia, eia_ts, eia_st = _cached("eia", make_fetch_eia(key), now, ttl, offline, cache_dir)
    else:
        eia, eia_ts, eia_st = None, None, EIA_MISSING

    # Regional caches feed /api/cpi/custom only; failures are swallowed by _cached and never touch this document.
    inj = bool(fetchers)
    fb = fetchers.get("bls_regions") or (None if inj else fetch_bls_regions)
    fe = fetchers.get("eia_regions") or (make_fetch_eia_regions(key, now) if key and not inj else None)
    jobs = [(name, fn) for name, fn in (("bls_regions", fb), ("eia_regions", fe)) if fn]

    def refresh():
        if not _REGIONS_LOCK.acquire(blocking=False):
            return  # a previous refresh is still running
        try:
            for name, fn in jobs:
                _cached(name, fn, now, ttl, offline, cache_dir)
        finally:
            _REGIONS_LOCK.release()
    # EIA takes ~1 min for the regional query; aperium.run calls build() inline, so don't block its AIS loop.
    global _regions_thread
    if inj or offline:
        refresh()
    else:
        _regions_thread = threading.Thread(target=refresh, daemon=True)
        _regions_thread.start()

    base = compute_baseline(bls, eia, cfg, now)
    h, off, ri = cfg["hormuz"], cfg["offsets"], cfg["relative_importance"]
    sens = cfg["sensitivity_usd_bbl_per_pct"]
    lag = cfg.get("pump_lag_days", 10)
    assumptions = [
        "AIS cannot measure the CPI level. The level is anchored on the latest official BLS print; AIS only supplies a disruption fraction.",
        "Nowcast period is the month after the last BLS print, or the latest month with EIA weekly data if that is newer. Baseline move = gasoline share x change in the monthly average of weekly EIA retail gasoline vs the previous month; any months between the last print and the nowcast month are not captured.",
        f"Gasoline share of energy CPI = {ri['gasoline']}/{ri['energy']} (BLS relative importance, approximate: {ri.get('source_note', '')}). Other energy components (electricity, natural gas, fuel oil) are held flat.",
        f"Hormuz oil flow is {h['flow_mbd']} mb/d. Offsets: bypass capacity {off['bypass_capacity_mbd']} mb/d (assumption: Saudi East-West and UAE Habshan-Fujairah pipelines) and {off['strategic_release_mbd']} mb/d strategic release applied at {off.get('scale', 1.0):.0%}; net loss = max(0, max(0, at-risk - bypass) - strategic release).",
        f"Crude price response is {sens['low']}/{sens['central']}/{sens['high']} USD/bbl per 1% of global supply ({cfg['global_demand_mbd']} mb/d) lost (low/central/high); short-run demand elasticity is very low so the range is wide and not calibrated.",
        f"Gasoline shock = crude shock / 42 x pass-through {cfg['gasoline_pass_through']}; energy CPI shock at full pass-through = gasoline share x gasoline shock / retail price. Real pass-through is asymmetric (rises faster than falls).",
        f"Pump prices respond after a {lag}-day lag (1-2 week pump pass-through). The elevated pump window is [start + {lag} d, start + {lag} d + duration); prices revert when the disruption ends, with the same lag.",
        "Price shock magnitude does not depend on duration. Duration only sets how many elevated pump days fall in the current and next calendar month; each month's energy_cpi_shock_pct = full shock pct x elevated_pump_days / days_in_month (month-average impact).",
        "Next-month baseline_cpi_energy is assumed flat: it equals the current-month nowcast.",
        f"Observed disruption = 1 - laden outbound tanker transits per day (last 24 h) / typical {h.get('baseline_laden_out_per_day', 20)} per day. The typical rate is uncalibrated (review said ~15-25) and the gate only sees tankers within AIS receiver coverage.",
        "coverage_status data_gap means AIS message volume and non-tanker traffic dropped together with tanker counts, so the fall is treated as missing data rather than a disruption: no disruption estimate or projection is produced (status data_gap or no_data).",
    ]
    if base["retail_gasoline_this_month_usd_gal"] is None:
        assumptions.append(f"No EIA retail gasoline price available; reference price {cfg['reference_gasoline_usd_gal']} USD/gal used to convert the gasoline shock to a CPI percentage.")
    if base["status"] != "ok":
        assumptions.append("Baseline is partial/unavailable: the nowcast carries the last official print without a gasoline-price adjustment" +
                           (" and no CPI level is available, so scenario indices are null." if base["cpi_energy_last"] is None else "."))
    if base["gasoline_share_source"] == "fallback":
        assumptions.append(f"Gasoline share fallback {cfg['gasoline_share_fallback']} used (no relative importance configured).")

    metrics = read_metrics(out_dir)
    live = hormuz_live(metrics, cfg, base, now)
    cov = (metrics or {}).get("data_coverage", {}).get("status")
    if live["status"] == "no_data":
        assumptions.append("No Hormuz AIS data (metrics missing or coverage status no_data): disruption fields are null, which means unknown, not 'no disruption'.")
    if cov == "replay":
        assumptions.append("Hormuz data coverage status is 'replay': live disruption is computed from replayed, not real-time, AIS data.")
    sc = cfg["scenario"]
    scen = shock(sc["disruption_fraction"], sc.get("days", 30), now, cfg, base, now)
    scen["label"] = sc["label"]

    sources = [
        {"name": "BLS CPI (public API v2)", "series": f"{BLS_ENERGY}, {BLS_GASOLINE}", "fetched_utc": bls_ts, "status": bls_st},
        {"name": "EIA weekly US regular retail gasoline", "series": EIA_SERIES, "fetched_utc": eia_ts, "status": eia_st},
        {"name": "Hormuz AIS metrics", "series": "hormuz/metrics.json", "fetched_utc": None,
         "status": live["status"] if cov is None else f"{live['status']} (data_coverage {cov})"},
    ]
    return {"schema_version": SCHEMA_VERSION, "as_of_utc": _iso(now), "calibrated": False,
            "coverage_status": live["coverage_status"], "baseline": base, "hormuz_live": live,
            "hormuz_scenario": scen, "scenario_grid": scenario_grid(cfg, base, now),
            "assumptions": assumptions, "sources": sources}


def write(out_dir, now=None, offline=False, **kw):
    out_dir = Path(out_dir)
    doc = build(out_dir, now=now, offline=offline, **kw)
    validate("cpi_nowcast", doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "cpi_nowcast.json.tmp"
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, out_dir / "cpi_nowcast.json")
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/latest")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    doc = write(Path(a.out), offline=a.offline)
    if _regions_thread:
        _regions_thread.join()  # CLI: let the regional cache refresh finish before exiting
    print(json.dumps({"coverage_status": doc["coverage_status"], "baseline": doc["baseline"], "sources": doc["sources"],
                      "scenario": doc["hormuz_scenario"], "live": doc["hormuz_live"]}, indent=2))


if __name__ == "__main__":
    main()
