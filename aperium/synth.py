"""SYNTHETIC TEST DATA - NOT REAL AIS. Vessel names, MMSIs and movements are invented.

Generates an AISstream-shaped JSONL (PositionReport + ShipStaticData, with received_at) covering both
monitor regions so the engine and frontend can run without a live key: tankers anchoring then berthing
at Corpus Christi and departing laden, VLCCs crossing the Hormuz gate both ways, tankers anchored at
Fujairah, non-tankers (type 70) that must be filtered, and one GPS-spoof jump (> 40 kn implied).
Fixed random seed: output is deterministic. Points that fall on the land mask are not emitted.

Run: uv run python -m aperium.synth --out data/synthetic_replay.jsonl --hours 6
     uv run python -m aperium.synth --out data/synthetic_replay.jsonl --days 7 [--end 2026-10-17T12:00:00Z]

--days N generates N days ending at --end (default: now rounded down to the hour): ~20 laden outbound
tankers/day through the Hormuz gate (plus inbound ballast and steady non-tanker traffic), a disruption
starting 2.5 days before the end where laden outbound drops ~60% (non-tanker traffic unaffected, so
coverage stays ok), slight recovery over the last 12 h, and Corpus Christi activity repeated daily.
Vessels in transit report every 5 min to keep the file small.
"""
import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from aperium import zones

START = "2026-10-17T12:00:00+00:00"
MOVE_S, HOLD_S, STATIC_S = 60, 180, 900

# Corpus Christi routes ([lat, lon]); land-mask misses on narrow channels are skipped by the generator.
CC_EAST, CC_ANCHOR = (27.80, -96.858), (27.80, -96.94)
CC_PASS = [(27.83, -97.00), (27.838, -97.04), (27.848, -97.066)]  # Aransas Pass -> Harbor Island
CC_HARBOR_ISLAND, CC_INGLESIDE = (27.848, -97.066), (27.816, -97.209)
CC_TO_INGLESIDE = [(27.845, -97.09), (27.83, -97.15), CC_INGLESIDE]
# Hormuz
HZ_GULF, HZ_MID, HZ_EAST = (26.55, 56.05), (26.50, 56.45), (26.15, 57.15)
FJ_ANCHOR, FJ_TERMINAL, FJ_EAST = (25.12, 56.55), (25.18, 56.36), (25.30, 57.10)


def go(*points, kn=12):
    return [("go", p, kn) for p in points]


def hold(minutes):
    return [("hold", minutes)]


def draft(d):
    return [("draft", d)]


def vessel(mmsi, name, kind, length, dr, dest, start, legs, spoof_min=None):
    return dict(mmsi=mmsi, name=name, type=kind, length=length, draft=dr, dest=dest, start=start,
                legs=legs, spoof_min=spoof_min)


