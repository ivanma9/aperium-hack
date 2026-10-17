import os

import psycopg
import pytest
from dotenv import load_dotenv

from aperium.db import database_url as env_database_url, redacted

load_dotenv()


def resolve_test_database_url():
    """TEST_DATABASE_URL, else the dev connection settings (.env) pointed at `aperium_test`."""
    return os.getenv("TEST_DATABASE_URL") or env_database_url(dbname="aperium_test")


@pytest.fixture
def database_url():
    """Empty test database (schema + seeded geographies/ports, no positions)."""
    try:
        url = resolve_test_database_url()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    if not psycopg.conninfo.conninfo_to_dict(url).get('dbname','').endswith('_test'):
        pytest.fail('Refusing destructive test setup: database name must end in _test')
    try:
        with psycopg.connect(url, connect_timeout=3, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS positions, latest, vessel_profiles, analytics_boundaries, ports, geographies CASCADE")
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable at {redacted(url)} ({type(exc).__name__}); run `docker compose up -d db`")
    return url
