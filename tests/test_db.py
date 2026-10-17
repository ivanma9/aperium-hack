import asyncio

from aperium import seed
from aperium.db import Store
from aperium.tracking import normalize
from test_tracking import message

PORTS = [{"id": p["id"], "bounds_lat_lon": p["bounds_lat_lon"]} for p in seed.PORTS]


def test_deduplication_out_of_order_staleness_and_restart(database_url):
    async def scenario():
        store = await Store.open(database_url)
        newer = normalize(message(), 200)
        await store.save(newer)
        await store.save(newer)
        await store.save(normalize(message(Latitude=25.2), 100))
        assert len(await store.history('123456789', 100)) == 2
        assert (await store.vessels(250, 60, PORTS))[0]['latitude'] == 25.16
        assert not (await store.vessels(250, 60, PORTS))[0]['stale']
        assert (await store.vessels(261, 60, PORTS))[0]['stale']
        await store.close()
        store = await Store.open(database_url)  # data survives a restart; migrate is idempotent
        assert len(await store.vessels(250, 60, PORTS)) == 1
        await store.save(normalize(message(Latitude=26), 300))
        assert not (await store.vessels(310, 60, PORTS))[0]['inside_geofence']
        await store.close()
    asyncio.run(scenario())


def test_geographies_and_ports_are_seeded_once(database_url):
    async def scenario():
        store = await Store.open(database_url)
        geos = await store.geographies()
        assert [g["id"] for g in geos] == [g["id"] for g in seed.GEOGRAPHIES]
        hormuz = geos[0]
        assert sorted(p["id"] for p in hormuz["ports"]) == sorted(p["id"] for p in seed.PORTS)
        assert hormuz["lanes"]["outbound"][0] == seed.GEOGRAPHIES[0]["lanes"]["outbound"][0]
        # Edits in the database survive a restart (seed is insert-if-missing).
        async with store.pool.connection() as conn:
            await conn.execute("UPDATE geographies SET name='Hormuz (edited)' WHERE id='hormuz'")
        await store.close()
        store = await Store.open(database_url)
        assert (await store.geographies())[0]["name"] == "Hormuz (edited)"
        assert len(await store.ports("hormuz")) == 4
        assert await store.ports("suez") == []
        await store.close()
    asyncio.run(scenario())
