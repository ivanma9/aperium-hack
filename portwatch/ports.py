"""Load and validate ports.yaml."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "ports.yaml"


class UnknownPortError(KeyError):
    pass


@dataclass(frozen=True)
class Exclusion:
    bbox: tuple                      # lon0, lat0, lon1, lat1
    note: str = ""


@dataclass(frozen=True)
class Port:
    name: str
    bbox: tuple                      # lon0, lat0, lon1, lat1
    notes: str = ""
    reference_from: str = None       # optional per-port override of config.REFERENCE_FROM / _TO
    reference_to: str = None
    exclude: tuple = ()              # Exclusion boxes: water pixels inside are not counted

    @property
    def reference_window(self):
        return (self.reference_from or config.REFERENCE_FROM, self.reference_to or config.REFERENCE_TO)


def _validate_bbox(name, bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        raise ValueError(f"port {name!r}: bbox must be [lon0, lat0, lon1, lat1], got {bbox!r}")
    lon0, lat0, lon1, lat1 = bbox
    if lon0 >= lon1 or lat0 >= lat1:
        raise ValueError(f"port {name!r}: bbox needs lon0 < lon1 and lat0 < lat1, got {list(bbox)}")
    if not (-180 <= lon0 and lon1 <= 180 and -90 <= lat0 and lat1 <= 90):
        raise ValueError(f"port {name!r}: bbox is outside the WGS84 range, got {list(bbox)}")
    return tuple(float(v) for v in bbox)


def _stamp(name, field, value):
    """A reference-window time as an ISO string ending in Z. Accepts an ISO string with an explicit Z or +00:00,
    or the timezone-aware datetime YAML makes of an unquoted one. Naive times and dates are refused: a window
    edge that depends on the machine's timezone would silently change reference_id."""
    if value is None:
        return None
    label = f"port {name!r}: reference.{field}"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{label} is a naive timestamp {value.isoformat()!r}; add Z or +00:00")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str) or not (value.endswith("Z") or value.endswith("+00:00")):
        raise ValueError(f"{label} must be an ISO timestamp ending in Z or +00:00, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as e:
        raise ValueError(f"{label} is not an ISO timestamp: {value!r}") from e
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exclusions(name, raw):
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"port {name!r}: exclude must be a list of {{bbox: [...], note: ...}}, got {raw!r}")
    out = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or "bbox" not in entry:
            raise ValueError(f"port {name!r}: exclude[{i}] needs a bbox, got {entry!r}")
        out.append(Exclusion(bbox=_validate_bbox(f"{name} exclude[{i}]", entry["bbox"]), note=str(entry.get("note", ""))))
    return tuple(out)


def load_ports(path=DEFAULT_PATH):
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    ports = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict) or "bbox" not in spec:
            raise ValueError(f"port {name!r}: needs a bbox")
        ref = spec.get("reference") or {}
        ports[name] = Port(name=name, bbox=_validate_bbox(name, spec["bbox"]), notes=str(spec.get("notes", "")),
                           reference_from=_stamp(name, "from", ref.get("from")),
                           reference_to=_stamp(name, "to", ref.get("to")),
                           exclude=_exclusions(name, spec.get("exclude")))
    return ports


def get_port(name, ports=None):
    ports = load_ports() if ports is None else ports
    if name not in ports:
        raise UnknownPortError(f"unknown port {name!r}; valid ports: {', '.join(sorted(ports))}")
    return ports[name]
