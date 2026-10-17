import asyncio
import json
import time
from contextlib import suppress

from fastapi.testclient import TestClient
from websockets.asyncio.server import serve

from aperium.app import create_app, collect
from aperium.tracking import BOUNDING_BOXES, PORTS, normalize
from test_tracking import message


def test_api_without_key_and_filtering():
    app = create_app(database=":memory:", api_key="")
    with TestClient(app) as client:
        assert client.get('/api/status').json()['status'] == 'missing_api_key'
        async def seed():
            app.state.store.save(normalize(message(), time.time()))
            app.state.store.save(normalize(message(UserID=223456789), time.time() - 3600))
            app.state.store.save(normalize(message(UserID=323456789, Latitude=26), time.time()))
        client.portal.call(seed)
        assert len(client.get('/api/vessels').json()) == 1
        assert len(client.get('/api/vessels?include_stale=true').json()) == 2
        metrics = client.get('/api/metrics').json()
        assert metrics['active_vessels'] == 1
        assert metrics['slow_vessels_under_1_knot'] == 1
        assert metrics['stale_vessels_in_area'] == 1
        assert client.get('/api/vessels/123456789/history?limit=0').status_code == 422
        assert len(client.get('/api/vessels/123456789/history').json()) == 1


def test_binary_stream_and_reconnect():
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
        app = create_app(database=':memory:', api_key='')
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
                    assert len(app.state.store.vessels(time.time(), 900)) == 1
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
    asyncio.run(scenario())


def test_four_ports_filtering_and_data_status():
    app = create_app(database=':memory:', api_key='')
    with TestClient(app) as client:
        assert client.get('/api/status').json()['data_status'] == 'no_positions_received'
        assert len(client.get('/api/ports').json()) == 4
        async def seed():
            for index, (port, config) in enumerate(PORTS.items()):
                (south, west), (north, east) = config['bounds_lat_lon']
                stamp = time.time() - (3600 if port == 'jebel_ali' else 0)
                app.state.store.save(normalize(message(UserID=123456789 + index,
                    Latitude=(south+north)/2, Longitude=(west+east)/2), stamp))
        client.portal.call(seed)
        assert len(client.get('/api/vessels').json()) == 3
        for port in PORTS:
            rows = client.get(f'/api/vessels?port={port}&include_stale=true').json()
            assert len(rows) == 1
            assert rows[0]['ports'] == [port]
        assert client.get('/api/vessels?port=typo').status_code == 422
        result = client.get('/api/metrics').json()
        assert result['active_vessels'] == 3
        assert result['by_port']['jebel_ali']['data_status'] == 'stale_observations_only'
        assert client.get('/api/metrics?port=khor_fakkan').json()['active_vessels'] == 1


def test_collector_subscription_and_binary_messages_without_network(monkeypatch):
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
        app = create_app(database=':memory:', api_key='')
        async with app.router.lifespan_context(app):
            task = asyncio.create_task(collect(app, 'test-only-key'))
            try:
                async def ready():
                    while len(subscriptions) < 2:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 5)
                assert subscriptions[0]['BoundingBoxes'] == BOUNDING_BOXES
                assert len(subscriptions[0]['BoundingBoxes']) == 4
                assert app.state.stream['positions_received'] == 2
                assert app.state.stream['invalid_messages'] == 2
                assert app.state.stream['discarded_messages'] == 2
                assert len(app.state.store.vessels(time.time(), 900)) == 1
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
    asyncio.run(scenario())
