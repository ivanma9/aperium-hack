import asyncio
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager, suppress
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import RedirectResponse
from websockets.asyncio.client import connect

from aperium.tracking import BOUNDING_BOXES, PORTS, POSITION_TYPES, Store, normalize

PortId = Literal["fujairah", "shahid_rajaee", "khor_fakkan", "jebel_ali"]

log = logging.getLogger("aperium")
STREAM_URL = "wss://stream.aisstream.io/v0/stream"


async def collect(app, key, url=STREAM_URL):
    state = app.state.stream
    delay = 1
    while True:
        state["status"] = "connecting"
        try:
            async with connect(url, compression="deflate", ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": BOUNDING_BOXES, "FilterMessageTypes": POSITION_TYPES}))
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
                        position = normalize(message, now)
                    except (ValueError, TypeError, AttributeError):
                        state["invalid_messages"] += 1
                        continue
                    if position:
                        app.state.store.save(position)
                        state["status"] = "receiving"
                        state["last_error"] = None
                        state["positions_received"] += 1
                        state["last_position_at"] = now
                        delay = 1
                    else:
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


def create_app(database=None, api_key=None, stream_url=STREAM_URL):
    @asynccontextmanager
    async def lifespan(app):
        load_dotenv()
        key = api_key if api_key is not None else os.getenv("AISSTREAM_API_KEY", "")
        app.state.stale_seconds = max(1, int(os.getenv("STALE_SECONDS", "900")))
        app.state.store = Store(database or os.getenv("DATABASE_PATH", "data/ais.sqlite3"))
        app.state.stream = dict(status="missing_api_key", last_error=None, last_message_at=None,
                                last_position_at=None, messages_received=0, positions_received=0,
                                invalid_messages=0, discarded_messages=0, reconnects=0, started_at=time.time())
        task = asyncio.create_task(collect(app, key, stream_url)) if key.strip() else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            app.state.store.close()

    app = FastAPI(title="Aperium · Hormuz region AIS", lifespan=lifespan,
                  description="Observed vessel activity around Fujairah, Shahid Rajaee, Khor Fakkan, and Jebel Ali. Approximate discovery boxes, not official anchorage boundaries or congestion scores. Times are Unix seconds in UTC.")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/docs")

    @app.get("/api/status")
    async def status():
        now = time.time()
        last = app.state.stream["last_position_at"]
        age = None if last is None else round(now - last, 1)
        return {**app.state.stream, "geofences": PORTS,
                "seconds_since_last_position": age,
                "data_status": "no_positions_received" if last is None else
                    ("stale" if age > app.state.stale_seconds else "recent_positions_received"),
                "stale_seconds": app.state.stale_seconds, "now": now}

    @app.get("/api/ports")
    async def ports():
        return [{"id": key, **value, "boundary_type": "approximate_discovery_box"}
                for key, value in PORTS.items()]

    @app.get("/api/vessels")
    async def vessels(include_stale: bool = False, port: Optional[PortId] = None):
        items = app.state.store.vessels(time.time(), app.state.stale_seconds)
        return [v for v in items if v["inside_geofence"] and (include_stale or not v["stale"])
                and (port is None or port in v["ports"])]

    @app.get("/api/metrics")
    async def metrics(port: Optional[PortId] = None):
        all_vessels = app.state.store.vessels(time.time(), app.state.stale_seconds)
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
                "by_port": {key: summarize([v for v in all_vessels if key in v["ports"]])
                            for key in PORTS if port is None or key == port},
                "stream_status": app.state.stream["status"],
                "note": "Observed activity only. Zero may mean no coverage. Slow/anchored vessels are not necessarily waiting for a berth."}

    @app.get("/api/vessels/{mmsi}/history")
    async def history(mmsi: str, limit: int = Query(100, ge=1, le=10000)):
        return app.state.store.history(mmsi, limit)

    return app


app = create_app()
