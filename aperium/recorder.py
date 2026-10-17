"""Record raw AISstream messages for the monitor regions to data/raw_YYYYMMDD.jsonl.

One upstream connection covers both regions (AISstream allows one per key), so do
not run this alongside aperium.app's built-in collector with the same key.
Run: uv run python -m aperium.recorder
"""
import asyncio
import json
import logging
import os
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from websockets.asyncio.client import connect

from aperium.regions import REGIONS, region_of

STREAM_URL = "wss://stream.aisstream.io/v0/stream"
MESSAGE_TYPES = ["PositionReport", "ShipStaticData"]
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
log = logging.getLogger("aperium.recorder")


def raw_path(now=None):
    now = now or datetime.now(timezone.utc)
    return DATA_DIR / f"raw_{now:%Y%m%d}.jsonl"


class Stats:
    """Per-region message counts and distinct tanker MMSIs for the 60 s report."""

    def __init__(self):
        self.ship_type = {}
        self.reset()

    def reset(self):
        self.messages = defaultdict(int)
        self.mmsis = defaultdict(set)

    def add(self, message):
        meta = message.get("MetaData", {})
        mmsi = str(meta.get("MMSI", ""))
        if message.get("MessageType") == "ShipStaticData":
            kind = message.get("Message", {}).get("ShipStaticData", {}).get("Type")
            if isinstance(kind, int):
                self.ship_type[mmsi] = kind
        region = region_of(meta.get("latitude"), meta.get("longitude"))
        if region:
            self.messages[region] += 1
            self.mmsis[region].add(mmsi)

    def report(self):
        parts = []
        for rid in REGIONS:
            tankers = sum(80 <= self.ship_type.get(m, 0) <= 89 for m in self.mmsis[rid])
            parts.append(f"{rid}: {self.messages[rid]} msgs, {len(self.mmsis[rid])} vessels, {tankers} tankers")
        return " | ".join(parts)


async def record(key, url=STREAM_URL, stats=None):
    stats = stats or Stats()
    boxes = [r["bbox"] for r in REGIONS.values()]
    delay = 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            async with connect(url, compression="deflate", ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": boxes, "FilterMessageTypes": MESSAGE_TYPES}))
                log.info("subscribed to %s", ", ".join(REGIONS))
                async for raw in ws:
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    if "error" in message or "Error" in message:
                        # Payload may echo request details; report the fact, not the body.
                        raise ConnectionError("AISstream rejected the subscription; check the key")
                    message["received_at"] = datetime.now(timezone.utc).isoformat()
                    with raw_path().open("a") as f:
                        f.write(json.dumps(message, separators=(",", ":")) + "\n")
                    stats.add(message)
                    delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("connection interrupted (%s: %s); retrying in ~%ds", type(exc).__name__,
                        exc if isinstance(exc, ConnectionError) else "", delay)
        await asyncio.sleep(delay + random.uniform(0, 1))
        delay = min(delay * 2, 60)


async def main():
    load_dotenv()
    key = os.getenv("AISSTREAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("AISSTREAM_API_KEY is not set. Get a key at https://aisstream.io (GitHub login) and add it to .env")
    stats = Stats()
    task = asyncio.create_task(record(key, stats=stats))
    started = time.time()
    while not task.done():
        await asyncio.sleep(60)
        print(f"[{datetime.now(timezone.utc):%H:%M:%SZ}] last 60s ({time.time() - started:.0f}s up) {stats.report()}", flush=True)
        stats.reset()
    task.result()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
