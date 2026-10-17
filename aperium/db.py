"""Postgres storage: geographies, port geofences, AIS positions, and change events.

Tables: `geographies` (monitored chokepoints: framing bbox, lanes, gates, model
parameters), `ports` (geofences, each belonging to a geography), `positions`
(append-only AIS history) and `latest` (one row per MMSI).

Every insert or update of `latest` fires `pg_notify('vessel_positions', <row json>)`.
The app LISTENs on that channel and fans events out to SSE clients (/api/stream).
"""
import json
import os
from typing import Optional

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from aperium import seed
from aperium.tracking import matching_ports

CHANNEL = "vessel_positions"


def database_url(dbname: Optional[str] = None) -> str:
    """Connection string from the environment (.env): DATABASE_URL if set, else the
    compose.yaml settings (POSTGRES_PASSWORD required; POSTGRES_USER, POSTGRES_DB and
    APERIUM_DB_PORT have defaults). `dbname` swaps the database (tests use aperium_test).
    No password is ever defaulted."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return make_conninfo(url, dbname=dbname) if dbname else url
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("Set POSTGRES_PASSWORD (or DATABASE_URL) in .env; ./dev.sh generates one.")
    return make_conninfo(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=os.getenv("APERIUM_DB_PORT", "5434"),
        user=os.getenv("POSTGRES_USER", "aperium"),
        password=password,
        dbname=dbname or os.getenv("POSTGRES_DB", "aperium"),
    )


def redacted(dsn: str) -> str:
    """DSN for log/error messages, without the password."""
    parts = conninfo_to_dict(dsn)
    parts.pop("password", None)
    return make_conninfo(**parts)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS geographies (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    short_name TEXT NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    base_mbd DOUBLE PRECISION NOT NULL,
    bypass_cap_mbd DOUBLE PRECISION NOT NULL,
    bypass_label TEXT NOT NULL,
    premium_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1,
    bbox JSONB NOT NULL,
    imagery_provider TEXT,
    lanes JSONB NOT NULL,
    lane_offset_px DOUBLE PRECISION,
    gates JSONB NOT NULL,
    destinations JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS ports (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    geography_id TEXT REFERENCES geographies(id) ON DELETE SET NULL,
    south DOUBLE PRECISION NOT NULL,
    west DOUBLE PRECISION NOT NULL,
    north DOUBLE PRECISION NOT NULL,
    east DOUBLE PRECISION NOT NULL,
    boundary_type TEXT NOT NULL DEFAULT 'approximate_discovery_box',
    CHECK (south < north AND west < east)
);
CREATE TABLE IF NOT EXISTS positions (
    mmsi TEXT NOT NULL, name TEXT, latitude DOUBLE PRECISION, longitude DOUBLE PRECISION,
    speed_knots DOUBLE PRECISION, course DOUBLE PRECISION, nav_status INTEGER,
    observed_at DOUBLE PRECISION, received_at DOUBLE PRECISION, time_source TEXT,
    UNIQUE (mmsi, observed_at, latitude, longitude)
);
CREATE INDEX IF NOT EXISTS position_history ON positions (mmsi, observed_at);
CREATE TABLE IF NOT EXISTS latest (
    mmsi TEXT PRIMARY KEY, name TEXT, latitude DOUBLE PRECISION, longitude DOUBLE PRECISION,
    speed_knots DOUBLE PRECISION, course DOUBLE PRECISION, nav_status INTEGER,
    observed_at DOUBLE PRECISION, received_at DOUBLE PRECISION, time_source TEXT
);
CREATE OR REPLACE FUNCTION notify_latest() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('{CHANNEL}', row_to_json(NEW)::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER latest_notify AFTER INSERT OR UPDATE ON latest
    FOR EACH ROW EXECUTE FUNCTION notify_latest();
"""

POSITION_COLUMNS = ["mmsi", "name", "latitude", "longitude", "speed_knots", "course", "nav_status",
                    "observed_at", "received_at", "time_source"]
GEOGRAPHY_COLUMNS = ["id", "slug", "short_name", "name", "sort_order", "base_mbd", "bypass_cap_mbd", "bypass_label",
                    "premium_multiplier", "bbox", "imagery_provider", "lanes", "lane_offset_px", "gates", "destinations"]
