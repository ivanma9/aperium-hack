import asyncio
import time

from fastapi.testclient import TestClient

from aperium import seed
from aperium.analytics import Boundary
from aperium.app import create_app
from aperium.db import Store
from test_analytics import point


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
