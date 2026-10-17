"""Run the state engine: tail today's raw AIS file (live) or replay a recorded one.

Writes OUT/regions.json and OUT/{region}/{vessels,metrics}.json, appends OUT/{region}/events.jsonl.
Run: uv run python -m aperium.run                                    (live tail)
     uv run python -m aperium.run --replay data/x.jsonl --speed 30   (0 = as fast as possible)
"""
import argparse
import importlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aperium import zones
from aperium.contract import SCHEMA_VERSION, validate
from aperium.recorder import raw_path
from aperium.regions import REGIONS
from aperium.state import Engine, iso, message_time

WRITE_EVERY_S = 10
HOOKS = (("aperium.sentinel", 10 * 60), ("aperium.cpi_nowcast", 30 * 60))
log = logging.getLogger("aperium.run")


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def checked(name, doc, strict):
    try:
        validate(name, doc)
        return True
    except Exception as exc:
        if strict:
            raise
        log.error("%s failed validation, skipped: %s", name, str(exc)[:200])
        return False


def write_outputs(engine, out, now, events, strict=False):
    """Write all JSON docs for `now` and append `events` (list of event dicts) to events.jsonl."""
    regions = {"schema_version": SCHEMA_VERSION, "as_of_utc": iso(now), "calibrated": False, "regions": [
        dict(id=rid, name=r["name"], role=r["role"], bbox=r["bbox"], zones=zones.geojson(rid))
        for rid, r in REGIONS.items()]}
    if checked("regions", regions, strict):
        atomic_write(out / "regions.json", json.dumps(regions, indent=2))
    by_region = {rid: [] for rid in REGIONS}
    for e in events:
        by_region[zones.zone_region(e["zone"])].append(e)
    for rid in REGIONS:
        vessels, metrics = engine.snapshot(rid, now)
        if checked("vessels", vessels, strict):
            atomic_write(out / rid / "vessels.json", json.dumps(vessels, indent=2))
        if checked("metrics", metrics, strict):
            atomic_write(out / rid / "metrics.json", json.dumps(metrics, indent=2))
        good = [e for e in by_region[rid] if checked("event", e, strict)]
        if good:
            (out / rid).mkdir(parents=True, exist_ok=True)
            with open(out / rid / "events.jsonl", "a") as f:
                f.writelines(json.dumps(e) + "\n" for e in good)


class Hooks:
    """Optional sentinel / CPI writers; absence or failure never breaks the loop."""

    def __init__(self):
        self.last = {}

    def run(self, out):
        for name, every in HOOKS:
            if time.monotonic() - self.last.get(name, -1e9) < every:
                continue
            self.last[name] = time.monotonic()
            try:
                importlib.import_module(name).write(out)
            except Exception as exc:
                log.warning("%s.write skipped: %s", name, exc)


def event_key(e):
    return (e["ts_utc"], e["mmsi"], e["type"], e["zone"])


def replay(path, speed, out, strict=False, hooks=True):
    engine, h, events, last_write, prev_t = Engine(replay=True), Hooks(), [], time.monotonic(), None
    for rid in REGIONS:
        (out / rid / "events.jsonl").unlink(missing_ok=True)
    with open(path) as f:
        for line in f:
            try:
                message = json.loads(line)
                t = message_time(message)
            except ValueError:
                continue
            if speed > 0 and prev_t is not None and t is not None and t > prev_t:
                time.sleep((t - prev_t) / speed)
            prev_t = t if t is not None else prev_t
            events += engine.ingest(message)
            if speed > 0 and time.monotonic() - last_write >= WRITE_EVERY_S:
                write_outputs(engine, out, engine.now, events, strict)
                events, last_write = [], time.monotonic()
                if hooks:
                    h.run(out)
    write_outputs(engine, out, engine.now, events, strict)
    if hooks:
        h.run(out)
    return engine


def feed(engine, text, seen):
    events = []
    for line in text.splitlines():
        try:
            new = engine.ingest(json.loads(line))
        except ValueError:
            continue
        for e in new:
            if event_key(e) not in seen:
                seen.add(event_key(e))
                events.append(e)
    return events


def warm_start(engine, seen, days=7):
    """Feed the last `days` UTC days of recorded files before today's (oldest first) so long windows survive restarts."""
    today, events = datetime.now(timezone.utc), []
    for back in range(days, 0, -1):
        path = raw_path(today - timedelta(days=back))
        if path.exists():
            log.info("warm start: %s", path)
            events += feed(engine, path.read_text(), seen)  # events already in events.jsonl are skipped via `seen`
    return events


def live(out, strict=False, hooks=True):
    engine, h, f, current, buf, events, last_write = Engine(), Hooks(), None, None, "", [], 0.0
    seen = set()
    for rid in REGIONS:
        p = out / rid / "events.jsonl"
        if p.exists():  # state rebuilds from the start of today's file; skip events already written
            seen |= {event_key(json.loads(x)) for x in p.read_text().splitlines() if x.strip()}
    events += warm_start(engine, seen)
    while True:
        path = raw_path()
        if path != current and path.exists():
            if f:  # drain the old file before rotating at UTC midnight
                events += feed(engine, buf + f.read(), seen)
                f.close()
            f, current, buf = open(path), path, ""
        if f:
            complete, _, buf = (buf + f.read()).rpartition("\n")  # keep a partial last line for next poll
            events += feed(engine, complete, seen)
        if time.monotonic() - last_write >= WRITE_EVERY_S:
            write_outputs(engine, out, time.time(), events, strict)
            events, last_write = [], time.monotonic()
            if hooks:
                h.run(out)
        time.sleep(1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", type=Path, help="recorded raw JSONL to feed through the engine")
    ap.add_argument("--speed", type=float, default=30, help="replay speed multiplier; 0 = as fast as possible")
    ap.add_argument("--out", type=Path, default=Path("outputs/latest"))
    ap.add_argument("--strict", action="store_true", help="raise on schema validation failure")
    ap.add_argument("--no-hooks", action="store_true", help="skip sentinel / cpi_nowcast writers")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if a.replay:
        engine = replay(a.replay, a.speed, a.out, a.strict, not a.no_hooks)
        print(f"replayed to {iso(engine.now)}; dropped {engine.dropped}; wrote {a.out}")
    else:
        live(a.out, a.strict, not a.no_hooks)


if __name__ == "__main__":
    main()
