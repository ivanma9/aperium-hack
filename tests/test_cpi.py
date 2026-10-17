import json
import importlib
from datetime import datetime, timezone

import pytest

from aperium import cpi_nowcast as c
from aperium.contract import validate

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
BLS = {c.BLS_ENERGY: {"value": 300.0, "period": "2026-09"}, c.BLS_GASOLINE: {"value": 350.0, "period": "2026-09"}}
EIA = [{"period": "2026-10-12", "value": 3.30}, {"period": "2026-10-05", "value": 3.30},
       {"period": "2026-09-28", "value": 3.00}, {"period": "2026-09-21", "value": 3.00}]
CFG = {
    "relative_importance": {"energy": 6.0, "gasoline": 3.0, "source_note": "test"}, "gasoline_share_fallback": 0.5,
    "reference_gasoline_usd_gal": 3.10,
    "hormuz": {"flow_mbd": 20.0, "baseline_laden_out_per_day": 20, "drop_threshold": 0.25, "trend_band": 0.15,
               "projection_min_days": 7},
    "offsets": {"bypass_capacity_mbd": 2.5, "strategic_release_mbd": 2.0, "scale": 1.0}, "pump_lag_days": 10,
    "global_demand_mbd": 100.0,
    "sensitivity_usd_bbl_per_pct": {"low": 3.0, "central": 6.0, "high": 12.0},
    "gasoline_pass_through": 1.0, "scenario": {"label": "test", "disruption_fraction": 0.5, "days": 30},
    "cache_ttl_hours": 12,
}


def cfg():
    return json.loads(json.dumps(CFG))


def run(tmp_path, eia=True, monkeypatch=None, **kw):
    monkeypatch.setenv("EIA_API_KEY", "")
    f = {"bls": lambda: BLS}
    if eia:
        f["eia"] = lambda: EIA
    return c.build(tmp_path / "out", now=NOW, cfg=cfg(), fetchers=f, cache_dir=tmp_path / "cache", **kw)


def test_baseline_formula(tmp_path, monkeypatch):
    b = run(tmp_path, monkeypatch=monkeypatch)["baseline"]
    assert b["nowcast_period"] == "2026-10" and b["status"] == "ok"
    assert b["retail_gasoline_mom_pct"] == pytest.approx(10.0)  # 3.30 vs 3.00
    assert b["nowcast_cpi_energy"] == pytest.approx(300 * (1 + 0.5 * 0.10))  # share 0.5


def test_missing_eia_key_is_partial(tmp_path, monkeypatch):
    doc = run(tmp_path, eia=False, monkeypatch=monkeypatch)
    assert doc["baseline"]["status"] == "partial"
    assert doc["baseline"]["nowcast_cpi_energy"] == 300.0
    assert doc["sources"][1]["status"].startswith("missing_key")
    assert any("reference price" in a for a in doc["assumptions"])


def test_stale_cache_fallback(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch=monkeypatch)  # populate cache
    later = datetime(2026, 10, 19, tzinfo=timezone.utc)

    def boom():
        raise RuntimeError("HTTP 500 boom")
    monkeypatch.setenv("EIA_API_KEY", "")
    doc = c.build(tmp_path / "out", now=later, cfg=cfg(), fetchers={"bls": boom, "eia": boom}, cache_dir=tmp_path / "cache")
    assert doc["sources"][0]["status"] == "stale_cache: HTTP 500 boom"
    assert doc["baseline"]["cpi_energy_last"] == 300.0


def test_doc_validates_and_write_atomic(tmp_path, monkeypatch):
    doc = run(tmp_path, monkeypatch=monkeypatch)
    validate("cpi_nowcast", doc)
    monkeypatch.setenv("EIA_API_KEY", "")
    out = tmp_path / "w"
    c.write(out, now=NOW, cfg=cfg(), fetchers={"bls": lambda: BLS, "eia": lambda: EIA}, cache_dir=tmp_path / "cache")
    validate("cpi_nowcast", json.loads((out / "cpi_nowcast.json").read_text()))
    assert not list(out.glob("*.tmp"))


