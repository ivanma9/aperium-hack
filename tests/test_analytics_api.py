import asyncio
import json
import time

from fastapi.testclient import TestClient

from aperium import seed
from aperium.analytics import Boundary
from aperium.app import create_app
from aperium.db import Store
from test_analytics import point


def test_shared_collector_records_monitor_messages_and_saves_analytics_profiles(monkeypatch, tmp_path):
    """The shared stream must feed both raw-file monitoring and Postgres analytics."""
    from importlib import import_module
    from aperium.regions import REGIONS
    from aperium.tracking import bounding_boxes
    from test_tracking import message

    module = import_module('aperium.app')
    frames = [
        {'MessageType': 'ShipStaticData', 'Message': {'ShipStaticData': {
            'UserID': 123456789, 'Type': 80, 'Name': 'TEST TANKER'}}},
        {'MessageType': 'StaticDataReport', 'Message': {'StaticDataReport': {
            'UserID': 223456789, 'PartNumber': True, 'ReportB': {'ShipType': 80}}}},
        message(),
    ]
    subscriptions, profiles, positions = [], [], []
    raw_file = tmp_path / 'raw.jsonl'
    monkeypatch.setattr(module, 'raw_path', lambda: raw_file)

    async def scenario():
        finished = asyncio.Event()

        class FakeStore:
            async def ports(self): return seed.PORTS
            async def geographies(self): return seed.GEOGRAPHIES
            async def boundaries(self):
                return [Boundary.model_validate(b) for b in seed.ANALYTICS_BOUNDARIES]
            async def save_profile(self, profile): profiles.append(profile)
            async def save(self, position):
                positions.append(position)
                finished.set()
            async def close(self): pass

        class FakeSocket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send(self, raw): subscriptions.append(json.loads(raw))
            async def messages(self):
                for item in frames:
                    yield json.dumps(item)
                await asyncio.Event().wait()
            def __aiter__(self): return self.messages()

        async def opened(cls, dsn): return FakeStore()
        async def idle(*args): await asyncio.Event().wait()
        monkeypatch.setattr(Store, 'open', classmethod(opened))
        monkeypatch.setattr(module, 'listen', idle)
        monkeypatch.setattr(module, 'connect', lambda *args, **kwargs: FakeSocket())
        app = create_app(database_url='test-placeholder', api_key='test-key', record=True)
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(finished.wait(), 2)
            boxes = bounding_boxes(seed.PORTS) + [r['bbox'] for r in REGIONS.values()]
            assert subscriptions[0]['BoundingBoxes'][:len(boxes)] == boxes
            assert len(subscriptions[0]['BoundingBoxes']) == len(boxes) + len(seed.ANALYTICS_BOUNDARIES)
            assert {'ShipStaticData', 'StaticDataReport'} <= set(subscriptions[0]['FilterMessageTypes'])
            assert app.state.stream['profiles_received'] == 2
            assert app.state.stream['positions_received'] == 1
            assert app.state.stream['discarded_messages'] == 0
            assert all(p['vessel_class'] == 'tanker' for p in profiles)
            assert len(positions) == 1

    asyncio.run(scenario())
    recorded = [json.loads(line) for line in raw_file.read_text().splitlines()]
    assert [r['MessageType'] for r in recorded] == [r['MessageType'] for r in frames]
    assert all('received_at' in r for r in recorded)


def test_postgres_profiles_boundaries_and_window(database_url):
    async def scenario():
        store=await Store.open(database_url)
        try:
            await store.save_profile({'mmsi':'123456789','updated_at':10,'vessel_class':'tanker'})
            await store.save_profile({'mmsi':'123456789','updated_at':20,'name':'RENAMED'})
            await store.save_profile({'mmsi':'123456789','updated_at':5,'vessel_class':'cargo'})
            await store.save(point(100))
            await store.save(point(200,x=20))
            rows,profiles=await store.analytics_snapshot(50,150,[-1,-1,1,1])
            assert len(rows)==1
            assert profiles['123456789']['vessel_class']=='tanker'
            assert profiles['123456789']['name']=='RENAMED'
            assert len(await store.boundaries('hormuz'))==3
            await store.migrate()
            assert len(await store.boundaries('hormuz'))==3
        finally:
            await store.close()
    asyncio.run(scenario())


def test_analytics_routes_and_scope_without_database(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.requested_bbox=None
        async def ports(self): return seed.PORTS
        async def geographies(self): return [{**g,'ports':[p for p in seed.PORTS if p['geography_id']==g['id']]} for g in seed.GEOGRAPHIES]
        async def boundaries(self):
            return [Boundary(id='test_wait',port='fujairah',geography_id='hormuz',kind='anchorage',
                purpose='waiting',reviewed=True,source='synthetic fixture',
                coordinates=[[56.35,25.10],[56.4,25.10],[56.4,25.2],[56.35,25.2],[56.35,25.10]])]
        async def analytics_snapshot(self,since,now,bbox):
            self.requested_bbox=bbox
            return [point(now-400,x=56.37,y=25.16),point(now-100,x=56.37,y=25.16)], {'123456789':{'vessel_class':'tanker'}}
        async def close(self): pass
    store=FakeStore()
    async def opened(cls,dsn): return store
    monkeypatch.setattr(Store,'open',classmethod(opened))
    async def idle(*args): await asyncio.Event().wait()
    monkeypatch.setattr('aperium.app.listen',idle)
    app=create_app(database_url='test-placeholder',api_key='')
    with TestClient(app) as client:
        data=client.get('/api/analytics?geography=hormuz&port=fujairah&hours=1').json()
        assert data['congestion']['waiting_tankers']==1
        assert data['waiting_times'][0]['observed_seconds']==300
        assert data['classification'][0]['vessel_class']=='tanker'
        assert data['geography_id']=='hormuz'
        assert store.requested_bbox[0] < 56.35
        assert client.get('/api/analytics?geography=invalid').status_code==422
        assert client.get('/api/analytics?geography=suez&port=fujairah').status_code==422
        assert client.get('/api/analytics?hours=169').status_code==422
        assert client.get('/api/boundaries?geography=suez').json()==[]
        assert client.get('/api/coverage').json()['unclassified_fresh_vessels']==0
        async def too_many(*args): raise ValueError('Too many observations')
        store.analytics_snapshot=too_many
        assert client.get('/api/analytics').status_code==422