FLEET = [
    # --- Corpus Christi
    vessel(538001001, "SYNTH ORION", 84, 333, 9.5, "CORPUS CHRISTI", 0,
           go(CC_EAST, CC_ANCHOR) + hold(90) + go(*CC_PASS, kn=8) + hold(55) + draft(21.5)
           + go(CC_PASS[1], CC_PASS[0], CC_EAST, kn=9)[::1] + go((27.80, -96.86))),
    vessel(636001002, "SYNTH VEGA", 82, 274, 8.0, "CORPUS CHRISTI", 40,
           go(CC_EAST, CC_ANCHOR) + hold(60) + go(*CC_PASS, *CC_TO_INGLESIDE, kn=8) + hold(45) + draft(16.5)
           + go(*CC_TO_INGLESIDE[::-1][1:], *CC_PASS[::-1], CC_EAST, kn=9)),
    vessel(477001003, "SYNTH LYRA", 81, 245, 8.5, "CORPUS CHRISTI", 20, go(CC_EAST, (27.77, -96.92)) + hold(500)),
    vessel(538001004, "SYNTH DENEB", 84, 333, 20.0, "EXPORT", 0,
           go(CC_INGLESIDE) + hold(40) + draft(21.0) + go(*CC_TO_INGLESIDE[::-1][1:], *CC_PASS[::-1], CC_EAST, kn=9)),
    vessel(636001005, "SYNTH ALTAIR", 80, 180, 6.0, "CORPUS CHRISTI", 120,
           go(CC_EAST, (27.83, -96.95)) + hold(30) + go(*CC_PASS, kn=8) + hold(50)
           + go(*CC_PASS[::-1][1:], CC_EAST, kn=9)),
    vessel(366001006, "SYNTH BULKER", 70, 200, 10.0, "ELSEWHERE", 60, go(CC_EAST, (27.85, -96.91)) + hold(120)),
    # --- Strait of Hormuz
    vessel(538002001, "SYNTH HORIZON", 84, 332, 21.0, "FUJAIRAH", 0, go(HZ_GULF, HZ_MID, HZ_EAST), spoof_min=50),
    vessel(477002002, "SYNTH MERIDIAN", 84, 300, 21.5, "SINGAPORE", 60, go(HZ_GULF, HZ_MID, HZ_EAST)),
    vessel(636002003, "SYNTH RETURN", 84, 330, 9.0, "BASRAH", 30, go(HZ_EAST, HZ_MID, HZ_GULF)),
    vessel(538002004, "SYNTH CRESCENT", 82, 260, 16.0, "ROTTERDAM", 150, go(HZ_GULF, HZ_MID, HZ_EAST)),
    vessel(636002005, "SYNTH DAWN", 81, 225, 7.5, "BANDAR ABBAS", 200, go(HZ_EAST, HZ_MID, HZ_GULF)),
    vessel(477002006, "SYNTH HEAVY", 84, 320, 20.0, "KUWAIT", 90, go(HZ_EAST, HZ_MID, HZ_GULF)),
    vessel(538002007, "SYNTH WAITER", 84, 334, 20.0, "FUJAIRAH", 0, go((25.2, 57.0), FJ_ANCHOR) + hold(500)),
    vessel(636002008, "SYNTH DRIFT", 82, 270, 8.0, "FUJAIRAH", 10, go((25.25, 57.0), (25.2, 56.45)) + hold(500)),
    vessel(477002009, "SYNTH PATIENCE", 81, 235, 14.0, "FUJAIRAH", 100, go((25.1, 57.05), (25.08, 56.5)) + hold(500)),
    vessel(538002010, "SYNTH BUNKER", 80, 190, 5.0, "FUJAIRAH", 30,
           go(FJ_EAST, (25.2, 56.5), FJ_TERMINAL, kn=10) + hold(50) + draft(11.0) + go((25.2, 56.5), FJ_EAST, kn=10)),
    vessel(371002011, "SYNTH BOXER", 70, 210, 9.0, "JEBEL ALI", 120, go(HZ_GULF, HZ_MID, HZ_EAST)),
]


def bearing(a, b):
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) - \
        math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1]))
    return round(math.degrees(math.atan2(y, x)) % 360)


def km(a, b):
    dy, dx = (b[0] - a[0]) * 111.2, (b[1] - a[1]) * 111.2 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def track(v, rng, move_s=MOVE_S, hold_s=HOLD_S, static_s=STATIC_S):
    """Yield (minute, kind, payload) for one vessel: ('pos', (lat, lon, sog, cog)) or ('static', draft)."""
    t, pos, d = float(v["start"]), v["legs"][0][1], v["draft"]
    yield t, "static", d
    next_static = t + static_s / 60
    for leg in v["legs"]:
        if leg[0] == "draft":
            d = leg[1]
            yield t, "static", d
        elif leg[0] == "hold":
            for _ in range(int(leg[1] * 60 / hold_s)):
                t += hold_s / 60
                yield t, "pos", (pos[0] + rng.uniform(-2e-4, 2e-4), pos[1] + rng.uniform(-2e-4, 2e-4),
                                 round(rng.uniform(0.0, 0.3), 1), 0)
        else:
            _, dest, kn = leg
            steps = max(1, int(km(pos, dest) / 1.852 / kn * 3600 / move_s))
            cog = bearing(pos, dest)
            for i in range(1, steps + 1):
                t += move_s / 60
                f = i / steps
                yield t, "pos", (pos[0] + (dest[0] - pos[0]) * f, pos[1] + (dest[1] - pos[1]) * f,
                                 round(kn + rng.uniform(-0.4, 0.4), 1), cog)
            pos = dest
        while t >= next_static:
            yield next_static, "static", d
            next_static += static_s / 60


