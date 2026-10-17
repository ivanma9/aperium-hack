"""Custom energy-CPI scenarios: pick chokepoints, offsets and a US region; reuses cpi_nowcast math.

Reads caches only (never the network); aperium.cpi_nowcast.build() refreshes them.
Contract: see aperium/contract.py (CPI_FACTORS, CPI_CUSTOM).
"""
import copy
from datetime import datetime, timezone

from . import cpi_nowcast as c
from .contract import SCHEMA_VERSION, validate
from .seed import GEOGRAPHIES

IDS = ("hormuz", "malacca", "bab_el_mandeb", "suez")
REGION_NAMES = {"national": "United States", "northeast": "Northeast", "midwest": "Midwest", "south": "South", "west": "West"}
FRACTION_DEFAULT = 0.5


def chokepoints(cfg):
    g = {x["id"].replace("-", "_"): x for x in GEOGRAPHIES}
    out = []
    for i in IDS:
        flow, byp = (cfg["hormuz"]["flow_mbd"], cfg["offsets"]["bypass_capacity_mbd"]) if i == "hormuz" else (g[i]["base_mbd"], g[i]["bypass_cap_mbd"])
        out.append({"id": i, "name": g[i]["name"], "flow_mbd": float(flow), "bypass_mbd": float(byp)})
    return out


def _env(now):
    return {"schema_version": SCHEMA_VERSION, "as_of_utc": c._iso(now), "calibrated": False}


def _effective_cfg(cfg, p):
    cfg = copy.deepcopy(cfg)
    if p.get("gasoline_share") is not None:
        cfg["gasoline_share_fallback"] = p["gasoline_share"]
        if cfg["relative_importance"].get("energy"):
            cfg["relative_importance"]["gasoline"] = p["gasoline_share"] * cfg["relative_importance"]["energy"]
    if p.get("sensitivity_central") is not None:
        s = p["sensitivity_central"]
        cfg["sensitivity_usd_bbl_per_pct"] = {"low": s / 2, "central": s, "high": s * 2}
    if p.get("pass_through") is not None:
        cfg["gasoline_pass_through"] = p["pass_through"]
    if p.get("lag_days") is not None:
        cfg["pump_lag_days"] = p["lag_days"]
    return cfg


def _load(cfg, now, cache_dir):
    """Cache payloads + statuses, read offline."""
    cd = cache_dir or c.CACHE_DIR
    got = {n: c._cached(n, None, now, cfg.get("cache_ttl_hours", 12), True, cd) for n in ("bls", "eia", "bls_regions", "eia_regions")}
    return {n: v[0] for n, v in got.items()}, got


def _bases(cfg, now, data):
    out = {}
    for rid, (se, sg, sx) in c.REGION_SERIES.items():
        if rid == "national":
            bls, eia = data["bls"], data["eia"]
        else:
            r = data["bls_regions"] or {}
            bls = {c.BLS_ENERGY: r[se], **({c.BLS_GASOLINE: r[sg]} if sg in r else {})} if se in r else None
            eia = (data["eia_regions"] or {}).get(sx)
        out[rid] = c.compute_baseline(bls, eia, cfg, now)
    return out