# ---------------------------------------------------------------- v2
BASE = {"gasoline_share_of_energy": 0.5, "retail_gasoline_this_month_usd_gal": 3.30, "nowcast_cpi_energy": 315.0,
        "status": "ok"}


def ci(lo, hi):
    return [lo, hi]


def metrics_fx(r24=10.0, r3=10.0, cov="ok", data="live", daily=None, ci24=(5.0, 16.0)):
    lo = lambda r: {"count": 0, "per_day": r, "per_day_ci90": list(ci24) if r is not None else None}
    w = lambda r: {"window_h": 24, "observed_h": 24.0, "in": lo(r), "out": lo(r), "laden_out": lo(r)}
    return {"coverage_status": cov, "data_coverage": {"messages_last_10m": 5, "distinct_tankers": 3, "status": data},
            "crossings": {"24h": w(r24), "3d": w(r3), "7d": w(r3)},
            "laden_out_daily": daily or []}


def day(d, count, h=24.0):
    return {"date": f"2026-10-{d:02d}", "count": count, "observed_h": h}


def write_metrics(tmp_path, m):
    h = tmp_path / "out" / "hormuz"
    h.mkdir(parents=True)
    (h / "metrics.json").write_text(json.dumps(m))


def test_bypass_floor_and_zero_disruption():
    s = c.shock(0.1, 7, NOW, cfg(), BASE, NOW)  # 2 mb/d at risk < 2.5 bypass
    assert s["net_supply_loss_mbd"] == 0.0 and s["bypass_capacity_mbd"] == 2.5
    for k in ("current_month", "next_month"):
        assert all(s["months"][k][x]["energy_cpi_shock_pct"] == 0 for x in c.CASES)
        assert s["months"][k]["central"]["energy_cpi_index"] == 315.0
    # 0.5 -> 10 - 2.5 - 2.0 = 5.5 mb/d lost -> 5.5% x $6 central
    assert c.shock(0.5, 7, NOW, cfg(), BASE, NOW)["months"]["current_month"]["central"]["crude_shock_usd_bbl"] == pytest.approx(33.0)


def test_month_split():
    # window entirely in November: start Oct 25 + 10 d lag = Nov 4
    s = c.shock(0.5, 10, datetime(2026, 10, 25, tzinfo=timezone.utc), cfg(), BASE, NOW)
    cur, nxt = s["months"]["current_month"], s["months"]["next_month"]
    assert cur["period"] == "2026-10" and cur["elevated_pump_days"] == 0 and nxt["elevated_pump_days"] == 10
    # start Oct 10 + 10 d = Oct 20 .. Nov 3: 11 days Oct 20-31 (Oct 20 00:00 -> Nov 1 00:00 = 12 d), 2 d Nov
    s = c.shock(0.5, 14, datetime(2026, 10, 10, tzinfo=timezone.utc), cfg(), BASE, NOW)
    cur, nxt = s["months"]["current_month"], s["months"]["next_month"]
    assert (cur["elevated_pump_days"], nxt["elevated_pump_days"]) == (12, 2)
    assert (cur["days_in_month"], nxt["days_in_month"]) == (31, 30)
    full = cur["central"]["energy_cpi_shock_pct"] * 31 / 12
    assert nxt["central"]["energy_cpi_shock_pct"] == pytest.approx(full * 2 / 30, rel=1e-3)
    assert nxt["central"]["crude_shock_usd_bbl"] == cur["central"]["crude_shock_usd_bbl"]  # magnitude independent of duration


def test_grid_cells_and_zero():
    doc = run_doc = c.scenario_grid(cfg(), BASE, NOW)
    assert len(doc["cells"]) == 44 and doc["days_values"] == [3, 7, 14, 30]
    assert doc["disruption_values"][:3] == [0.0, 0.1, 0.2]
    zero = [x for x in doc["cells"] if x["disruption_fraction"] == 0.0]
    assert len(zero) == 4 and all(v == 0 for x in zero for k in ("current_month", "next_month") for v in x[k].values())