JSON_COLUMNS = {"bbox", "lanes", "gates", "destinations"}


def describe(row, now, stale_seconds, ports):
    """API shape of a vessel: the stored row plus freshness and geofence membership."""
    item = dict(row)
    item["age_seconds"] = max(0, round(now - item["observed_at"], 1))
    item["stale"] = now - item["observed_at"] > stale_seconds
    item["ports"] = matching_ports(item["latitude"], item["longitude"], ports)
    item["inside_geofence"] = bool(item["ports"])
    return item


def port_row(row):
    return {"id": row["id"], "name": row["name"], "geography_id": row["geography_id"],
            "bounds_lat_lon": [[row["south"], row["west"]], [row["north"], row["east"]]],
            "boundary_type": row["boundary_type"]}


class Store:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    @classmethod
    async def open(cls, dsn: str):
        pool = AsyncConnectionPool(dsn, open=False, min_size=1, max_size=5,
                                   kwargs={"autocommit": True, "row_factory": dict_row})
        await pool.open(wait=True, timeout=15)
        store = cls(pool)
        await store.migrate()
        return store

    async def migrate(self):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                # Serialize concurrent startups (e.g. reloader + tests) applying the schema.
                await conn.execute("SELECT pg_advisory_xact_lock(4247001)")
                await conn.execute(SCHEMA)
                for geo in seed.GEOGRAPHIES:
                    values = [Jsonb(geo[c]) if c in JSON_COLUMNS else geo[c] for c in GEOGRAPHY_COLUMNS]
                    await conn.execute(
                        f"INSERT INTO geographies ({','.join(GEOGRAPHY_COLUMNS)}) "
                        f"VALUES ({','.join(['%s'] * len(GEOGRAPHY_COLUMNS))}) ON CONFLICT (id) DO NOTHING", values)
                for p in seed.PORTS:
                    (south, west), (north, east) = p["bounds_lat_lon"]
                    await conn.execute(
                        "INSERT INTO ports (id, name, geography_id, south, west, north, east) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                        [p["id"], p["name"], p["geography_id"], south, west, north, east])

    async def save(self, position):
        columns = [c for c in POSITION_COLUMNS if c in position]
        values = [position[c] for c in columns]
        names = ",".join(columns)
        placeholders = ",".join(["%s"] * len(columns))
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c != "mmsi")
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(f"INSERT INTO positions ({names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING", values)
                await conn.execute(
                    f"INSERT INTO latest ({names}) VALUES ({placeholders}) ON CONFLICT (mmsi) DO UPDATE SET {updates} "
                    "WHERE excluded.observed_at >= latest.observed_at", values)

    async def vessels(self, now, stale_seconds, ports):
        async with self.pool.connection() as conn:
            rows = await (await conn.execute("SELECT * FROM latest ORDER BY observed_at DESC")).fetchall()
        return [describe(r, now, stale_seconds, ports) for r in rows]

    async def history(self, mmsi, limit):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM positions WHERE mmsi=%s ORDER BY observed_at DESC LIMIT %s", [mmsi, limit])
            return await cur.fetchall()

    async def ports(self, geography_id: Optional[str] = None):
        async with self.pool.connection() as conn:
            if geography_id is None:
                cur = await conn.execute("SELECT * FROM ports ORDER BY id")
            else:
                cur = await conn.execute("SELECT * FROM ports WHERE geography_id=%s ORDER BY id", [geography_id])
            return [port_row(r) for r in await cur.fetchall()]

    async def geographies(self):
        """Monitored geographies (chokepoints), each with its port geofences."""
        async with self.pool.connection() as conn:
            rows = await (await conn.execute("SELECT * FROM geographies ORDER BY sort_order, id")).fetchall()
        ports = await self.ports()
        return [{**r, "ports": [p for p in ports if p["geography_id"] == r["id"]]} for r in rows]

    async def clear_positions(self):
        """Test helper: drop all observations, keep geographies and ports."""
        async with self.pool.connection() as conn:
            await conn.execute("TRUNCATE positions, latest")

    async def close(self):
        await self.pool.close()


def decode_notification(payload: str):
    return json.loads(payload)
