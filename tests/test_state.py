import json
from datetime import datetime, timezone

import pytest

from aperium import run, zones
from aperium.contract import validate
from aperium.state import Engine, Vessel, parse_time, poisson_ci90, ship_class

T0 = datetime(2026, 10, 17, 12, tzinfo=timezone.utc).timestamp()
INGLESIDE, HARBOR, ANCHORAGE = (27.816, -97.209), (27.848, -97.066), (27.80, -96.94)


def stamp(minute):
    ts = datetime.fromtimestamp(T0 + minute * 60, timezone.utc)
    return f"{ts:%Y-%m-%d %H:%M:%S}.000000000 +0000 UTC"


def static(mmsi, kind=84, length=333, draft=21.0, minute=0):
    return {"MessageType": "ShipStaticData", "MetaData": {"MMSI": mmsi, "ShipName": "TEST", "time_utc": stamp(minute),
            "latitude": 27.8, "longitude": -96.9},
            "Message": {"ShipStaticData": {"UserID": mmsi, "Type": kind, "Dimension": {"A": length - 30, "B": 30},
                                           "MaximumStaticDraught": draft, "Destination": "X", "Valid": True}}}


def pos(mmsi, minute, lat, lon, sog=0.0):
    return {"MessageType": "PositionReport", "MetaData": {"MMSI": mmsi, "ShipName": "TEST", "time_utc": stamp(minute)},
            "Message": {"PositionReport": {"UserID": mmsi, "Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": 90,
                                           "TrueHeading": 511, "Valid": True}}}


def feed(engine, messages):
    return [e for m in messages for e in engine.ingest(m)]


def tanker(engine, mmsi=538000001, **kw):
    engine.ingest(static(mmsi, **kw))
    return mmsi


def stay(mmsi, place, start, end, step=3):
    return [pos(mmsi, m, *place) for m in range(start, end + 1, step)]


def test_class_and_laden_thresholds():
    assert [ship_class(x) for x in (None, 219.9, 220, 249.9, 250, 299.9, 300)] == \
        [None, "product", "Aframax", "Aframax", "Suezmax", "Suezmax", "VLCC"]
    v = Vessel("1")
    v.length, v.draft = 330, 15.3
    assert v.laden is False  # 70% of 22.0 m is 15.4
    v.draft = 15.5
    assert v.laden is True
    v.draft = None
    assert v.laden is None
    v.length = None
    assert v.cls is None


def test_only_tankers_are_output():
    e = Engine()
    t = tanker(e)
    cargo = tanker(e, 366000002, kind=70)
    unknown = 366000003
    feed(e, [pos(m, 0, *ANCHORAGE, 5) for m in (t, cargo, unknown)])
    doc, metrics = e.snapshot("corpus_christi")
    assert [v["mmsi"] for v in doc["vessels"]] == [str(t)]
    assert metrics["tankers_present"] == 1 and metrics["data_coverage"]["messages_last_10m"] == 5  # all messages in region, incl. static
    assert unknown in map(int, e.vessels)  # tracked internally


def test_static_after_position_still_outputs():
    e = Engine()
    feed(e, [pos(538000001, 0, *ANCHORAGE, 5)])
    assert e.snapshot("corpus_christi")[0]["vessels"] == []
    e.ingest(static(538000001, minute=1))
    v = e.snapshot("corpus_christi")[0]["vessels"][0]
    assert (v["class"], v["laden"], v["destination"]) == ("VLCC", True, "X")


def test_anchored_fires_once():
    e = Engine()
    t = tanker(e)
    events = feed(e, stay(t, ANCHORAGE, 0, 60))
    assert [x["type"] for x in events] == ["ANCHORED"] and events[0]["zone"] == "offshore_anchorage"
    doc, metrics = e.snapshot("corpus_christi")
    assert doc["vessels"][0]["state"] == "anchored" and metrics["waiting_at_anchor"] == 1
    assert metrics["avg_wait_h"] == pytest.approx(1.0, abs=0.01)


