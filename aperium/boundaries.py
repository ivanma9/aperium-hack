"""Import reviewed terminal/anchorage geometry: python -m aperium.boundaries FILE.json.

This is a local administrative command, not an unauthenticated HTTP mutation.
The file is an array of Boundary objects. It never deletes unspecified boundaries.
"""
import argparse
import asyncio

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from aperium.analytics import load_boundaries
from aperium.db import Store, database_url


async def import_boundaries(path):
    boundaries = load_boundaries(path)
    load_dotenv()
    store = await Store.open(database_url())
    try:
        geos = {g['id'] for g in await store.geographies()}
        ports = {p['id']:p['geography_id'] for p in await store.ports()}
        for b in boundaries:
            if b.geography_id not in geos:
                raise ValueError(f'Unknown geography for {b.id}')
            if b.kind != 'checkpoint' and ports.get(b.port) != b.geography_id:
                raise ValueError(f'Boundary {b.id} must reference a port in its geography')
        async with store.pool.connection() as conn:
            async with conn.transaction():
                for b in boundaries:
                    await conn.execute('''INSERT INTO analytics_boundaries (id,geography_id,data) VALUES (%s,%s,%s)
                        ON CONFLICT (id) DO UPDATE SET geography_id=excluded.geography_id,data=excluded.data''',
                        (b.id,b.geography_id,Jsonb(b.model_dump())))
        print(f'Imported {len(boundaries)} boundaries. Restart the backend to refresh subscriptions and analytics.')
    finally:
        await store.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file')
    asyncio.run(import_boundaries(parser.parse_args().file))
