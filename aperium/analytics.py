"""Replayable, conservative analytics on observed tracks (never silence-as-exit)."""
import hashlib
import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator
from typing import Literal


class Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["terminal", "anchorage", "checkpoint"]
    port: str
    geography_id: str = "hormuz"
    coordinates: list[list[float]]  # GeoJSON order: longitude, latitude
    source: str
    reviewed: bool = False
    purpose: Literal["waiting", "service", "unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_geometry(self):
        if not self.id or not self.source:
            raise ValueError("Boundary ID and source required")
        for point in self.coordinates:
            if len(point) != 2 or not all(math.isfinite(v) for v in point) or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                raise ValueError("Coordinates must be [longitude, latitude]")
        if self.kind == "checkpoint":
            if len(self.coordinates) != 2 or self.coordinates[0] == self.coordinates[1]:
                raise ValueError("Checkpoint needs two distinct endpoints")
        elif len(self.coordinates) < 4 or self.coordinates[0] != self.coordinates[-1] or len(set(map(tuple, self.coordinates))) < 3:
            raise ValueError("Polygon needs a closed ring with at least three distinct vertices")
        if self.kind != "checkpoint":
            ring = self.coordinates
            area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:]))
            if abs(area) < 1e-12:
                raise ValueError("Polygon must have nonzero area")
            for i in range(len(ring)-1):
                for j in range(i+2,len(ring)-1):
                    if i == 0 and j == len(ring)-2:
                        continue
                    if crosses(ring[i],ring[i+1],ring[j],ring[j+1]):
                        raise ValueError("Polygon must not self-intersect")
        return self


def load_boundaries(path):
    items = [Boundary.model_validate(v) for v in json.loads(Path(path).read_text())]
    if len({v.id for v in items}) != len(items):
        raise ValueError("Boundary IDs must be unique")
    return items


def contains(point, ring):
    x, y = point
    result = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        if abs(cross) < 1e-10 and min(ax,bx) <= x <= max(ax,bx) and min(ay,by) <= y <= max(ay,by):
            return True
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            result = not result
    return result


def side(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])


def crosses(a, b, p, q):
    # Strict finite-segment crossing: touching a gate is not a transit.
    return side(a,b,p)*side(a,b,q) < 0 and side(p,q,a)*side(p,q,b) < 0


def plausible(previous, current, max_gap):
    dt = current['observed_at'] - previous['observed_at']
    if not 0 < dt <= max_gap:
        return False
    lat1, lat2 = map(math.radians, (previous['latitude'], current['latitude']))
    dlat = lat2-lat1
    dlon = math.radians(current['longitude']-previous['longitude'])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    nautical_miles = 3440.065 * 2 * math.asin(min(1, math.sqrt(h)))
    return nautical_miles / (dt/3600) <= 60


def events_for_track(track, boundary, now, max_gap=900, dwell=300):
    events, visit, previous, last_crossing = [], None, None, -float('inf')
    def finish(reason, departure=None):
        nonlocal visit
        if visit and visit['observed_seconds'] >= dwell and visit['samples'] >= 2:
            visit['end_reason'] = reason
            visit['departure_observed_at'] = departure
            visit['id'] = hashlib.sha256(f"{visit['mmsi']}:{boundary.id}:{visit['first_seen_at']}".encode()).hexdigest()[:24]
            events.append(visit)
        visit = None

    for point in track:
        continuous = previous is not None and plausible(previous, point, max_gap)
        xy = [point['longitude'], point['latitude']]
        if boundary.kind == 'checkpoint':
            if continuous and point['observed_at'] - last_crossing >= 600:
                pxy = [previous['longitude'], previous['latitude']]
                a, b = boundary.coordinates
                if crosses(a,b,pxy,xy):
                    direction = 'negative_to_positive' if side(a,b,xy) > 0 else 'positive_to_negative'
                    events.append(dict(mmsi=point['mmsi'], boundary_id=boundary.id, kind='checkpoint_crossing',
                        port=boundary.port, geography_id=boundary.geography_id,
                        direction=direction, interval_start=previous['observed_at'], interval_end=point['observed_at'],
                        reviewed_boundary=boundary.reviewed))
                    last_crossing = point['observed_at']
        else:
            if visit and not continuous:
                finish('coverage_gap')
            # A dwell requires a low reported speed, not just a point inside a box.
            eligible = contains(xy, boundary.coordinates) and point['speed_knots'] is not None and point['speed_knots'] < 1
            if eligible:
                if visit is None:
                    visit = dict(mmsi=point['mmsi'], boundary_id=boundary.id, port=boundary.port,
                        geography_id=boundary.geography_id,
                        kind='terminal_call_candidate' if boundary.kind == 'terminal' else 'anchorage_stay',
                        purpose=boundary.purpose, reviewed_boundary=boundary.reviewed,
                        first_seen_at=point['observed_at'], last_seen_at=point['observed_at'], samples=1,
                        observed_seconds=0, entry_observed=bool(continuous and not contains(
                            [previous['longitude'], previous['latitude']], boundary.coordinates)))
                else:
                    visit['observed_seconds'] += point['observed_at']-visit['last_seen_at']
                    visit['last_seen_at'] = point['observed_at']
                    visit['samples'] += 1
            elif visit:
                outside = not contains(xy, boundary.coordinates)
                finish('observed_exit' if outside else 'movement_or_unknown_speed', point['observed_at'] if outside else None)
        previous = point
    if visit:
        finish('stale' if now-visit['last_seen_at'] > max_gap else 'ongoing')
    return events