def message(v, minute, kind, payload, t0):
    ts = datetime.fromtimestamp(t0 + minute * 60, timezone.utc)
    stamp = f"{ts:%Y-%m-%d %H:%M:%S}.{ts.microsecond:06d}000 +0000 UTC"
    received = (ts.replace(microsecond=ts.microsecond)).isoformat()
    meta = dict(MMSI=v["mmsi"], ShipName=v["name"].ljust(20, "@") if kind == "static" else v["name"], time_utc=stamp)
    if kind == "static":
        a = round(v["length"] * 0.6)
        body = dict(UserID=v["mmsi"], ImoNumber=9000000 + v["mmsi"] % 1000000, Name=v["name"].ljust(20, "@"),
                    Type=v["type"], Dimension=dict(A=a, B=v["length"] - a, C=20, D=20),
                    MaximumStaticDraught=payload, Destination=v["dest"], Valid=True, MessageID=5)
        meta.update(latitude=0.0, longitude=0.0)
        return {"MessageType": "ShipStaticData", "MetaData": meta, "Message": {"ShipStaticData": body},
                "received_at": received}
    lat, lon, sog, cog = payload
    meta.update(latitude=lat, longitude=lon)
    body = dict(UserID=v["mmsi"], Latitude=lat, Longitude=lon, Sog=sog, Cog=cog, TrueHeading=cog,
                NavigationalStatus=1 if sog < 0.5 else 0, Valid=True, MessageID=1)
    return {"MessageType": "PositionReport", "MetaData": meta, "Message": {"PositionReport": body},
            "received_at": received}


def generate(hours=6, seed=7):
    rng = random.Random(seed)
    t0 = datetime.fromisoformat(START).timestamp()
    out = []
    for v in FLEET:
        pos_seen = None
        for minute, kind, payload in track(v, rng):
            if minute > hours * 60:
                break
            if kind == "pos":
                lat, lon = payload[:2]
                if zones.is_land(lat, lon):
                    continue
                if v["spoof_min"] is not None and pos_seen is None and minute >= v["spoof_min"]:
                    pos_seen = True  # one GPS-spoof fix ~150 km away, then the real track resumes
                    out.append((minute + 0.1, message(v, minute + 0.1, "pos", (25.30, 55.20, 12.0, 90), t0)))
            out.append((minute, message(v, minute, kind, payload, t0)))
    out.sort(key=lambda x: x[0])
    return [m for _, m in out]


# ---- multi-day mode
LADEN_OUT_PER_DAY, BALLAST_IN_PER_DAY, NON_TANKER_TRANSITS_PER_DAY = 20.0, 20.0, 12
DISRUPTION_START_H, RECOVERY_START_H, DISRUPTION_FACTOR, RECOVERY_FACTOR = 60.0, 12.0, 0.4, 0.55  # hours before end
TRANSIT_S = 300
LADEN_CLASSES = [("VLCC", 333, 21.0, 0.45), ("Suezmax", 274, 16.0, 0.30), ("Aframax", 245, 13.5, 0.25)]
BALLAST_CLASSES = [("VLCC", 333, 8.0), ("Suezmax", 274, 6.5), ("Aframax", 245, 6.0)]
HZ_PARKED = [(25.2, 57.0), (25.25, 57.0), (25.1, 57.05), (25.15, 56.5), (25.22, 56.45), (25.1, 56.58),
             (25.28, 56.52), (25.12, 56.42), (25.08, 56.52), (25.3, 57.1), (25.45, 56.95), (25.9, 56.9),
             (26.0, 57.0), (25.3, 56.05), (25.6, 56.4), (26.1, 56.2)]
HZ_PARKED_N = 28
CC_PARKED = [(27.85, -96.91), (27.77, -96.92), (27.82, -96.95), (27.76, -96.90)]


def poisson(rng, lam):
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def laden_rate(hours_before_end):
    if hours_before_end <= RECOVERY_START_H:
        return LADEN_OUT_PER_DAY * RECOVERY_FACTOR
    if hours_before_end <= DISRUPTION_START_H:
        return LADEN_OUT_PER_DAY * DISRUPTION_FACTOR
    return LADEN_OUT_PER_DAY