def test_berthed_needs_30_minutes_then_departed():
    e = Engine()
    t = tanker(e)
    assert feed(e, stay(t, INGLESIDE, 0, 30)) == []  # exactly 30 min is not > 30
    events = feed(e, stay(t, INGLESIDE, 33, 60))
    assert [x["type"] for x in events] == ["BERTHED"]
    assert e.snapshot("corpus_christi", T0 + 3700)[1]["berthed_now"] == 1
    out = feed(e, [pos(t, 75, 27.84, -97.15, 6)])  # left terminal polygon
    assert [(x["type"], x["zone"], x["laden"], x["est_barrels"]) for x in out] == \
        [("DEPARTED", "ingleside", True, 2_000_000)]
    assert feed(e, [pos(t, 90, 27.86, -97.12, 6)]) == []  # no repeat


def test_departed_ballast_has_no_barrels():
    e = Engine()
    t = tanker(e, draft=8.0)
    feed(e, stay(t, INGLESIDE, 0, 40))
    out = feed(e, [pos(t, 60, 27.84, -97.15, 6)])
    assert out[0]["type"] == "DEPARTED" and out[0]["laden"] is False and out[0]["est_barrels"] is None


def test_gate_direction_both_ways():
    e = Engine()
    t = tanker(e)
    inbound = feed(e, [pos(t, 0, 27.835, -96.97, 8), pos(t, 15, 27.835, -97.04, 8)])
    outbound = feed(e, [pos(t, 30, 27.835, -96.97, 8)])
    assert [(x["type"], x["direction"]) for x in inbound + outbound] == \
        [("GATE_CROSS", "inbound"), ("GATE_CROSS", "outbound")]
    assert inbound[0]["est_barrels"] is None and outbound[0]["est_barrels"] == 2_000_000
    assert zones.gate_crossing("hormuz", (26.6, 56.2), (26.6, 56.7)) == ("hormuz_gate", "outbound")
    assert zones.gate_crossing("hormuz", (26.6, 56.7), (26.6, 56.2)) == ("hormuz_gate", "inbound")
    assert e.snapshot("corpus_christi", T0 + 31 * 60)[0]["vessels"][0]["state"] == "outbound_laden"


def test_ballast_outbound_gate_has_no_barrels():
    e = Engine()
    t = tanker(e, draft=9.0)
    out = feed(e, [pos(t, 0, 27.835, -97.04, 8), pos(t, 15, 27.835, -96.97, 8)])
    assert out[0]["direction"] == "outbound" and out[0]["laden"] is False and out[0]["est_barrels"] is None


def test_barrels_counted_once_per_voyage():
    e = Engine()
    t = tanker(e)
    feed(e, stay(t, HARBOR, 0, 40))
    events = feed(e, [pos(t, 50, 27.835, -97.04, 6), pos(t, 65, 27.835, -96.97, 8)])
    assert [x["type"] for x in events] == ["BERTHED", "DEPARTED", "GATE_CROSS"][1:] and \
        [x["est_barrels"] for x in events] == [2_000_000, 2_000_000]
    assert e.snapshot("corpus_christi", T0 + 70 * 60)[1]["est_barrels_departed_today"] == 2_000_000
    day = e.snapshot("corpus_christi", T0 + 70 * 60)[1]["crossings"]["24h"]
    assert (day["in"]["count"], day["out"]["count"], day["laden_out"]["count"]) == (0, 1, 1)


def test_spoof_jump_dropped():
    e = Engine()
    t = tanker(e)
    feed(e, [pos(t, 0, *ANCHORAGE, 5), pos(t, 1, 25.3, 55.2, 5), pos(t, 2, 27.80, -96.935, 5)])
    assert e.dropped == {"speed": 1, "land": 0}
    v = e.snapshot("corpus_christi")[0]["vessels"][0]
    assert v["lat"] == 27.80 and v["lon"] == -96.935


def test_land_dropped_but_berth_zone_kept():
    assert zones.is_land(27.9, -97.2) and not zones.is_land(*INGLESIDE)
    e = Engine()
    t = tanker(e)
    feed(e, [pos(t, 0, 27.9, -97.2, 5)])
    assert e.dropped["land"] == 1 and e.snapshot("corpus_christi")[0]["vessels"] == []