def analyze(rows, profiles, boundaries, now, hours=24, max_gap=900):
    """Pure replay engine. The store supplies a bounded, consistent Postgres snapshot."""
    if len(rows) > 100000:
        raise ValueError("Too many observations; request a smaller hours window")
    tracks = {}
    for row in rows:
        tracks.setdefault(row['mmsi'], []).append(dict(row))
    events = []
    gaps = 0
    for mmsi, track in tracks.items():
        gaps += sum(not plausible(a,b,max_gap) for a,b in zip(track, track[1:]))
        if profiles.get(mmsi, {}).get('vessel_class') != 'tanker':
            continue
        for boundary in boundaries:
            events.extend(events_for_track(track, boundary, now, max_gap))
    waiting_boundaries = [b for b in boundaries if b.reviewed and b.kind == 'anchorage' and b.purpose == 'waiting']
    waiting_ids = {b.id for b in waiting_boundaries}
    waiting = [e for e in events if e['boundary_id'] in waiting_ids and e.get('end_reason') == 'ongoing']
    calls = [e for e in events if e['kind'] == 'terminal_call_candidate']
    for call in calls:
        prior = [e for e in events if e['boundary_id'] in waiting_ids and e['mmsi']==call['mmsi']
                 and e.get('port')==call['port'] and e.get('end_reason')=='observed_exit'
                 and 0 <= call['first_seen_at']-e['last_seen_at'] <= max_gap]
        call['observed_prior_wait_seconds'] = max((e['observed_seconds'] for e in prior), default=None)
    crossings = [e for e in events if e['kind']=='checkpoint_crossing']
    classifications = []
    for mmsi, track in tracks.items():
        latest = track[-1]
        profile = profiles.get(mmsi, {})
        classifications.append(dict(mmsi=mmsi, name=profile.get('name') or latest.get('name') or '',
            vessel_class=profile.get('vessel_class','unknown'), ship_type=profile.get('ship_type'),
            classification_updated_at=profile.get('classification_updated_at'), source=profile.get('source'),
            last_seen_at=latest['observed_at'], stale=now-latest['observed_at']>max_gap))
    latest_time = max((r['observed_at'] for r in rows), default=None)
    observation_status = 'no_observations' if latest_time is None else ('stale' if now-latest_time>max_gap else 'recent_observations')
    waiting_count = len({e['mmsi'] for e in waiting}) if waiting_ids and observation_status=='recent_observations' else None
    return dict(window_hours=hours, boundary_version=hashlib.sha256(json.dumps([b.model_dump() for b in boundaries], sort_keys=True).encode()).hexdigest()[:16],
        generated_at=now, classification=classifications,
        waiting_times=[e for e in events if e['boundary_id'] in waiting_ids],
        port_calls=calls,
        transit_counts={b.id: {'reviewed_boundary': b.reviewed,
            'source': b.source,
            'negative_to_positive': sum(e['boundary_id']==b.id and e['direction']=='negative_to_positive' for e in crossings),
            'positive_to_negative': sum(e['boundary_id']==b.id and e['direction']=='positive_to_negative' for e in crossings)}
            for b in boundaries if b.kind=='checkpoint'},
        configuration={'terminal_boundaries':sum(b.kind=='terminal' for b in boundaries),
                       'reviewed_waiting_boundaries':len(waiting_boundaries)},
        events=events, congestion=dict(status=(observation_status if observation_status!='recent_observations' else 'observed_waiting_only') if waiting_ids else 'boundaries_not_configured',
            waiting_tankers=waiting_count, observed_waits=waiting,
            by_boundary={b.id: {'port':b.port, 'waiting_tankers':len({e['mmsi'] for e in waiting if e['boundary_id']==b.id}),
                'source': b.source} for b in waiting_boundaries}),
        quality=dict(observed_vessels=len(tracks), tanker_vessels=sum(profiles.get(m,{}).get('vessel_class')=='tanker' for m in tracks),
            observation_status=observation_status, latest_observed_at=latest_time,
            unclassified_vessels=sum(profiles.get(m,{}).get('vessel_class','unknown')=='unknown' for m in tracks),
            discontinuities=gaps, coverage_completeness='unverified',
            note='AIS self-reported classification. Observed stays are lower bounds, not verified berth waits. No departures or crossings inferred across gaps.'))