def generate_days(days=7, end=None, seed=7):
    rng = random.Random(seed)
    end = end if end is not None else time.time() // 3600 * 3600
    t0, total = end - days * 86400, days * 1440
    fleet, serial = [], iter(range(1, 10**6))

    for day in range(days):  # Corpus Christi: the original cycle, repeated daily with fresh MMSIs
        for v in FLEET[:6]:
            fleet.append(dict(v, mmsi=v["mmsi"] + day * 10000, start=v["start"] + day * 1440 + rng.uniform(0, 120)))
    for i, spot in enumerate(CC_PARKED):
        fleet.append(vessel(366100000 + i, f"SYNTH CCBOAT {i}", 70, 150, 6.0, "ELSEWHERE", 0, go(spot) + hold(total)))
    for i in range(HZ_PARKED_N):  # steady non-tanker presence, reporting every 10 min
        spot = (HZ_PARKED[i % len(HZ_PARKED)][0] + 0.04 * (i // len(HZ_PARKED)), HZ_PARKED[i % len(HZ_PARKED)][1])
        fleet.append(dict(vessel(371100000 + i, f"SYNTH PARKED {i}", 70 + i % 3, 180, 8.0, "JEBEL ALI", 0,
                                 go(spot) + hold(total)), hold_s=600))
    for v in FLEET[12:15]:  # tankers waiting at Fujairah the whole time
        fleet.append(dict(v, legs=v["legs"][:-1] + hold(total)))
    for hour in range(days * 24):
        before = days * 24 - hour - 0.5
        trips = [("out", laden_rate(before) / 24), ("in", BALLAST_IN_PER_DAY / 24),
                 ("other", NON_TANKER_TRANSITS_PER_DAY / 24)]
        for kind, lam in trips:
            for _ in range(poisson(rng, lam)):
                start, kn, dlat = hour * 60 + rng.uniform(0, 60), rng.uniform(11, 14), rng.uniform(-0.02, 0.02)
                g, m, e = ((p[0] + dlat, p[1]) for p in (HZ_GULF, HZ_MID, HZ_EAST))
                n = next(serial)
                if kind == "out":
                    cls, length, dr, _w = rng.choices(LADEN_CLASSES, [c[3] for c in LADEN_CLASSES])[0]
                    fleet.append(vessel(538200000 + n, f"SYNTH LADEN {n}", 84, length, dr, "SINGAPORE", start,
                                        go(g, m, e, kn=kn)))
                elif kind == "in":
                    cls, length, dr = rng.choice(BALLAST_CLASSES)
                    fleet.append(vessel(636200000 + n, f"SYNTH BALLAST {n}", 84, length, dr, "BASRAH", start,
                                        go(e, m, g, kn=kn)))
                else:
                    pts = (g, m, e) if rng.random() < 0.5 else (e, m, g)
                    fleet.append(vessel(371200000 + n, f"SYNTH CARGO {n}", rng.choice((70, 71, 60)), 200, 9.0,
                                        "JEBEL ALI", start, go(*pts, kn=kn)))
    out = []
    for v in fleet:
        for minute, kind, payload in track(v, rng, TRANSIT_S, v.get("hold_s", TRANSIT_S), 1800):
            if minute > total:
                break
            if kind == "pos" and zones.is_land(*payload[:2]):
                continue
            out.append((minute, message(v, minute, kind, payload, t0)))
    out.sort(key=lambda x: x[0])
    return [m for _, m in out]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/synthetic_replay.jsonl"))
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--days", type=float, help="multi-day mode (overrides --hours)")
    ap.add_argument("--end", help="--days only: end time, ISO-8601 UTC (default: now rounded down to the hour)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.days:
        end = datetime.fromisoformat(a.end.replace("Z", "+00:00")).timestamp() if a.end else None
        msgs = generate_days(int(a.days), end, a.seed)
    else:
        msgs = generate(a.hours, a.seed)
    a.out.write_text("".join(json.dumps(m, separators=(",", ":")) + "\n" for m in msgs))
    print(f"wrote {len(msgs)} synthetic messages to {a.out}")
