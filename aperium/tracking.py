"""AIS message normalization and geofence matching.

Geofences come from the `ports` table (see aperium/db.py); a discovery box is not an
official anchorage boundary.
"""
import math
import re
from datetime import datetime, timezone

POSITION_TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"]
STATIC_TYPES = ["ShipStaticData", "StaticDataReport"]


def static_profile(message, received_at):
    """Mergeable AIS profile fields; absent/zero type does not erase known identity."""
    kind = message.get("MessageType")
    if kind not in STATIC_TYPES + ["ExtendedClassBPositionReport"]:
        return None
    report = message.get("Message", {}).get(kind, {})
    mmsi = str(report.get("UserID", ""))
    if report.get("Valid") is False or not re.fullmatch(r"[1-9][0-9]{8}", mmsi):
        return None
    data = report
    if kind == "StaticDataReport":
        data = report.get("ReportB" if report.get("PartNumber") else "ReportA", {})
        if data.get("Valid") is False:
            return None
    result = {"mmsi": mmsi, "updated_at": received_at, "source": "ais_self_reported"}
    name = str(data.get("Name") or "").strip(" @")
    if name:
        result["name"] = name
    code = number(data.get("Type", data.get("ShipType")))
    if code is not None and code.is_integer() and 1 <= code <= 99:
        code = int(code)
        result.update(ship_type=code, vessel_class="tanker" if 80 <= code <= 89 else
                      ("cargo" if 70 <= code <= 79 else "other"), classification_updated_at=received_at)
    imo = number(data.get("ImoNumber"))
    if imo and imo.is_integer() and 1000000 <= imo <= 9999999:
        result["imo"] = int(imo)
    return result if len(result) > 3 else None


def bounding_boxes(ports):
    """AISstream subscription boxes ([[lat, lon], [lat, lon]]) for the given geofences."""
    return [port["bounds_lat_lon"] for port in ports]


def matching_ports(lat, lon, ports):
    """IDs of the geofences (from the `ports` table) that contain the point."""
    return [port["id"] for port in ports
            if port["bounds_lat_lon"][0][0] <= lat <= port["bounds_lat_lon"][1][0]
            and port["bounds_lat_lon"][0][1] <= lon <= port["bounds_lat_lon"][1][1]]


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalize(message, received_at):
    kind = message.get("MessageType")
    if kind not in POSITION_TYPES:
        return None
    report = message.get("Message", {}).get(kind, {})
    meta = message.get("MetaData", {})
    if report.get("Valid") is False:
        return None
    mmsi = str(report.get("UserID", meta.get("MMSI", "")))
    if not re.fullmatch(r"[1-9][0-9]{8}", mmsi):
        return None
    lat = number(report.get("Latitude", meta.get("latitude", meta.get("Latitude"))))
    lon = number(report.get("Longitude", meta.get("longitude", meta.get("Longitude"))))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    observed_at, time_source = received_at, "local_receipt"
    if meta.get("time_utc"):
        timestamp = re.sub(r"\s+[A-Z]{2,5}$", "", meta["time_utc"]).strip()
        timestamp = re.sub(r"(\.\d{6})\d+", r"\1", timestamp)
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            observed_at = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
            time_source = "provider"
        except (ValueError, TypeError):
            return None
        if observed_at > received_at + 60:
            return None
    speed, course = number(report.get("Sog")), number(report.get("Cog"))
    return dict(mmsi=mmsi, name=str(meta.get("ShipName", "")).strip(" @"),
                latitude=lat, longitude=lon,
                speed_knots=speed if speed is not None and 0 <= speed < 102.3 else None,
                course=course if course is not None and 0 <= course < 360 else None,
                nav_status=report.get("NavigationalStatus"), observed_at=observed_at,
                received_at=received_at, time_source=time_source)
