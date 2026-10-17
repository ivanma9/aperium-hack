import asyncio
import os

import psycopg
import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql://aperium:aperium@127.0.0.1:5434/aperium_test")


@pytest.fixture
def database_url():
    """Empty test database (schema + seeded geographies/ports, no positions).

    Needs Postgres: `docker compose up -d db` (creates `aperium_test`) or TEST_DATABASE_URL.
    """
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS positions, latest, ports, geographies CASCADE")
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable at TEST_DATABASE_URL ({type(exc).__name__}); run `docker compose up -d db`")
    return TEST_DATABASE_URL


def run(coro):
    return asyncio.run(coro)