def test_parse_time_formats():
    assert parse_time("2026-10-17 12:00:00.500000000 +0000 UTC") == T0 + 0.5
    assert parse_time("2026-10-17T12:00:00+00:00") == T0
    assert parse_time("2026-10-17T14:00:00+02:00") == T0
    assert parse_time("garbage") is None


def test_seven_day_synth_replay_validates(tmp_path):
    from aperium import synth
    src = tmp_path / "week.jsonl"
    end = T0 + 3600
    src.write_text("".join(json.dumps(m) + "\n" for m in synth.generate_days(7, end)))
    run.replay(src, 0, tmp_path / "out", strict=True, hooks=False)
    for rid in ("corpus_christi", "hormuz"):
        validate("metrics", json.loads((tmp_path / "out" / rid / "metrics.json").read_text()))
    m = json.loads((tmp_path / "out" / "hormuz" / "metrics.json").read_text())
    c = m["crossings"]
    assert m["coverage_status"] == "ok" and len(m["laden_out_daily"]) == 7
    assert c["7d"]["observed_h"] > 160 and c["24h"]["laden_out"]["per_day"] < 0.7 * 20 < c["7d"]["laden_out"]["per_day"] + 5


def test_replay_end_to_end_validates(tmp_path):
    from aperium import synth
    src = tmp_path / "synthetic.jsonl"
    src.write_text("".join(json.dumps(m) + "\n" for m in synth.generate(6)))
    engine = run.replay(src, 0, tmp_path / "out", strict=True, hooks=False)
    assert engine.replay and engine.dropped["speed"] == 1
    validate("regions", json.loads((tmp_path / "out" / "regions.json").read_text()))
    for rid in ("corpus_christi", "hormuz"):
        d = tmp_path / "out" / rid
        validate("vessels", json.loads((d / "vessels.json").read_text()))
        metrics = json.loads((d / "metrics.json").read_text())
        validate("metrics", metrics)
        assert metrics["data_coverage"]["status"] == "replay" and metrics["tankers_present"] > 0
        lines = (d / "events.jsonl").read_text().splitlines()
        assert lines
        for line in lines:
            validate("event", json.loads(line))


# ---- crossings windows and coverage health (Hormuz)
PARKED = (25.2, 57.0)


def gate_trip(engine, mmsi, minute, direction="outbound", draft=21.0):
    """A tanker (static + two fixes straddling the Hormuz gate) at `minute` after T0."""
    engine.ingest(static(mmsi, draft=draft, minute=minute))
    a, b = (26.55, 56.30), (26.50, 56.55)
    feed(engine, [pos(mmsi, minute, *(a if direction == "outbound" else b), 12),
                  pos(mmsi, minute + 45, *(b if direction == "outbound" else a), 12)])


