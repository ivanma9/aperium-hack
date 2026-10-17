import pytest
from aperium.analytics import Boundary, events_for_track, analyze, contains
from aperium import seed
from aperium.tracking import static_profile


def point(t, x=.005, y=.005, speed=0):
    return dict(mmsi='123456789', name='TEST', latitude=y, longitude=x, speed_knots=speed,
                course=0, nav_status=1, observed_at=t, received_at=t, time_source='provider')


def boundary(kind='terminal', **kwargs):
    return Boundary(id='test', kind=kind, port='test', source='synthetic test', reviewed=True,
        coordinates=[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]], **kwargs)


def test_calls_require_dwell_and_observed_exit():
    track = [point(0,x=-.001), point(60), point(360), point(420,x=.011)]
    result = events_for_track(track, boundary(), 420)
    assert len(result)==1
    assert result[0]['entry_observed']
    assert result[0]['observed_seconds']==300
    assert result[0]['departure_observed_at']==420
    assert result[0]['end_reason']=='observed_exit'
    assert events_for_track([point(0),point(50)], boundary(),50)==[]


def test_gaps_and_stale_reports_are_not_departures():
    result = events_for_track([point(0),point(300),point(2000,x=.011)], boundary(),2000)
    assert result[0]['end_reason']=='coverage_gap'
    assert result[0]['departure_observed_at'] is None
    assert not result[0]['entry_observed']
    result = events_for_track([point(0),point(300)],boundary(),2000)
    assert result[0]['end_reason']=='stale'


def test_direction_finite_gate_and_gap():
    gate = Boundary(id='gate',kind='checkpoint',port='test',source='test',coordinates=[[0,-.01],[0,.01]])
    events=events_for_track([point(0,-.001,0),point(100,.001,0),point(200,-.001,0)],gate,200)
    assert len(events)==1  # jitter is suppressed for ten minutes
    assert events[0]['direction']=='positive_to_negative'
    assert not events_for_track([point(0,-.001,.02),point(100,.001,.02)],gate,100)
    assert not events_for_track([point(0,-.001,0),point(2000,.001,0)],gate,2000)


def test_classification_merge_and_unknowns():
    for code, expected in [(80,'tanker'),(89,'tanker'),(70,'cargo'),(60,'other')]:
        result=static_profile({'MessageType':'ShipStaticData','Message':{'ShipStaticData':{'UserID':123456789,'Type':code,'Name':'TEST'}}},10)
        assert result['vessel_class']==expected
    typed = static_profile({'MessageType':'StaticDataReport','Message':{'StaticDataReport':{'UserID':123456789,'PartNumber':True,'ReportB':{'ShipType':80}}}},10)
    named = static_profile({'MessageType':'StaticDataReport','Message':{'StaticDataReport':{'UserID':123456789,'PartNumber':False,'ReportA':{'Name':'RENAMED'}}}},20)
    assert typed['vessel_class']=='tanker'
    assert named['name']=='RENAMED'
    assert 'vessel_class' not in named


def test_congestion_requires_reviewed_waiting_polygon_and_tanker():
    rows=[point(0),point(300)]
    assert analyze(rows,{},[],400)['congestion']['waiting_tankers'] is None
    b=boundary('anchorage',purpose='waiting')
    assert analyze(rows,{},[b],400)['quality']['unclassified_vessels']==1
    profiles={'123456789':{'vessel_class':'tanker'}}
    result=analyze(rows,profiles,[b],400)
    assert result['congestion']['waiting_tankers']==1
    assert result['congestion']['observed_waits'][0]['observed_seconds']==300
    assert analyze(rows,profiles,[b],2000)['congestion']['waiting_tankers'] is None
    b.reviewed=False
    assert analyze(rows,profiles,[b],400)['congestion']['waiting_tankers'] is None


def test_bad_geometry_rejected():
    with pytest.raises(ValueError):
        Boundary(id='bad', kind='terminal', port='test', source='test', coordinates=[[0,91]]*4)


def test_fujairah_waiting_seed_excludes_service_and_sts_areas():
    b = Boundary.model_validate(seed.ANALYTICS_BOUNDARIES[0])
    assert b.reviewed and b.purpose == 'waiting' and b.port == 'fujairah'
    assert contains([56.46, 25.19], b.coordinates)
    assert contains([56.495, 25.15], b.coordinates)  # southern eastward extension
    assert not contains([56.495, 25.19], b.coordinates)  # BS service area
    assert not contains([56.52, 25.15], b.coordinates)  # S ship-to-ship area
    profiles = {'123456789': {'vessel_class': 'tanker'}}
    waiting = [point(0, x=56.46, y=25.19), point(300, x=56.46, y=25.19)]
    result = analyze(waiting, profiles, [b], 400)
    assert result['configuration']['reviewed_waiting_boundaries'] == 1
    assert result['congestion']['waiting_tankers'] == 1
    assert result['waiting_times'][0]['observed_seconds'] == 300
    services = [point(0, x=56.495, y=25.19), point(300, x=56.495, y=25.19)]
    assert analyze(services, profiles, [b], 400)['waiting_times'] == []
