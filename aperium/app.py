import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
from typing import Optional

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect

from aperium import api as monitor_api
from aperium.db import CHANNEL, Store, describe
from aperium.db import database_url as env_database_url
from aperium.recorder import raw_path
from aperium.regions import REGIONS
from aperium.tracking import POSITION_TYPES, STATIC_TYPES, bounding_boxes, normalize, static_profile
from aperium.analytics import analyze

try:  # MCP SDK needs Python 3.10+; without it the collector runs without /mcp.
    from aperium.mcp_server import mcp as mcp_server
except ImportError:  # pragma: no cover
    mcp_server = None

log = logging.getLogger("aperium")
STREAM_URL = "wss://stream.aisstream.io/v0/stream"
# SSE comment sent when idle so proxies keep the connection open.
HEARTBEAT_SECONDS = 15
SUBSCRIBER_QUEUE = 1000


def record_raw(message):
    """Append the raw message for aperium.run (tanker monitor), as aperium.recorder would."""
    path = raw_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({**message, "received_at": datetime.now(timezone.utc).isoformat()},
                           separators=(",", ":")) + "\n")


async def collect(app, key, url=STREAM_URL):
    state = app.state.stream
    delay = 1
    while True:
        state["status"] = "connecting"
        try:
            async with connect(url, compression="deflate", ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": app.state.subscription_boxes,
                                          "FilterMessageTypes": POSITION_TYPES + STATIC_TYPES}))
                state["status"] = "awaiting_subscription"
                async for raw in ws:
                    try:
                        message = json.loads(raw)
                        if not isinstance(message, dict):
                            raise ValueError("Expected object")
                        if "error" in message or "Error" in message:
                            state["last_error"] = "Provider rejected request; check key and account connection limits."
                            raise ConnectionError("Provider rejection")
                        if message.get("MessageType") == "SubscriptionConfirmation":
                            state["status"] = "subscribed"
                            state["last_error"] = None
                            continue
                        now = time.time()
                        state["last_message_at"] = now
                        state["messages_received"] += 1
                        if getattr(app.state, "record_raw", False):
                            record_raw(message)
                        profile = static_profile(message, now)
                        position = normalize(message, now)
                    except (ValueError, TypeError, AttributeError):
                        state["invalid_messages"] += 1
                        continue
                    if profile:
                        await app.state.store.save_profile(profile)
                        state['profiles_received'] += 1
                    if position:
                        await app.state.store.save(position)
                        state["status"] = "receiving"
                        state["last_error"] = None
                        state["positions_received"] += 1
                        state["last_position_at"] = now
                        delay = 1
                    elif not profile:
                        state["discarded_messages"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log provider payloads or exception text containing credentials.
            log.warning("AIS connection interrupted (%s)", type(exc).__name__)
            if not state["last_error"]:
                state["last_error"] = f"Connection interrupted ({type(exc).__name__}); retrying."
        state["status"] = "reconnecting"
        state["reconnects"] += 1
        await asyncio.sleep(delay + random.uniform(0, 1))
        delay = min(delay * 2, 60)


async def listen(app, dsn):
    """LISTEN for position changes (trigger on `latest`) and fan them out to SSE subscribers."""
    delay = 1
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                await conn.execute(f"LISTEN {CHANNEL}")
                app.state.listening = True
                delay = 1
                async for notification in conn.notifies():
                    item = describe(json.loads(notification.payload), time.time(),
                                    app.state.stale_seconds, app.state.ports)
                    if not item["inside_geofence"]:
                        continue
                    for queue in list(app.state.subscribers):
                        with suppress(asyncio.QueueFull):  # a stalled client misses events, not the others
                            queue.put_nowait(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Postgres LISTEN interrupted (%s)", type(exc).__name__)
        app.state.listening = False
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def create_app(database_url=None, api_key=None, stream_url=STREAM_URL, record=None):
    # MCP over Streamable HTTP at /mcp (stateless, JSON responses). Built per app: each
    # streamable_http_app() call creates the session manager its lifespan must run.
    mcp_app = mcp_server.streamable_http_app(stateless_http=True, json_response=True) if mcp_server else None
    mcp_sessions = mcp_server.session_manager if mcp_server else None

    @asynccontextmanager
    async def lifespan(app):
        load_dotenv()
        key = api_key if api_key is not None else os.getenv("AISSTREAM_API_KEY", "")
        dsn = database_url or env_database_url()
        app.state.stale_seconds = max(1, int(os.getenv("STALE_SECONDS", "900")))
        app.state.store = await Store.open(dsn)
        # Geofences are read once at startup; restart after editing the `ports` table.
        app.state.ports = await app.state.store.ports()
        app.state.geographies = await app.state.store.geographies()
        app.state.boundaries = await app.state.store.boundaries()
        # Keep the monitor's regions and analytics geometry on the same AIS connection.
        app.state.subscription_boxes = bounding_boxes(app.state.ports) + [r["bbox"] for r in REGIONS.values()]
        for boundary in app.state.boundaries:
            xs,ys = zip(*boundary.coordinates)
            app.state.subscription_boxes.append([[max(-90,min(ys)-.05), max(-180,min(xs)-.05)],
                [min(90,max(ys)+.05),min(180,max(xs)+.05)]])
        app.state.subscribers = set()
        app.state.record_raw = record if record is not None else os.getenv("RECORD_RAW", "1") != "0"
        app.state.listening = False
        app.state.stream = dict(status="missing_api_key", last_error=None, last_message_at=None,
                                last_position_at=None, messages_received=0, positions_received=0,
                                invalid_messages=0, discarded_messages=0, profiles_received=0, reconnects=0, started_at=time.time())
        tasks = [asyncio.create_task(listen(app, dsn))]
        if key.strip():
            tasks.append(asyncio.create_task(collect(app, key, stream_url)))
        try:
            if mcp_sessions:
                async with mcp_sessions.run():
                    yield
            else:
                yield
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await app.state.store.close()

    app = FastAPI(title="Aperium · Hormuz region AIS", lifespan=lifespan,
                  description="Observed vessel activity in the port geofences stored in Postgres (`ports` table), "
                              "and the monitored geographies (`geographies` table). Approximate discovery boxes, "
                              "not official anchorage boundaries or congestion scores. Times are Unix seconds in UTC.")

    # Tanker monitor read-only routes (/api/regions/..., /api/cpi_nowcast, /api/cpi/scenario, /api/files/...).
    app.include_router(monitor_api.router)
    app.mount("/api/files", monitor_api.files(), name="monitor-files")

    def port_ids():
        return {p["id"] for p in app.state.ports}

    def check_port(port):
        if port is not None and port not in port_ids():
            raise HTTPException(422, f"Unknown port {port!r}; expected one of {sorted(port_ids())}")

    def check_geography(geography):
        for geo in app.state.geographies:
            if geo['id']==geography:
                return geo
        raise HTTPException(422, 'Unknown geography')

    @app.get('/api/boundaries')
    async def boundaries(geography: str = 'hormuz'):
        check_geography(geography)
        return [b.model_dump() for b in app.state.boundaries if b.geography_id==geography]

    @app.get('/api/analytics')
    async def analytics(geography: str = 'hormuz', hours: int = Query(24, ge=1, le=168), port: Optional[str] = None):
        geo = check_geography(geography)
        check_port(port)
        selected_port = next((p for p in geo['ports'] if p['id']==port),None)
        if port and selected_port is None:
            raise HTTPException(422,'Port does not belong to this geography')
        bounds = [b for b in app.state.boundaries if b.geography_id==geography and (not port or b.port==port)]
        bbox = list(geo['bbox'])
        if selected_port:
            (south,west),(north,east)=selected_port['bounds_lat_lon']
            bbox=[west,south,east,north]
        # Retain observations on both sides of every analytics feature.
        for boundary in bounds:
            xs,ys=zip(*boundary.coordinates)
            bbox=[min(bbox[0],min(xs)-.05),min(bbox[1],min(ys)-.05),max(bbox[2],max(xs)+.05),max(bbox[3],max(ys)+.05)]
        now=time.time()
        try:
            rows,profiles=await app.state.store.analytics_snapshot(now-hours*3600,now,bbox)
            result=await run_in_threadpool(analyze, rows, profiles, bounds, now, hours, app.state.stale_seconds)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        return {**result,'geography_id':geography,'port':port,
                'boundaries':[b.model_dump() for b in bounds], 'stream_status':app.state.stream['status']}

    @app.get('/api/coverage')
    async def coverage(geography: str = 'hormuz'):
        geo=check_geography(geography)
        now=time.time()
        try:
            rows,profiles=await app.state.store.analytics_snapshot(now-3600,now,geo['bbox'])
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        latest={r['mmsi']:r for r in rows}
        fresh=[m for m,r in latest.items() if now-r['observed_at']<=app.state.stale_seconds]
        return {'geography_id':geography,'completeness':'unverified','fresh_observed_vessels':len(fresh),
                'unclassified_fresh_vessels':sum(profiles.get(m,{}).get('vessel_class','unknown')=='unknown' for m in fresh),
                'latest_observed_at':max((r['observed_at'] for r in rows),default=None)}

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/docs")

    @app.get("/api/status")
    async def status():
        now = time.time()
        last = app.state.stream["last_position_at"]
        age = None if last is None else round(now - last, 1)
        return {**app.state.stream,
                "geofences": {p["id"]: {"name": p["name"], "bounds_lat_lon": p["bounds_lat_lon"]} for p in app.state.ports},
                "seconds_since_last_position": age,
                "data_status": "no_positions_received" if last is None else
                    ("stale" if age > app.state.stale_seconds else "recent_positions_received"),
                "stale_seconds": app.state.stale_seconds, "now": now,
                "event_stream": "listening" if app.state.listening else "reconnecting",
                "stream_subscribers": len(app.state.subscribers)}

    @app.get("/api/geographies")
    async def geographies():
        """Monitored geographies (chokepoints), each with its port geofences."""
        return await app.state.store.geographies()

    @app.get("/api/ports")
    async def ports(geography: Optional[str] = None):
        return await app.state.store.ports(geography)

    @app.get("/api/vessels")
    async def vessels(include_stale: bool = False, port: Optional[str] = None):
        check_port(port)
        items = await app.state.store.vessels(time.time(), app.state.stale_seconds, app.state.ports)
        return [v for v in items if v["inside_geofence"] and (include_stale or not v["stale"])
                and (port is None or port in v["ports"])]

    @app.get("/api/metrics")
    async def metrics(port: Optional[str] = None):
        check_port(port)
        all_vessels = await app.state.store.vessels(time.time(), app.state.stale_seconds, app.state.ports)
        def summarize(items):
            active = [v for v in items if v["inside_geofence"] and not v["stale"]]
            last_received = max((v["received_at"] for v in items), default=None)
            return {"active_vessels": len(active),
                "slow_vessels_under_1_knot": sum(v["speed_knots"] is not None and v["speed_knots"] < 1 for v in active),
                "reported_anchored": sum(v["nav_status"] == 1 for v in active),
                "stale_vessels_in_area": sum(v["inside_geofence"] and v["stale"] for v in items),
                "latest_receipt_at": last_received,
                "data_status": "fresh_observations" if active else
                    ("stale_observations_only" if items else "no_observed_vessels")}
        selected = [v for v in all_vessels if v["inside_geofence"] and (port is None or port in v["ports"])]
        return {**summarize(selected), "port": port,
                "by_port": {p["id"]: summarize([v for v in all_vessels if p["id"] in v["ports"]])
                            for p in app.state.ports if port is None or p["id"] == port},
                "stream_status": app.state.stream["status"],
                "note": "Observed activity only. Zero may mean no coverage. Slow/anchored vessels are not necessarily waiting for a berth."}

    @app.get("/api/vessels/{mmsi}/history")
    async def history(mmsi: str, limit: int = Query(100, ge=1, le=10000)):
        return await app.state.store.history(mmsi, limit)

    @app.get("/api/stream")
    async def stream(request: Request):
        """Server-Sent Events. `snapshot`: fresh geofence vessels on connect.
        `vessel`: each new position (Postgres NOTIFY on `latest`), same shape as /api/vessels items."""
        queue = asyncio.Queue(SUBSCRIBER_QUEUE)
        app.state.subscribers.add(queue)  # subscribe before the snapshot so no update falls between them

        async def events():
            try:
                items = await app.state.store.vessels(time.time(), app.state.stale_seconds, app.state.ports)
                yield sse("snapshot", [v for v in items if v["inside_geofence"] and not v["stale"]])
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                        yield sse("vessel", item)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": keep-alive\n\n"
            finally:
                app.state.subscribers.discard(queue)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


    # Last: Mount("/") matches every path, so it must come after all API routes.
    # The MCP app serves /mcp itself and 404s anything else.
    if mcp_app:
        app.mount("/", mcp_app, name="mcp")

    return app


app = create_app()