def traffic(engine, start_h, end_h, non_tankers, tankers, per_hour=4, first=0):
    """Every vessel sends `per_hour` messages per hour from `start_h` to `end_h` hours after T0, parked in Hormuz."""
    for h in range(start_h, end_h):
        for i in range(non_tankers):
            for k in range(per_hour):
                m = 366_100_000 + i
                if h == start_h and k == 0 and not first:
                    engine.ingest(static(m, kind=70, minute=h * 60))
                engine.ingest(pos(m, h * 60 + k * 60 // per_hour + 1, *PARKED))
        for i in range(tankers):
            for k in range(per_hour):
                m = 538_100_000 + i
                if h == start_h and k == 0 and not first:
                    engine.ingest(static(m, minute=h * 60))
                engine.ingest(pos(m, h * 60 + k * 60 // per_hour + 2, *PARKED))


def hormuz_status(recent_non_tankers, recent_tankers, history_h=48, recent_per_hour=4):
    e = Engine()
    traffic(e, 0, history_h, 40, 5)
    traffic(e, history_h, history_h + 3, recent_non_tankers, recent_tankers, recent_per_hour, first=1)
    metrics = e.snapshot("hormuz")[1]
    validate("metrics", metrics)
    return metrics


def test_poisson_ci90_exact_values():
    assert poisson_ci90(0) == (0.0, pytest.approx(2.9957, abs=1e-3))
    lo, hi = poisson_ci90(10)
    assert (lo, hi) == (pytest.approx(5.425, abs=2e-3), pytest.approx(16.962, abs=2e-3))


def test_windows_use_observed_hours_only():
    e = Engine()
    traffic(e, 0, 12, 1, 0, per_hour=6)  # coverage only for the first 12 h (12:00-23:59 on Oct 17)
    for i in range(6):
        gate_trip(e, 538_200_000 + i, 60 * i + 10)
    gate_trip(e, 538_200_100, 130, "inbound")
    gate_trip(e, 538_200_101, 140, draft=8.0)  # ballast outbound
    m = e.snapshot("hormuz", T0 + 12 * 3600)[1]
    validate("metrics", m)
    day, week = m["crossings"]["24h"], m["crossings"]["7d"]
    assert (day["window_h"], week["window_h"]) == (24, 168) and day["observed_h"] == week["observed_h"] == 12
    assert (day["laden_out"]["count"], day["out"]["count"], day["in"]["count"]) == (6, 7, 1)
    assert day["laden_out"]["per_day"] == pytest.approx(12.0)  # 6 / 12 observed h * 24, not 6 / 24 h
    lo, hi = day["laden_out"]["per_day_ci90"]
    assert lo == pytest.approx(poisson_ci90(6)[0] * 2, abs=0.01) and hi == pytest.approx(poisson_ci90(6)[1] * 2, abs=0.01)
    # before any coverage: counts but no rates
    empty = Engine().snapshot("hormuz", T0)[1]["crossings"]["24h"]
    assert empty["observed_h"] == 0 and empty["laden_out"] == {"count": 0, "per_day": None, "per_day_ci90": None}


def test_laden_out_daily_last_seven_utc_days():
    e = Engine()
    traffic(e, 0, 12, 1, 0, per_hour=6)
    for i in range(4):
        gate_trip(e, 538_200_000 + i, 60 * i + 10)
    m = e.snapshot("hormuz", T0 + 11 * 3600 + 1800)[1]  # 23:30 on Oct 17
    daily = m["laden_out_daily"]
    assert [d["date"] for d in daily] == [f"2026-10-{d}" for d in range(11, 18)]
    assert [d["count"] for d in daily] == [0] * 6 + [4]
    assert daily[-1]["observed_h"] == pytest.approx(11.5, abs=0.2) and daily[0]["observed_h"] == 0


def test_coverage_ok_degraded_data_gap():
    ok = hormuz_status(40, 5)
    assert ok["coverage_status"] == "ok" and ok["coverage"]["baseline_hours"] >= 12
    assert ok["coverage"]["non_tankers"] == 40 and ok["coverage"]["non_tankers_baseline"] == 40
    assert ok["coverage"]["messages_per_h"] == pytest.approx(ok["coverage"]["messages_per_h_baseline"], rel=0.1)
    assert hormuz_status(40, 0)["coverage_status"] == "ok"  # only tankers vanished: a real disruption
    assert hormuz_status(30, 5)["coverage_status"] == "degraded"  # non-tankers down 25%, tankers unaffected
    assert hormuz_status(12, 5)["coverage_status"] == "degraded"  # coverage < 50% but tankers did not drop
    gap = hormuz_status(12, 1)
    assert gap["coverage_status"] == "data_gap" and gap["coverage"]["tankers"] == 1


def test_coverage_needs_history_for_baseline():
    e = Engine()
    traffic(e, 0, 6, 40, 5)
    traffic(e, 6, 9, 1, 0, per_hour=1, first=1)
    m = e.snapshot("hormuz")[1]
    assert m["coverage_status"] == "ok" and m["coverage"]["baseline_hours"] < 12
    assert m["coverage"]["messages_per_h_baseline"] is None and m["coverage"]["tankers_baseline"] is None