def catalog(out_dir, now=None, cfg=None, cache_dir=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = cfg or c.load_config()
    data, _ = _load(cfg, now, cache_dir)
    bases = _bases(cfg, now, data)
    nat = bases["national"]
    live = c.hormuz_live(c.read_metrics(out_dir), cfg, nat, now)
    off, sens = cfg["offsets"], cfg["sensitivity_usd_bbl_per_pct"]

    def f(id, label, kind, default, lo=None, hi=None, step=None, unit=None, available=True, reason=None):
        return {"id": id, "label": label, "kind": kind, "default": default, "min": lo, "max": hi, "step": step, "unit": unit,
                "available": available, "reason": reason}
    no_eia = data["eia"] is None
    factors = [
        f("bls_anchor", "BLS energy CPI anchor", "locked", None),
        f("gasoline_share", "Gasoline share of energy CPI", "slider", nat["gasoline_share_of_energy"], 0.2, 0.8, 0.01, "share"),
        f("eia_move", "EIA retail gasoline move", "toggle", True, available=not no_eia,
          reason="No EIA weekly gasoline data cached; the baseline carries the last BLS print." if no_eia else None),
        f("release", "Strategic release", "toggle", True),
        f("release_mbd", "Release rate", "slider", float(off["strategic_release_mbd"]), 0, 4, 0.1, "mb/d"),
        f("release_scale", "Release achievable", "slider", float(off.get("scale", 1.0)), 0, 1, 0.05, "fraction"),
        f("crude_response", "Crude price response", "locked", None),
        f("sensitivity_central", "Crude response (central)", "slider", float(sens["central"]), 1, 20, 0.5, "USD/bbl per 1% supply"),
        f("pump", "Pump pass-through", "locked", None),
        f("pass_through", "Gasoline pass-through", "slider", float(cfg["gasoline_pass_through"]), 0, 1, 0.05, "fraction"),
        f("lag_days", "Pump lag", "slider", float(cfg.get("pump_lag_days", 10)), 0, 30, 1, "days"),
        f("days", "Disruption duration", "slider", float(cfg["scenario"].get("days", 30)), 1, 90, 1, "days"),
        f("baseline_transits", "Typical Hormuz laden outbound transits", "slider", float(cfg["hormuz"].get("baseline_laden_out_per_day", 20)),
          10, 30, 1, "per day", available=live["status"] == "ok",
          reason=None if live["status"] == "ok" else f"Live Hormuz data unavailable (status {live['status']})."),
    ]
    cps = []
    for cp in chokepoints(cfg):
        h = cp["id"] == "hormuz"
        cps.append({"id": cp["id"], "name": cp["name"], "flow_mbd": cp["flow_mbd"], "default_bypass_mbd": cp["bypass_mbd"],
                    "default_fraction": FRACTION_DEFAULT, "live_available": h and live["status"] == "ok",
                    "live_reason": None if h and live["status"] == "ok" else
                    (f"Live Hormuz data unavailable (status {live['status']})." if h else "No live source; manual only.")})
    regions = [{"id": rid, "name": REGION_NAMES[rid], "series": dict(zip(("bls_energy", "bls_gasoline", "eia_gasoline"), s)),
                "baseline_status": bases[rid]["status"], "data_period": bases[rid]["cpi_energy_period"]}
               for rid, s in c.REGION_SERIES.items()]
    doc = {**_env(now), "factors": factors, "chokepoints": cps, "regions": regions}
    validate("cpi_factors", doc)
    return doc


def custom(p, out_dir, now=None, cfg=None, cache_dir=None):
    """p: already-validated params (see api.py); missing keys take config defaults."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg0 = cfg or c.load_config()
    cfg = _effective_cfg(cfg0, p)
    data, got = _load(cfg, now, cache_dir)
    bases = _bases(cfg, now, data)
    share_override = p.get("gasoline_share") is not None
    for rid, b in bases.items():
        if share_override or rid != "national":
            b["gasoline_share_source"] = "override" if share_override else "national_fallback"
        if not p.get("eia_move", True) and b["cpi_energy_last"] is not None:
            b["nowcast_cpi_energy"], b["nowcast_mom_pct"] = b["cpi_energy_last"], 0.0
    days = float(p.get("days") or cfg["scenario"].get("days", 30))
    release_on = p.get("release", True)
    rel = (p.get("release_mbd", cfg["offsets"]["strategic_release_mbd"]) * p.get("release_scale", cfg["offsets"].get("scale", 1.0))) if release_on else 0.0
    ids = p.get("chokepoints") or ["hormuz"]
    live = c.hormuz_live(c.read_metrics(out_dir), cfg, bases["national"], now)

    items = []
    for cp in chokepoints(cfg):
        if cp["id"] not in ids:
            continue
        i = cp["id"]
        src = p.get("hormuz_source", "manual") if i == "hormuz" else "manual"
        byp = p.get(f"{i}_bypass_mbd", cp["bypass_mbd"])
        frac, status, reason = p.get(f"{i}_fraction", FRACTION_DEFAULT), "ok", None
        if src == "live":
            r24 = live["laden_out_per_day_24h"]
            if live["status"] == "ok" and live["disruption_fraction"] is not None:
                frac = live["disruption_fraction"]
                if p.get("baseline_transits") and r24 is not None:
                    frac = round(c._clamp01(1 - r24 / p["baseline_transits"]), 4)
            else:
                frac, status, reason = None, "unavailable", f"Live Hormuz data unavailable (status {live['status']}); this chokepoint contributes 0."
        at_risk = (frac or 0.0) * cp["flow_mbd"]
        net = max(0.0, at_risk - byp)
        items.append({"id": cp["id"], "name": cp["name"], "source": src, "fraction": None if frac is None else round(frac, 4),
                      "flow_mbd": cp["flow_mbd"], "at_risk_mbd": round(at_risk, 3), "bypass_mbd": float(byp),
                      "effective_bypass_mbd": round(at_risk - net, 3), "net_mbd": round(net, 3), "status": status, "reason": reason})
    nets = [i["net_mbd"] for i in items]
    gross = sum(nets)
    rel_eff = min(rel, gross)
    total = gross - rel_eff
    overlap = any(i["id"] == "hormuz" and i["net_mbd"] > 0 for i in items) and any(i["id"] != "hormuz" and i["net_mbd"] > 0 for i in items)
    supply = {"chokepoints": items, "net_before_release_mbd": round(gross, 3), "release_applied_mbd": round(rel_eff, 3),
              "net_supply_loss_mbd": round(total, 3), "overlap_warning": overlap,
              "net_supply_loss_lower_bound_mbd": round(max(0.0, max(nets) - rel), 3) if overlap else None}

    rids = list(c.REGION_SERIES) if p.get("region") == "all" else [p.get("region", "national")]
    regions = []
    for rid in rids:
        b = bases[rid]
        reg = {"id": rid, "name": REGION_NAMES[rid], "series": dict(zip(("bls_energy", "bls_gasoline", "eia_gasoline"), c.REGION_SERIES[rid])),
               "baseline": b, "months": None, "contributions": []}
        if b["status"] != "unavailable":
            reg["months"] = c.shock_months(total, days, now, cfg, b, now)
            k = {m: c.shock_months(100.0, days, now, cfg, b, now)[m]["central"]["energy_cpi_shock_pct"] / 100 for m in ("current_month", "next_month")}

            def con(id, label, kind, mbd):
                return {"id": id, "label": label, "kind": kind, "current_month_pct": round(k["current_month"] * mbd, 4),
                        "next_month_pct": round(k["next_month"] * mbd, 4)}
            mom = b["nowcast_mom_pct"] or 0.0
            reg["contributions"] = [{"id": "eia_move", "label": "EIA gasoline move (baseline)", "kind": "baseline",
                                     "current_month_pct": mom, "next_month_pct": 0.0}]
            for i in items:
                reg["contributions"].append(con(i["id"], i["name"], "chokepoint", i["at_risk_mbd"]))
                reg["contributions"].append(con(i["id"] + "_bypass", i["name"] + " bypass", "bypass", -i["effective_bypass_mbd"]))
            reg["contributions"].append(con("release", "Strategic release", "release", -rel_eff))
        regions.append(reg)

    nat = bases["national"]
    inputs = {"chokepoints": [i["id"] for i in items], "region": p.get("region", "national"), "days": days,
              "gasoline_share": nat["gasoline_share_of_energy"], "eia_move": bool(p.get("eia_move", True)), "release": release_on,
              "release_mbd": float(p.get("release_mbd", cfg["offsets"]["strategic_release_mbd"])),
              "release_scale": float(p.get("release_scale", cfg["offsets"].get("scale", 1.0))),
              "sensitivity_central": float(cfg["sensitivity_usd_bbl_per_pct"]["central"]),
              "pass_through": float(cfg["gasoline_pass_through"]), "lag_days": float(cfg.get("pump_lag_days", 10)),
              "baseline_transits": p.get("baseline_transits"),
              "energy_weight": float(cfg["relative_importance"]["energy"]),
              "reference_gasoline_usd_gal": float(cfg["reference_gasoline_usd_gal"])}
    sens = cfg["sensitivity_usd_bbl_per_pct"]
    assumptions = [
        "Chokepoint net loss = max(0, disrupted fraction x flow - bypass); the total is the sum across chokepoints minus the strategic release. One global crude -> gasoline -> energy CPI chain converts it to a price shock.",
        f"Crude response is {sens['low']:g}/{sens['central']:g}/{sens['high']:g} USD/bbl per 1% of global supply ({cfg['global_demand_mbd']:g} mb/d) lost (low/central/high); pass-through {cfg['gasoline_pass_through']:g}, pump lag {cfg.get('pump_lag_days', 10):g} days, one shared duration of {days:g} days starting now. Not calibrated.",
        "Contributions use the central case. The chain is linear in net mb/d, so each chokepoint's gross shock and bypass offset are exact; the strategic release is attributed after summing across chokepoints.",
        "Hormuz flow and bypass come from config.yaml; Malacca, Bab el-Mandeb and Suez flow and bypass are rough seed estimates (aperium/seed.py), to verify against EIA chokepoint data.",
        "Regions pair BLS census-region CPI with EIA PADD retail gasoline (East Coast, Midwest, Gulf Coast, West Coast). PADDs are not census regions, so the pairing is approximate. National uses BLS's own national series; regions are never re-weighted into it.",
        "Regional gasoline share of energy is not verified, so every region uses the national share (gasoline_share_source national_fallback). The crude and gasoline USD shock is the same in every region; the percentage differs by regional gasoline price.",
        "Other energy components (electricity, natural gas, fuel oil) are held flat. Next-month baseline is assumed flat at the current-month nowcast.",
    ]
    if overlap:
        assumptions.append("Hormuz flow largely also transits Malacca and Bab el-Mandeb/Suez, so summing their losses may double count. The lower bound is the largest single chokepoint net loss after release; no correction factor is applied.")
    if not p.get("eia_move", True):
        assumptions.append("EIA gasoline move is off: the baseline carries the last BLS print flat (0% month-over-month).")
    if share_override:
        assumptions.append(f"Gasoline share of energy overridden to {p['gasoline_share']:g} for all regions.")
    if any(i["status"] == "unavailable" for i in items):
        assumptions.append("Live Hormuz data is unavailable, so the live chokepoint contributes 0. That means unknown, not 'no disruption'.")
    if any(r["baseline"]["status"] == "unavailable" for r in regions):
        assumptions.append("Regions with status unavailable have no cached BLS data; their values are null rather than estimated.")
    if any(r["baseline"]["retail_gasoline_this_month_usd_gal"] is None for r in regions if r["months"]):
        assumptions.append(f"Where no EIA retail gasoline price is cached, the reference price {cfg['reference_gasoline_usd_gal']} USD/gal converts the gasoline shock to a CPI percentage.")
    meta = [("BLS CPI national", "bls", f"{c.BLS_ENERGY}, {c.BLS_GASOLINE}"), ("EIA weekly retail gasoline national", "eia", c.EIA_SERIES),
            ("BLS CPI regions", "bls_regions", ", ".join(s for r in c.REGION_SERIES.values() for s in r[:2])),
            ("EIA weekly retail gasoline PADDs", "eia_regions", ", ".join(r[2] for r in c.REGION_SERIES.values()))]
    sources = [{"name": n, "series": s, "fetched_utc": got[k][1], "status": got[k][2]} for n, k, s in meta]
    sources.append({"name": "Hormuz AIS metrics", "series": "hormuz/metrics.json", "fetched_utc": None, "status": live["status"]})
    doc = {**_env(now), "inputs": inputs, "supply": supply, "regions": regions, "assumptions": assumptions, "sources": sources}
    validate("cpi_custom", doc)
    return doc
