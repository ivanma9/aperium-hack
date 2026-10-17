"""AIS observations; the discovery box is not an official anchorage boundary."""
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PORTS = {
    "fujairah": {"name": "Fujairah", "bounds_lat_lon": [[25.05, 56.32], [25.28, 56.65]]},
    "shahid_rajaee": {"name": "Shahid Rajaee", "bounds_lat_lon": [[26.95, 55.95], [27.18, 56.20]]},
    "khor_fakkan": {"name": "Khor Fakkan", "bounds_lat_lon": [[25.30, 56.32], [25.45, 56.55]]},
    "jebel_ali": {"name": "Jebel Ali", "bounds_lat_lon": [[24.90, 54.95], [25.12, 55.15]]},
}
# Preserve the original Fujairah constant for callers using it.
BOUNDS = PORTS["fujairah"]["bounds_lat_lon"]
BOUNDING_BOXES = [port["bounds_lat_lon"] for port in PORTS.values()]
POSITION_TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"]


def matching_ports(lat, lon):
    return [key for key, port in PORTS.items()
            if port["bounds_lat_lon"][0][0] <= lat <= port["bounds_lat_lon"][1][0]
            and port["bounds_lat_lon"][0][1] <= lon <= port["bounds_lat_lon"][1][1]]


def inside(lat, lon):
    return bool(matching_ports(lat, lon))


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


class Store:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                mmsi TEXT, name TEXT, latitude REAL, longitude REAL,
                speed_knots REAL, course REAL, nav_status INTEGER,
                observed_at REAL, received_at REAL, time_source TEXT,
                UNIQUE(mmsi, observed_at, latitude, longitude)
            );
            CREATE INDEX IF NOT EXISTS position_history ON positions(mmsi, observed_at);
            CREATE TABLE IF NOT EXISTS latest (
                mmsi TEXT PRIMARY KEY, name TEXT, latitude REAL, longitude REAL,
                speed_knots REAL, course REAL, nav_status INTEGER,
                observed_at REAL, received_at REAL, time_source TEXT
            );
        """)

    def save(self, position):
        columns = list(position)
        names = ','.join(columns)
        placeholders = ','.join('?' for _ in columns)
        updates = ','.join(f'{key}=excluded.{key}' for key in columns if key != 'mmsi')
        with self.db:
            self.db.execute(f"INSERT OR IGNORE INTO positions ({names}) VALUES ({placeholders})", list(position.values()))
            self.db.execute(f"INSERT INTO latest ({names}) VALUES ({placeholders}) ON CONFLICT(mmsi) DO UPDATE SET {updates} WHERE excluded.observed_at >= latest.observed_at", list(position.values()))

    def vessels(self, now, stale_seconds):
        result = []
        for row in self.db.execute("SELECT * FROM latest ORDER BY observed_at DESC"):
            item = dict(row)
            item["age_seconds"] = max(0, round(now - item["observed_at"], 1))
            item["stale"] = now - item["observed_at"] > stale_seconds
            item["inside_geofence"] = inside(item["latitude"], item["longitude"])
            item["ports"] = matching_ports(item["latitude"], item["longitude"])
            result.append(item)
        return result

    def history(self, mmsi, limit):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM positions WHERE mmsi=? ORDER BY observed_at DESC LIMIT ?", (mmsi, limit))]

    def close(self):
        self.db.close()
