"""Output contract: JSON Schemas for every file in outputs/latest/.

Single source of truth. `python -m aperium.contract` writes schema/*.json.
Bump SCHEMA_VERSION and note it in SCHEMA.md on any change.
"""
import json
from pathlib import Path

SCHEMA_VERSION = "2.0.0"

TS = {"type": "string", "format": "date-time", "description": "UTC ISO-8601, e.g. 2026-10-17T19:20:00Z"}
NTS = {"type": ["string", "null"], "format": "date-time"}
NUM = {"type": "number"}
NNUM = {"type": ["number", "null"]}
NSTR = {"type": ["string", "null"]}
REGION_ID = {"type": "string", "enum": ["corpus_christi", "hormuz"]}
BBOX = {"type": "array", "description": "[[lat_sw, lon_sw], [lat_ne, lon_ne]]",
        "items": {"type": "array", "items": NUM, "minItems": 2, "maxItems": 2}, "minItems": 2, "maxItems": 2}
CLASS = {"type": ["string", "null"], "enum": ["VLCC", "Suezmax", "Aframax", "product", None],
         "description": "By length: VLCC >= 300 m, Suezmax 250-300, Aframax 220-250, product < 220; null if length unknown"}
ZONE = {"type": ["string", "null"], "description": "Zone id from regions.json, or null when outside all zones"}


def _obj(props, required=None, **extra):
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False, **extra}


ENVELOPE = {"schema_version": {"type": "string", "const": SCHEMA_VERSION}, "as_of_utc": TS,
            "calibrated": {"type": "boolean", "const": False}}

REGIONS = _obj({
    **ENVELOPE,
    "regions": {"type": "array", "items": _obj({
        "id": REGION_ID, "name": {"type": "string"}, "role": {"type": "string"}, "bbox": BBOX,
        "zones": {"type": "object", "description": "GeoJSON FeatureCollection. Feature properties: id, name, "
                  "kind (terminal|anchorage|gate|boundary). Gates/boundaries are LineStrings, others Polygons. "
                  "Coordinates are GeoJSON [lon, lat].",
                  "properties": {"type": {"const": "FeatureCollection"}, "features": {"type": "array"}},
                  "required": ["type", "features"]},
    })},
})

VESSEL = _obj({
    "mmsi": {"type": "string", "pattern": "^[0-9]{9}$"}, "name": NSTR, "imo": NSTR, "class": CLASS,
    "length_m": NNUM, "draft_m": NNUM,
    "laden": {"type": ["boolean", "null"], "description": "draft > 70% of class max draft; null if draft or class unknown"},
    "state": {"type": "string", "enum": ["underway", "anchored", "berthed", "outbound_laden"]},
    "lat": NUM, "lon": NUM, "speed_kn": NNUM, "heading": {**NNUM, "description": "degrees true, 0-359"},
    "destination": NSTR, "zone": ZONE, "last_seen_utc": TS,
})

VESSELS = _obj({**ENVELOPE, "region": REGION_ID, "vessels": {"type": "array", "items": VESSEL}})

EVENT = _obj({
    "ts_utc": TS, "mmsi": VESSEL["properties"]["mmsi"], "name": NSTR,
    "type": {"type": "string", "enum": ["ANCHORED", "BERTHED", "DEPARTED", "GATE_CROSS"]},
    "zone": ZONE,
    "direction": {"type": ["string", "null"], "enum": ["inbound", "outbound", None],
                  "description": "GATE_CROSS only; inbound = toward the port / into the Gulf"},
    "laden": {"type": ["boolean", "null"]},
    "est_barrels": {"type": ["integer", "null"], "description": "Typical load by class, only for laden DEPARTED and laden outbound GATE_CROSS"},
}, description="One line of {region}/events.jsonl (append-only, one JSON object per line). No envelope.")

COVERAGE_STATUS = {"type": "string", "enum": ["ok", "degraded", "data_gap"],
                   "description": "ok; degraded = AIS message volume or non-tanker vessel count is down vs baseline; "
                                  "data_gap = they dropped together with tanker counts, so a fall in tanker traffic is "
                                  "treated as missing data, not a disruption"}
