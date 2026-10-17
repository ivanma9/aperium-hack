"""AIS state engine shared by live tailing and replay.

Engine.ingest(raw AISstream message) -> events; Engine.snapshot(region, now) -> (vessels_doc, metrics_doc).
The engine clock is the messages' own time (MetaData.time_utc, falling back to received_at).

Rules worth knowing:
- Only ship types 80-89 are output; other/unknown types are tracked internally, but events
  are only emitted while the vessel is known to be a tanker (static data arriving late
  cannot retro-create earlier events).
- A fix is dropped if it is on land or implies > 40 kn from the last accepted fix. After
  SPOOF_RESYNC consecutive speed drops the new position is accepted (the first fix was bad).
- Barrels departed today: one contribution per voyage. A laden DEPARTED counts; a later laden
  outbound GATE_CROSS counts only if the voyage has not been counted yet. A voyage ends
  (flag reset) on BERTHED or an inbound gate crossing.
- distinct_tankers = tankers with a message in the region within the last 10 min.
- crossings are reported over rolling 24h/3d/7d windows. observed_h = hours (fractional) of those
  windows in which the region received >= 1 AIS message, so dead coverage does not drag rates down.
- Coverage health compares the last cov_recent_h hours (messages/h, distinct non-tanker and tanker MMSIs)
  with the median of the preceding 3-hour blocks. Time-of-day seasonality is ignored (a note for later:
  a same-hour-of-day baseline would need more history than we keep).
"""
import math
import re
import statistics
from collections import deque
from datetime import datetime, timezone

from aperium import zones
from aperium.contract import SCHEMA_VERSION
from aperium.regions import REGIONS, region_of