def test_live_data_gap_and_no_data(tmp_path, monkeypatch):
    write_metrics(tmp_path, metrics_fx(cov="data_gap"))
    live = run(tmp_path, monkeypatch=monkeypatch)
    assert live["coverage_status"] == "data_gap"
    h = live["hormuz_live"]
    assert h["status"] == "data_gap" and h["disruption_fraction"] is None and h["projection"] is None
    validate("cpi_nowcast", live)


def test_no_metrics_is_no_data(tmp_path, monkeypatch):
    doc = run(tmp_path, monkeypatch=monkeypatch)
    assert doc["hormuz_live"]["status"] == "no_data" and doc["coverage_status"] == "data_gap"
    assert doc["hormuz_live"]["projection"] is None
    validate("cpi_nowcast", doc)


def test_live_ok_drop_and_trend(tmp_path, monkeypatch):
    daily = [day(11, 22), day(12, 21), day(13, 4), day(14, 3), day(15, 5), day(16, 2), day(17, 1, h=3.0)]
    write_metrics(tmp_path, metrics_fx(r24=4.0, r3=3.0, cov="degraded", daily=daily, ci24=(2.0, 8.0)))
    doc = run(tmp_path, monkeypatch=monkeypatch)
    h = doc["hormuz_live"]
    assert h["status"] == "ok" and doc["coverage_status"] == "degraded"
    assert h["disruption_fraction"] == pytest.approx(0.8)
    assert h["disruption_fraction_ci90"] == [0.6, 0.9]
    assert h["days_since_drop"] == 4 and h["recovery_trend"] == "improving"  # 4/3 > 1.15; today partial skipped
    p = h["projection"]
    assert p["start_utc"] == "2026-10-13T00:00:00Z" and p["days"] == 7
    assert c.recovery_trend(3.0, 3.0, 0.15) == "flat" and c.recovery_trend(2.0, 3.0, 0.15) == "worsening"
    validate("cpi_nowcast", doc)
    assert len(doc["scenario_grid"]["cells"]) == 44


def test_scenario_validates(tmp_path, monkeypatch):
    out = tmp_path / "o"
    out.mkdir()
    (out / "cpi_nowcast.json").write_text(json.dumps({"baseline": BASE}))
    r = c.scenario(0.3, 10, out, now=NOW, cfg=cfg())
    validate("cpi_scenario", r)
    assert r["baseline_status"] == "ok" and r["days"] == 10


def test_api_scenario(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    (tmp_path / "cpi_nowcast.json").write_text(json.dumps({"baseline": BASE}))
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path))
    import aperium.api as api
    api = importlib.reload(api)
    cl = TestClient(api.app)
    for path in ("/api/cpi/scenario", "/cpi/scenario"):
        r = cl.get(path, params={"disruption": 0.6, "days": 10})
        assert r.status_code == 200, r.text
        validate("cpi_scenario", r.json())
    for q in ({"disruption": 1.5, "days": 10}, {"disruption": 0.3, "days": 0}, {"disruption": 0.3, "days": 366},
              {"disruption": -0.1, "days": 5}, {"days": 5}):
        assert cl.get("/api/cpi/scenario", params=q).status_code == 422


def test_live_needs_min_observed_hours():
    m = {"coverage_status": "ok", "data_coverage": {"status": "live"},
         "crossings": {w: {"observed_h": 1.2, "laden_out": {"count": 0, "per_day": 0.0, "per_day_ci90": [0.0, 60.0]}}
                       for w in ("24h", "3d", "7d")},
         "laden_out_daily": []}
    from aperium import cpi_nowcast
    cfg = cpi_nowcast.load_config()
    live = cpi_nowcast.hormuz_live(m, cfg, None, datetime(2026, 10, 17, 21, tzinfo=timezone.utc))
    assert live["status"] == "no_data" and live["disruption_fraction"] is None