CI90 = {"type": ["array", "null"], "items": NUM, "minItems": 2, "maxItems": 2,
        "description": "[low, high] exact Poisson 90% interval, per day; null when observed_h < 1"}
COUNT = _obj({"count": {"type": "integer"}, "per_day": NNUM, "per_day_ci90": CI90})
WINDOW = _obj({
    "window_h": {"type": "integer"},
    "observed_h": {**NUM, "description": "Hours of recorded AIS inside the window; per_day = count / observed_h * 24"},
    "in": COUNT, "out": COUNT, "laden_out": COUNT,
})

METRICS = _obj({
    **ENVELOPE, "region": REGION_ID,
    "tankers_present": {"type": "integer"}, "waiting_at_anchor": {"type": "integer"},
    "avg_wait_h": {**NNUM, "description": "Mean hours anchored so far for tankers currently at anchor; null if none"},
    "berthed_now": {"type": "integer"},
    "crossings": _obj({"24h": WINDOW, "3d": WINDOW, "7d": WINDOW},
                      description="Gate/boundary crossings over rolling windows (no hourly numbers: counts are too low)"),
    "laden_out_daily": {"type": "array", "description": "Laden outbound crossings per UTC day, last 7 days, oldest first",
                        "items": _obj({"date": {"type": "string", "format": "date"}, "count": {"type": "integer"},
                                       "observed_h": NUM})},
    "est_barrels_departed_today": {"type": "integer", "description": "Since 00:00 UTC"},
    "coverage_status": COVERAGE_STATUS,
    "coverage": _obj({
        "window_h": {"type": "integer", "description": "Recent window compared against the baseline"},
        "messages_per_h": NUM, "messages_per_h_baseline": NNUM,
        "non_tankers": {"type": "integer", "description": "Distinct non-tanker vessels in the recent window"},
        "non_tankers_baseline": NNUM, "tankers": {"type": "integer"}, "tankers_baseline": NNUM,
        "baseline_hours": {**NUM, "description": "Hours of history behind the baseline; status stays ok below the minimum"},
    }),
    "data_coverage": _obj({"messages_last_10m": {"type": "integer"}, "distinct_tankers": {"type": "integer"},
                           "status": {"type": "string", "enum": ["live", "thin", "no_data", "replay"]}}),
})

SENTINEL = _obj({
    **ENVELOPE, "region": REGION_ID,
    "image": {"type": ["object", "null"], "description": "null when no radar image is available for the region",
              **{k: v for k, v in _obj({
                  "acquired_utc": TS, "satellite": NSTR,
                  "image_path": {"type": "string", "description": "Relative to outputs/latest/"},
                  "bbox": BBOX, "ship_count": {"type": ["integer", "null"]},
              }).items() if k != "type"}},
    "next_pass_note": NSTR,
})

CASES = ["low", "central", "high"]
CASE = _obj({
    "crude_shock_usd_bbl": NUM, "gasoline_shock_usd_gal": NUM,
    "energy_cpi_shock_pct": {**NUM, "description": "Month-average impact on the energy CPI, percent, on top of the baseline"},
    "energy_cpi_index": NNUM,
})
MONTH = _obj({
    "period": {"type": "string", "description": "YYYY-MM"},
    "elevated_pump_days": {**NUM, "description": "Days in this month with elevated pump prices after the pass-through lag"},
    "days_in_month": {"type": "integer"},
    "baseline_cpi_energy": NNUM,
    **{c: CASE for c in CASES},
})
MONTHS = _obj({"current_month": MONTH, "next_month": MONTH})
SHOCK = {
    "disruption_fraction": {**NUM, "minimum": 0, "maximum": 1},
    "days": {**NUM, "description": "Disruption duration in days"},
    "start_utc": TS,
    "supply_at_risk_mbd": NUM,
    "bypass_capacity_mbd": NUM,
    "net_supply_loss_mbd": {**NUM, "description": "max(0, supply_at_risk - bypass - strategic release)"},
    "months": MONTHS,
}

