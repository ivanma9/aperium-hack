import json
import importlib
from datetime import datetime, timezone

import pytest

from aperium import cpi_factors as f
from aperium import cpi_nowcast as c
from aperium.contract import validate
from test_cpi import BLS, CFG, EIA, NOW, metrics_fx, cfg

CFG_F = {**CFG, "sensitivity_usd_bbl_per_pct": {"low": 3.0, "central": 6.0, "high": 12.0}}
REG = {"northeast": ("1", "10"), "midwest": ("2", "20"), "south": ("3", "30")}  # west deliberately has no cached data


def put(cache, name, payload):
    cache.mkdir(exist_ok=True)
    (cache / f"{name}.json").write_text(json.dumps({"fetched_utc": c._iso(NOW), "payload": payload}))


@pytest.fixture
def env(tmp_path):
    cache = tmp_path / "cache"
    put(cache, "bls", BLS)
    put(cache, "eia", EIA)
    put(cache, "bls_regions", {s: {"value": 200.0 + i, "period": "2026-09"} for i, r in enumerate(REG.values())
                               for s in (f"CUUR0{r[0]}00SA0E", f"CUUR0{r[0]}00SETB01")})
    put(cache, "eia_regions", {f"EMM_EPMR_PTE_R{r[1]}_DPG": EIA for r in REG.values()})
    (tmp_path / "out").mkdir()
    return tmp_path


def go(env, **p):
    p.setdefault("hormuz_source", "manual")
    p.setdefault("hormuz_fraction", 0.5)
    p.setdefault("days", 30)
    return f.custom(p, env / "out", now=NOW, cfg=cfg(), cache_dir=env / "cache")


def cur(doc, region=0, case="central", key="current_month"):
    return doc["regions"][region]["months"][key][case]["energy_cpi_shock_pct"]


def test_defaults_match_nowcast_shock(env):
    base = c.compute_baseline(BLS, EIA, cfg(), NOW)
    ref = c.shock(0.5, 30, NOW, cfg(), base, NOW)
    d = go(env, region="national")
    assert d["regions"][0]["id"] == "national"
    for k in ("current_month", "next_month"):
        assert cur(d, key=k) == ref["months"][k]["central"]["energy_cpi_shock_pct"] != 0
    validate("cpi_custom", d)


def test_zero_bypass_and_no_release_raise_shock(env):
    base = cur(go(env))
    assert cur(go(env, hormuz_bypass_mbd=0)) > base
    assert cur(go(env, release=False)) > base


def test_eia_move_off_carries_last_print(env):
    b = go(env, eia_move=False)["regions"][0]["baseline"]
    assert b["nowcast_cpi_energy"] == BLS[c.BLS_ENERGY]["value"] and b["nowcast_mom_pct"] == 0.0
    assert go(env)["regions"][0]["baseline"]["nowcast_mom_pct"] > 0


def test_overlap(env):
    both = go(env, chokepoints=["hormuz", "suez"], suez_fraction=1.0, suez_bypass_mbd=0)
    s = both["supply"]
    nets = [x["net_mbd"] for x in s["chokepoints"]]
    assert s["overlap_warning"] is True and min(nets) > 0
    assert s["net_supply_loss_lower_bound_mbd"] == pytest.approx(max(nets) - 2.0, abs=1e-3)  # after release
    assert go(env)["supply"]["overlap_warning"] is False


def test_region_all(env):
    d = go(env, region="all")
    assert [r["id"] for r in d["regions"]] == ["national", "northeast", "midwest", "south", "west"]
    gas = {r["months"]["current_month"]["central"]["gasoline_shock_usd_gal"] for r in d["regions"] if r["months"]}
    assert len(gas) == 1
    w = d["regions"][4]
    assert w["baseline"]["status"] == "unavailable" and w["baseline"]["nowcast_cpi_energy"] is None and w["months"] is None
    assert d["regions"][1]["baseline"]["status"] == "ok"
    validate("cpi_custom", d)


def test_live_without_metrics_is_unavailable(env):
    d = go(env, hormuz_source="live")
    h = d["supply"]["chokepoints"][0]
    assert h["net_mbd"] == 0 and h["status"] == "unavailable" and "live" in h["reason"].lower()
    assert cur(d) == 0


def test_live_with_metrics(env):
    (env / "out" / "hormuz").mkdir()
    (env / "out" / "hormuz" / "metrics.json").write_text(json.dumps(metrics_fx(r24=4.0, r3=4.0)))
    h = go(env, hormuz_source="live")["supply"]["chokepoints"][0]
    assert h["status"] == "ok" and h["fraction"] == pytest.approx(0.8)


def test_contributions_sum_to_total(env):
    d = go(env, chokepoints=["hormuz", "malacca"], malacca_fraction=0.9, malacca_bypass_mbd=0)
    r = d["regions"][0]
    shock_items = [x for x in r["contributions"] if x["kind"] != "baseline"]
    assert sum(x["current_month_pct"] for x in shock_items) == pytest.approx(cur(d), abs=1e-3)
    assert any(x["kind"] == "bypass" and x["current_month_pct"] <= 0 for x in shock_items)


def test_catalog_validates(env):
    d = f.catalog(env / "out", now=NOW, cfg=cfg(), cache_dir=env / "cache")
    validate("cpi_factors", d)
    assert [x["id"] for x in d["chokepoints"]] == ["hormuz", "malacca", "bab_el_mandeb", "suez"]
    assert d["chokepoints"][0]["live_available"] is False and d["chokepoints"][0]["live_reason"]
    assert {r["id"]: r["baseline_status"] for r in d["regions"]}["west"] == "unavailable"


def test_api_routes(env, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("OUTPUTS_DIR", str(env / "out"))
    import aperium.api as api
    api = importlib.reload(api)
    monkeypatch.setattr(c, "CACHE_DIR", env / "cache")
    cl = TestClient(api.app)
    r = cl.get("/api/cpi/factors")
    assert r.status_code == 200, r.text
    validate("cpi_factors", r.json())
    r = cl.get("/api/cpi/custom", params={"region": "all", "hormuz_fraction": 0.4, "chokepoints": "hormuz,suez"})
    assert r.status_code == 200, r.text
    validate("cpi_custom", r.json())
    for q in ({"hormuz_fraction": 1.5}, {"days": 0}, {"region": "mars"}, {"gasoline_share": 0.9}, {"chokepoints": "panama"},
              {"bab_el_mandeb_bypass_mbd": 30}):
        assert cl.get("/api/cpi/custom", params=q).status_code == 422, q
    assert cl.get("/api/schema/cpi_custom").status_code == 200
