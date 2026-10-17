import asyncio
import json
import socket
import time
from contextlib import suppress

import httpx
import uvicorn
from fastapi.testclient import TestClient
from websockets.asyncio.server import serve

from aperium import seed
from aperium.app import create_app, collect
from aperium.tracking import bounding_boxes, normalize
from test_tracking import message

# Store.ports() returns geofences ordered by id.
BOUNDING_BOXES = bounding_boxes(sorted(seed.PORTS, key=lambda p: p['id']))


def test_api_without_key_and_filtering(database_url):
    app = create_app(database_url=database_url, api_key="")
    with TestClient(app) as client:
        assert client.get('/api/status').json()['status'] == 'missing_api_key'
        async def seed_positions():
            await app.state.store.save(normalize(message(), time.time()))
            await app.state.store.save(normalize(message(UserID=223456789), time.time() - 3600))
            await app.state.store.save(normalize(message(UserID=323456789, Latitude=26), time.time()))
        client.portal.call(seed_positions)
        assert len(client.get('/api/vessels').json()) == 1
        assert len(client.get('/api/vessels?include_stale=true').json()) == 2
        metrics = client.get('/api/metrics').json()
        assert metrics['active_vessels'] == 1
        assert metrics['slow_vessels_under_1_knot'] == 1
        assert metrics['stale_vessels_in_area'] == 1
        assert client.get('/api/vessels/123456789/history?limit=0').status_code == 422
        assert len(client.get('/api/vessels/123456789/history').json()) == 1


def test_binary_stream_and_reconnect(database_url):
    async def scenario():
        calls = []
        async def provider(ws):
            subscription = json.loads(await ws.recv())
            assert subscription['APIKey'] == 'test-key'
            assert subscription['BoundingBoxes'] == BOUNDING_BOXES
            calls.append(subscription)
            await ws.send(json.dumps({'MessageType': 'SubscriptionConfirmation', 'Message': {}}))
            await ws.send(b'not-json')
            await ws.send(json.dumps(message()).encode())
            if len(calls) > 1:
                await ws.wait_closed()
        app = create_app(database_url=database_url, api_key='')
        async with app.router.lifespan_context(app):
            async with serve(provider, '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                task = asyncio.create_task(collect(app, 'test-key', f'ws://127.0.0.1:{port}'))
                try:
                    async def wait_for_reconnect():
                        while app.state.stream['positions_received'] < 2:
                            await asyncio.sleep(0.01)
                    await asyncio.wait_for(wait_for_reconnect(), 8)
                    assert app.state.stream['reconnects'] >= 1
                    assert app.state.stream['invalid_messages'] >= 2
                    assert len(await app.state.store.vessels(time.time(), 900, app.state.ports)) == 1
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
    asyncio.run(scenario())


def test_four_ports_filtering_and_data_status(database_url):
    app = create_app(database_url=database_url, api_key='')
    with TestClient(app) as client:
        assert client.get('/api/status').json()['data_status'] == 'no_positions_received'
        assert len(client.get('/api/ports').json()) == 4
        async def seed_positions():
            for index, port in enumerate(seed.PORTS):
                (south, west), (north, east) = port['bounds_lat_lon']
                stamp = time.time() - (3600 if port['id'] == 'jebel_ali' else 0)
                await app.state.store.save(normalize(message(UserID=123456789 + index,
                    Latitude=(south+north)/2, Longitude=(west+east)/2), stamp))
        client.portal.call(seed_positions)
        assert len(client.get('/api/vessels').json()) == 3
        for port in seed.PORTS:
            rows = client.get(f"/api/vessels?port={port['id']}&include_stale=true").json()
            assert len(rows) == 1
            assert rows[0]['ports'] == [port['id']]
        assert client.get('/api/vessels?port=typo').status_code == 422
        result = client.get('/api/metrics').json()
        assert result['active_vessels'] == 3
        assert result['by_port']['jebel_ali']['data_status'] == 'stale_observations_only'
        assert client.get('/api/metrics?port=khor_fakkan').json()['active_vessels'] == 1


def test_geographies_endpoint(database_url):
    app = create_app(database_url=database_url, api_key='')
    with TestClient(app) as client:
        geos = client.get('/api/geographies').json()
        assert [g['id'] for g in geos] == ['hormuz', 'malacca', 'bab-el-mandeb', 'suez']
        hormuz = geos[0]
        assert {'bbox', 'lanes', 'gates', 'base_mbd', 'bypass_cap_mbd', 'ports'} <= set(hormuz)
        assert sorted(p['id'] for p in hormuz['ports']) == ['fujairah', 'jebel_ali', 'khor_fakkan', 'shahid_rajaee']
        assert all(p['geography_id'] == 'hormuz' for p in client.get('/api/ports?geography=hormuz').json())
        assert client.get('/api/ports?geography=suez').json() == []


def test_collector_subscription_and_binary_messages_without_network(monkeypatch, database_url):
    from importlib import import_module
    module = import_module('aperium.app')
    subscriptions = []

    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, raw):
            subscriptions.append(json.loads(raw))

        async def frames(self):
            yield json.dumps({'MessageType': 'SubscriptionConfirmation', 'Message': {}})
            yield b'invalid json'
            yield json.dumps(message()).encode()
            yield json.dumps(message(Latitude=91)).encode()

        def __aiter__(self):
            return self.frames()

    monkeypatch.setattr(module, 'connect', lambda *args, **kwargs: FakeSocket())

    async def scenario():
        app = create_app(database_url=database_url, api_key='')
        async with app.router.lifespan_context(app):
            task = asyncio.create_task(collect(app, 'test-only-key'))
            try:
                async def ready():
                    # Two subscriptions (initial + reconnect), each round fully processed; saves await Postgres.
                    while len(subscriptions) < 2 or app.state.stream['discarded_messages'] < 2:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 5)
                assert subscriptions[0]['BoundingBoxes'] == BOUNDING_BOXES
                assert len(subscriptions[0]['BoundingBoxes']) == 4
                assert app.state.stream['positions_received'] == 2
                assert app.state.stream['invalid_messages'] == 2
                assert app.state.stream['discarded_messages'] == 2
                assert len(await app.state.store.vessels(time.time(), 900, app.state.ports)) == 1
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
    asyncio.run(scenario())