CPI = _obj({
    **ENVELOPE,
    "coverage_status": COVERAGE_STATUS,
    "baseline": _obj({
        "cpi_energy_last": NNUM, "cpi_energy_period": {**NSTR, "description": "YYYY-MM of the last official print"},
        "cpi_gasoline_last": NNUM,
        "gasoline_share_of_energy": NUM, "gasoline_share_source": {"type": "string", "enum": ["bls", "fallback"]},
        "retail_gasoline_this_month_usd_gal": NNUM, "retail_gasoline_last_month_usd_gal": NNUM,
        "retail_gasoline_mom_pct": NNUM,
        "nowcast_period": NSTR, "nowcast_cpi_energy": NNUM, "nowcast_mom_pct": NNUM,
        "status": {"type": "string", "enum": ["ok", "partial", "unavailable"]},
    }),
    "hormuz_live": _obj({
        "status": {"type": "string", "enum": ["ok", "data_gap", "no_data"],
                   "description": "Only ok carries a disruption estimate; data_gap and no_data leave it null"},
        "coverage_status": COVERAGE_STATUS,
        "laden_out_per_day_24h": NNUM, "laden_out_per_day_24h_ci90": CI90, "laden_out_per_day_3d": NNUM,
        "baseline_laden_out_per_day": NUM,
        "disruption_fraction": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "disruption_fraction_ci90": CI90,
        "days_since_drop": {"type": ["integer", "null"], "description": "Consecutive UTC days the daily laden-outbound count "
                            "has been below the drop threshold; null when there is no current drop"},
        "recovery_trend": {"type": ["string", "null"], "enum": ["improving", "flat", "worsening", None],
                           "description": "24h rate vs 3d rate"},
        "projection": {"type": ["object", "null"], "description": "Shock if the observed disruption lasts `days` "
                       "(days_since_drop, at least the configured minimum); null unless status is ok",
                       **{k: v for k, v in _obj(SHOCK).items() if k != "type"}},
    }, description="Disruption implied by observed laden outbound Hormuz crossings vs a typical day"),
    "hormuz_scenario": _obj({**SHOCK, "label": {"type": "string"}},
                            description="Configured default what-if (config.yaml); any other case via GET /api/cpi/scenario"),
    "scenario_grid": _obj({
        "disruption_values": {"type": "array", "items": NUM}, "days_values": {"type": "array", "items": {"type": "integer"}},
        "start_utc": TS,
        "cells": {"type": "array", "items": _obj({
            "disruption_fraction": NUM, "days": {"type": "integer"}, "net_supply_loss_mbd": NUM,
            "current_month": _obj({c: NUM for c in CASES}, description="energy_cpi_shock_pct by case"),
            "next_month": _obj({c: NUM for c in CASES}, description="energy_cpi_shock_pct by case"),
        })},
    }, description="Precomputed disruption 0..1 (step 0.1) x days {3, 7, 14, 30}, starting now; values are energy_cpi_shock_pct"),
    "assumptions": {"type": "array", "items": {"type": "string"}},
    "sources": {"type": "array", "items": _obj({"name": {"type": "string"}, "series": NSTR,
                                                 "fetched_utc": NTS, "status": {"type": "string"}})},
})

SCENARIO_RESPONSE = _obj({**ENVELOPE, **SHOCK, "label": {"type": "string"}, "baseline_status": {"type": "string"}},
                         description="GET /api/cpi/scenario?disruption=&days= (computed on request, not a file)")

SCHEMAS = {"regions": REGIONS, "vessels": VESSELS, "event": EVENT, "metrics": METRICS,
           "sentinel": SENTINEL, "cpi_nowcast": CPI, "cpi_scenario": SCENARIO_RESPONSE}


def validate(name, document):
    import jsonschema
    jsonschema.Draft202012Validator(SCHEMAS[name], format_checker=jsonschema.FormatChecker()).validate(document)


def write(out=Path("schema")):
    out.mkdir(exist_ok=True)
    for name, schema in SCHEMAS.items():
        doc = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{name}.schema.json",
               "title": name, **schema}
        (out / f"{name}.schema.json").write_text(json.dumps(doc, indent=2) + "\n")


if __name__ == "__main__":
    write()