CONFIG = dict(
    tanker_types=range(80, 90),
    class_min_length=(("VLCC", 300), ("Suezmax", 250), ("Aframax", 220)),  # else "product"
    max_draft_m={"VLCC": 22.0, "Suezmax": 17.0, "Aframax": 14.5, "product": 12.0},
    laden_fraction=0.70,
    est_barrels={"VLCC": 2_000_000, "Suezmax": 1_000_000, "Aframax": 700_000, "product": 300_000},
    slow_kn=0.5, berth_s=30 * 60, max_speed_kn=40, spoof_min_km=0.5,
    present_s=2 * 3600, coverage_s=10 * 60, outbound_laden_s=6 * 3600, live_min_msgs=20,
    retain_s=7 * 86400, bucket_retain_s=8 * 86400,
    windows=(("24h", 24), ("3d", 72), ("7d", 168)),  # name, window_h
    cov_recent_h=3,  # recent window and baseline block length, hours
    cov_min_baseline_h=12,  # below this much history, coverage_status stays "ok"
    cov_gap_ratio=0.5, cov_degraded_ratio=0.8, cov_tanker_ratio=0.75,
)
SPOOF_RESYNC = 3
MMSI_RE = re.compile(r"[0-9]{9}")
TIME_RE = re.compile(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?")


def parse_time(text):
    """Epoch seconds from '2026-01-01 00:00:00.123456789 +0000 UTC' or ISO-8601; None if unparseable."""
    m = TIME_RE.match(text.strip()) if isinstance(text, str) else None
    if not m:
        return None
    y, mo, d, h, mi, s = map(int, m.groups()[:6])
    t = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp() + float(m.group(7) or 0)
    off = m.group(8)
    if off and off != "Z":
        sign = -1 if off[0] == "-" else 1
        t -= sign * (int(off[1:3]) * 3600 + int(off[-2:]) * 60)
    return t


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def message_time(message):
    meta = message.get("MetaData") or {}
    return parse_time(meta.get("time_utc")) or parse_time(message.get("received_at"))


def number(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def haversine_km(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def poisson_ci90(k):
    """Exact (Garwood) two-sided 90% interval [lo, hi] on a Poisson mean given count k."""
    from scipy.stats import chi2
    lo = chi2.ppf(0.05, 2 * k) / 2 if k > 0 else 0.0
    return lo, chi2.ppf(0.95, 2 * k + 2) / 2


def observed_hours(buckets, lo, hi):
    """Hours within [lo, hi] (epoch s) covered by hour buckets that received at least one message."""
    total = 0.0
    for h in range(int(lo // 3600), int(hi // 3600) + 1):
        if h in buckets:
            total += max(0.0, min(hi, (h + 1) * 3600) - max(lo, h * 3600)) / 3600
    return total


def ship_class(length):
    if not length:
        return None
    return next((name for name, low in CONFIG["class_min_length"] if length >= low), "product")


class Vessel:
    def __init__(self, mmsi):
        self.mmsi, self.name, self.imo, self.ship_type = mmsi, None, None, None
        self.length = self.draft = self.destination = None
        self.lat = self.lon = self.t = self.sog = self.heading = None
        self.region = self.zone = self.zone_kind = None
        self.rejects = 0
        self.anchored_since = self.slow_since = self.berth_zone = self.last_out = None
        self.departed_laden = self.counted = False

    is_tanker = property(lambda s: s.ship_type in CONFIG["tanker_types"])
    cls = property(lambda s: ship_class(s.length))
    slow = property(lambda s: s.sog is not None and s.sog < CONFIG["slow_kn"])

    @property
    def laden(self):
        if self.cls is None or not self.draft:
            return None
        return self.draft > CONFIG["laden_fraction"] * CONFIG["max_draft_m"][self.cls]

    def state(self, now):
        if self.berth_zone and self.zone == self.berth_zone:
            return "berthed"
        if self.zone_kind == "anchorage" and self.slow:
            return "anchored"
        recent_out = self.last_out is not None and now - self.last_out <= CONFIG["outbound_laden_s"]
        if self.laden and (recent_out or self.departed_laden):
            return "outbound_laden"
        return "underway"


class Engine:
    def __init__(self, replay=False):
        self.replay = replay
        self.vessels = {}
        self.now = 0.0
        self.dropped = {"speed": 0, "land": 0}
        self.coverage = {rid: deque() for rid in REGIONS}  # (t, mmsi) of every message in region
        # hour index -> [message count, non-tanker MMSIs (known non-tanker or unknown type), tanker MMSIs]
        self.hourly = {rid: {} for rid in REGIONS}
        self.crossings = []  # (t, region, direction, laden) tankers only
        self.barrels = []  # (t, region, mmsi, barrels), one per voyage

    def ingest(self, message):
        kind = message.get("MessageType")
        meta = message.get("MetaData") or {}
        body = (message.get("Message") or {}).get(kind) or {}
        t = message_time(message)
        mmsi = str(body.get("UserID", meta.get("MMSI", "")))
        if kind not in ("PositionReport", "ShipStaticData") or t is None or not MMSI_RE.fullmatch(mmsi):
            return []
        self.now = max(self.now, t)
        v = self.vessels.setdefault(mmsi, Vessel(mmsi))
        name = (meta.get("ShipName") or "").strip(" @")
        v.name = v.name or name or None
        if kind == "ShipStaticData":
            self._static(v, body)
            self._count(meta.get("latitude"), meta.get("longitude"), t, mmsi)
            return []
        lat = number(body.get("Latitude", meta.get("latitude")))
        lon = number(body.get("Longitude", meta.get("longitude")))
        if lat is None or lon is None or body.get("Valid") is False or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return []
        self._count(lat, lon, t, mmsi)
        return self._position(v, t, lat, lon, number(body.get("Sog")), body)

    def _count(self, lat, lon, t, mmsi):
        rid = region_of(lat, lon)
        if rid:
            q = self.coverage[rid]
            q.append((t, mmsi))
            while q and q[0][0] < self.now - CONFIG["coverage_s"]:
                q.popleft()
            buckets = self.hourly[rid]
            h = int(t // 3600)
            if h not in buckets:
                buckets[h] = [0, set(), set()]
                for old in [k for k in buckets if k * 3600 < self.now - CONFIG["bucket_retain_s"]]:
                    del buckets[old]
            b = buckets[h]
            b[0] += 1
            b[2 if self.vessels[mmsi].is_tanker else 1].add(mmsi)

    @staticmethod
    def _static(v, s):
        if isinstance(s.get("Type"), int):
            v.ship_type = s["Type"]
        d = s.get("Dimension") or {}
        length = (number(d.get("A")) or 0) + (number(d.get("B")) or 0)
        v.length = length or v.length
        v.draft = number(s.get("MaximumStaticDraught")) or v.draft
        imo = s.get("ImoNumber")
        v.imo = str(imo) if imo else v.imo
        dest = (s.get("Destination") or "").strip(" @")
        v.destination = dest or v.destination
        name = (s.get("Name") or "").strip(" @")
        v.name = name or v.name

    def _position(self, v, t, lat, lon, sog, body):
        if v.t is not None and t < v.t:
            return []  # out-of-order fix
        if v.t is not None:
            km = haversine_km(v.lat, v.lon, lat, lon)
            kn = km / 1.852 / max(t - v.t, 1.0) * 3600
            if kn > CONFIG["max_speed_kn"] and km > CONFIG["spoof_min_km"]:
                v.rejects += 1
                if v.rejects < SPOOF_RESYNC:
                    self.dropped["speed"] += 1
                    return []
        if zones.is_land(lat, lon):
            self.dropped["land"] += 1
            return []
        v.rejects = 0
        prev = (v.lat, v.lon) if v.t is not None and v.region else None
        v.lat, v.lon, v.t = lat, lon, t
        v.sog = sog if sog is not None and 0 <= sog < 102.3 else None
        heading = number(body.get("TrueHeading"))
        if heading is None or not 0 <= heading < 360:
            heading = number(body.get("Cog"))
        v.heading = heading if heading is not None and 0 <= heading < 360 else None
        region = region_of(lat, lon)
        if region != v.region:
            prev = None
        v.region = region
        if region is None:
            v.zone = v.zone_kind = None
            return []
        events = []
        zid, zkind = zones.zone_at(region, lat, lon)
        if v.zone != zid:
            events += self._leave(v, t, v.zone, v.zone_kind)
        if zkind == "anchorage" and v.slow and v.anchored_since is None:
            v.anchored_since = t
            events += self._event(v, t, "ANCHORED", zid)
        elif zkind == "terminal":
            if not v.slow:
                v.slow_since = None
            elif v.slow_since is None:
                v.slow_since = t
            if v.slow and v.berth_zone is None and t - v.slow_since > CONFIG["berth_s"]:
                v.berth_zone, v.counted, v.departed_laden = zid, False, False
                events += self._event(v, t, "BERTHED", zid)
        v.zone, v.zone_kind = zid, zkind
        cross = zones.gate_crossing(region, prev, (lat, lon))
        if cross:
            events += self._gate(v, t, region, *cross)
        return events

    def _leave(self, v, t, zid, zkind):
        v.slow_since = None
        if zkind == "anchorage":
            v.anchored_since = None
        if zkind == "terminal" and v.berth_zone == zid:
            v.berth_zone = None
            v.departed_laden = bool(v.laden)
            out = self._event(v, t, "DEPARTED", zid, barrels=True)
            self._count_barrels(v, t, out)
            return out
        return []

    def _gate(self, v, t, region, zid, direction):
        out = self._event(v, t, "GATE_CROSS", zid, direction, barrels=direction == "outbound")
        if v.is_tanker:
            self.crossings.append((t, region, direction, v.laden))
            self.crossings = [c for c in self.crossings if c[0] >= self.now - CONFIG["retain_s"]]
        if direction == "outbound":
            v.last_out = t
            self._count_barrels(v, t, out)
        else:
            v.last_out, v.counted, v.departed_laden = None, False, False
        return out

    def _count_barrels(self, v, t, events):
        if events and events[0]["est_barrels"] and not v.counted:
            v.counted = True
            self.barrels.append((t, v.region, v.mmsi, events[0]["est_barrels"]))

    def _event(self, v, t, kind, zid, direction=None, barrels=False):
        if not v.is_tanker:
            return []
        laden = v.laden
        est = CONFIG["est_barrels"][v.cls] if barrels and laden and v.cls else None
        return [dict(ts_utc=iso(t), mmsi=v.mmsi, name=v.name, type=kind, zone=zid, direction=direction,
                     laden=laden, est_barrels=est)]

    def snapshot(self, region, now=None):
        now = self.now if now is None else now
        present = sorted((v for v in self.vessels.values() if v.region == region and v.is_tanker
                          and now - v.t <= CONFIG["present_s"]), key=lambda v: v.mmsi)
        envelope = dict(schema_version=SCHEMA_VERSION, as_of_utc=iso(now), calibrated=False)
        vessels = [dict(mmsi=v.mmsi, name=v.name, imo=v.imo, **{"class": v.cls}, length_m=v.length,
                        draft_m=v.draft, laden=v.laden, state=v.state(now), lat=v.lat, lon=v.lon,
                        speed_kn=v.sog, heading=v.heading, destination=v.destination, zone=v.zone,
                        last_seen_utc=iso(v.t)) for v in present]
        states = [x["state"] for x in vessels]
        waits = [(now - v.anchored_since) / 3600 for v in present if v.state(now) == "anchored" and v.anchored_since]
        midnight = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight.timestamp()
        window = [(t, m) for t, m in self.coverage[region] if now - CONFIG["coverage_s"] < t <= now]
        n_msgs = len(window)
        tankers = {m for _, m in window if self.vessels[m].is_tanker}
        status = ("replay" if self.replay else "live" if n_msgs >= CONFIG["live_min_msgs"]
                  else "thin" if n_msgs else "no_data")
        metrics = dict(
            **envelope, region=region, tankers_present=len(present), waiting_at_anchor=states.count("anchored"),
            avg_wait_h=round(sum(waits) / len(waits), 2) if waits else None, berthed_now=states.count("berthed"),
            crossings=self._windows(region, now), laden_out_daily=self._daily(region, now, start),
            est_barrels_departed_today=sum(b for t, r, _, b in self.barrels if r == region and start <= t <= now),
            **self._coverage(region, now, status),
            data_coverage=dict(messages_last_10m=n_msgs, distinct_tankers=len(tankers), status=status))
        return dict(**envelope, region=region, vessels=vessels), metrics

    def _selected(self, region, lo, hi):
        return [c for c in self.crossings if c[1] == region and lo < c[0] <= hi]

    @staticmethod
    def _count_doc(k, observed):
        if observed < 1:
            return dict(count=k, per_day=None, per_day_ci90=None)
        lo, hi = poisson_ci90(k)
        return dict(count=k, per_day=round(k / observed * 24, 2),
                    per_day_ci90=[round(lo / observed * 24, 2), round(hi / observed * 24, 2)])

    def _windows(self, region, now):
        out = {}
        for name, hours in CONFIG["windows"]:
            lo = now - hours * 3600
            sel = self._selected(region, lo, now)
            observed = min(hours, observed_hours(self.hourly[region], lo, now))
            out[name] = dict(
                window_h=hours, observed_h=round(observed, 2),
                **{"in": self._count_doc(sum(c[2] == "inbound" for c in sel), observed)},
                out=self._count_doc(sum(c[2] == "outbound" for c in sel), observed),
                laden_out=self._count_doc(sum(c[2] == "outbound" and bool(c[3]) for c in sel), observed))
        return out

    def _daily(self, region, now, midnight):
        days = []
        for i in range(6, -1, -1):
            d0 = midnight - i * 86400
            hi = min(d0 + 86400, now)
            sel = [c for c in self.crossings if c[1] == region and d0 <= c[0] <= hi and c[2] == "outbound" and c[3]]
            days.append(dict(date=iso(d0)[:10], count=len(sel),
                             observed_h=round(observed_hours(self.hourly[region], d0, hi), 2) if hi > d0 else 0.0))
        return days

    def _coverage(self, region, now, status):
        n, buckets = CONFIG["cov_recent_h"], self.hourly[region]
        cur = int(now // 3600)
        recent = [buckets[h] for h in range(cur - n + 1, cur + 1) if h in buckets]
        elapsed = n - 1 + (now - cur * 3600) / 3600  # hours covered by the (partial) recent window
        msgs = sum(b[0] for b in recent) / max(elapsed, 1e-9)
        tankers = set().union(*[b[2] for b in recent]) if recent else set()
        non_tankers = set().union(*[b[1] for b in recent]) - tankers if recent else set()
        first = min(buckets, default=None)
        blocks = []  # (msgs/h, non-tankers, tankers) per fully-past 3 h block, newest first
        top = cur - n
        while first is not None and top - n + 1 >= max(first, cur - CONFIG["retain_s"] // 3600):
            bs = [buckets[h] for h in range(top - n + 1, top + 1) if h in buckets]
            t = set().union(*[b[2] for b in bs]) if bs else set()
            nt = (set().union(*[b[1] for b in bs]) if bs else set()) - t
            blocks.append((sum(b[0] for b in bs) / n, len(nt), len(t)))
            top -= n
        baseline_h = len(blocks) * n
        ok = baseline_h >= CONFIG["cov_min_baseline_h"]
        med = (lambda i: statistics.median(b[i] for b in blocks)) if ok else (lambda i: None)
        base_msgs, base_nt, base_t = med(0), med(1), med(2)
        ratio = lambda x, base: 1.0 if not base else x / base
        coverage = "ok"
        if ok:
            cov = min(ratio(msgs, base_msgs), ratio(len(non_tankers), base_nt))
            if cov < CONFIG["cov_gap_ratio"] and ratio(len(tankers), base_t) < CONFIG["cov_tanker_ratio"]:
                coverage = "data_gap"
            elif cov < CONFIG["cov_degraded_ratio"]:
                coverage = "degraded"
        if status == "no_data" and first is not None and first < cur:
            coverage = "data_gap"
        r = lambda x: None if x is None else round(x, 2)
        return dict(coverage_status=coverage, coverage=dict(
            window_h=n, messages_per_h=r(msgs), messages_per_h_baseline=r(base_msgs),
            non_tankers=len(non_tankers), non_tankers_baseline=r(base_nt),
            tankers=len(tankers), tankers_baseline=r(base_t), baseline_hours=baseline_h))