def test_notify_fans_out_geofence_positions(database_url):
    """Trigger on `latest` → LISTEN → subscriber queues; positions outside every geofence are dropped."""
    async def scenario():
        app = create_app(database_url=database_url, api_key='')
        async with app.router.lifespan_context(app):
            while not app.state.listening:
                await asyncio.sleep(0.01)
            queue = asyncio.Queue()
            app.state.subscribers.add(queue)
            await app.state.store.save(normalize(message(UserID=423456789, Latitude=30), time.time()))  # outside
            await app.state.store.save(normalize(message(), time.time()))  # inside Fujairah
            item = await asyncio.wait_for(queue.get(), 5)
            assert item['mmsi'] == '123456789'
            assert item['ports'] == ['fujairah']
            assert item['stale'] is False
            assert queue.empty()
    asyncio.run(scenario())


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_sse_stream_snapshot_then_live_events(database_url):
    """End to end over real HTTP: snapshot on connect, then each new position as an SSE `vessel` event."""
    async def scenario():
        app = create_app(database_url=database_url, api_key='')
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
        serving = asyncio.create_task(server.serve())
        try:
            while not server.started:
                await asyncio.sleep(0.02)
            await app.state.store.save(normalize(message(UserID=523456789), time.time()))
            async with httpx.AsyncClient(timeout=10) as client:
                async with client.stream('GET', f'http://127.0.0.1:{port}/api/stream') as response:
                    assert response.headers['content-type'].startswith('text/event-stream')
                    events = []
                    async def read():
                        event = None
                        async for line in response.aiter_lines():
                            if line.startswith('event: '):
                                event = line[7:]
                            elif line.startswith('data: '):
                                events.append((event, json.loads(line[6:])))
                                if event == 'snapshot':
                                    await app.state.store.save(normalize(message(UserID=623456789), time.time()))
                                if event == 'vessel':
                                    return
                    await asyncio.wait_for(read(), 10)
            (kind, snapshot), (kind2, vessel) = events
            assert kind == 'snapshot' and [v['mmsi'] for v in snapshot] == ['523456789']
            assert kind2 == 'vessel' and vessel['mmsi'] == '623456789' and vessel['ports'] == ['fujairah']
        finally:
            server.should_exit = True
            await serving
    asyncio.run(scenario())
