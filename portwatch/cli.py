"""python -m portwatch ports | search | run"""
import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config
from . import copernicus as cop
from .ports import DEFAULT_PATH, UnknownPortError, get_port, load_ports

logger = logging.getLogger("portwatch.cli")
_attached = []                    # handlers main() added to the "portwatch" logger, removed again on the way out


def cmd_ports(args):
    for p in load_ports(args.ports_file).values():
        print(f"{p.name:<22} bbox {list(p.bbox)}  reference {p.reference_window[0][:10]} to {p.reference_window[1][:10]}")
        if p.notes:
            print(f"{'':<22} {p.notes}")
        for e in p.exclude:
            print(f"{'':<22} exclude {list(e.bbox)}  {e.note}")


def cmd_search(args):
    port = get_port(args.port, load_ports(args.ports_file))
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    scenes = cop.search_s1(port.bbox, since)
    print(f"{port.name} {list(port.bbox)}: {len(scenes)} Sentinel-1 IW GRD pass(es) since {since:%Y-%m-%d}")
    by_orbit = {}
    for s in scenes:
        by_orbit.setdefault((s["relative_orbit"], s["orbit_direction"]), []).append(s)
    for (orbit, direction), group in sorted(by_orbit.items(), key=lambda kv: (kv[0][0] is None, kv[0][0])):
        dates = ", ".join(f"{s['start']:%m-%d}" for s in group)
        print(f"  relative orbit {orbit} {direction}: {len(group)} pass(es)  [{dates}]")
    for s in scenes:
        print(f"    {s['start']:%Y-%m-%d %H:%M:%SZ}  {s['platform']}  orbit {s['relative_orbit']}  {s['name']}")


def _attach(handler, fmt):
    handler.setFormatter(logging.Formatter(fmt))
    logging.getLogger("portwatch").addHandler(handler)
    _attached.append(handler)


class _BelowError(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.ERROR


def cmd_run(args):
    from dotenv import load_dotenv
    from .pipeline import run_port

    port = get_port(args.port, load_ports(args.ports_file))
    load_dotenv()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    _attach(logging.FileHandler(data_dir / "run.log"), "%(asctime)s %(name)s %(levelname)s %(message)s")
    tokens = cop.TokenSource.from_env()
    summary = run_port(
        port, days=args.days, data_dir=data_dir, refresh=args.refresh,
        search_fn=lambda bbox, since: cop.search_s1(bbox, since),
        fetch_fn=lambda scene, bbox: cop.fetch_s1_raw(scene, bbox, tokens.get),
        log=logging.getLogger("portwatch.pipeline").info)
    for orbit, info in sorted(summary["orbits"].items()):
        print(f"orbit {orbit}: {info['status']}, {info.get('processed', 0)} counted, {info.get('skipped', 0)} already done")
    if any(i["status"] != "ok" for i in summary["orbits"].values()):
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="portwatch", description=__doc__)
    ap.add_argument("--ports-file", type=Path, default=DEFAULT_PATH, help="ports.yaml (default: the one in the repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list the configured ports").set_defaults(fn=cmd_ports)
    s = sub.add_parser("search", help="list Sentinel-1 passes over a port (public catalogue, no credentials)")
    s.add_argument("--port", required=True)
    s.add_argument("--days", type=int, default=40)
    s.set_defaults(fn=cmd_search)
    r = sub.add_parser("run", help="count ships in recent passes and append to parquet (needs CDSE credentials)")
    r.add_argument("--port", required=True)
    r.add_argument("--days", type=int, required=True)
    r.add_argument("--refresh", action="store_true", help="refetch cached passes and rebuild the reference")
    r.add_argument("--data-dir", default="data")
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args(argv)
    top = logging.getLogger("portwatch")
    level = top.level
    top.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stdout)       # the file handler of `run` is added by cmd_run
    console.addFilter(_BelowError())                  # errors are printed once, by the handler below
    _attach(console, "%(message)s")
    try:
        code = args.fn(args)
    except UnknownPortError as e:
        print(e.args[0], file=sys.stderr)
        code = 2
    except cop.CopernicusError as e:
        logger.exception("%s: %s", type(e).__name__, e)     # the traceback goes to run.log
        print(f"ERROR: {e}", file=sys.stderr)
        code = 1
    finally:
        for h in _attached:
            top.removeHandler(h)
            h.close()
        _attached.clear()
        top.setLevel(level)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
