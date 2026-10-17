"""Read-only HTTP API over outputs/latest/ (files written by aperium.run).

Run: uv run uvicorn aperium.api:app --port 8001
It never connects to AISstream, so it can run beside the recorder.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from aperium.contract import SCHEMA_VERSION, SCHEMAS

OUT = Path(os.getenv("OUTPUTS_DIR", "outputs/latest"))
Region = Literal["corpus_christi", "hormuz"]

router = APIRouter(tags=["tanker monitor"])


def files():
    """Static files under outputs/latest/ (sentinel images), mounted at /api/files and /files."""
    OUT.mkdir(parents=True, exist_ok=True)
    return StaticFiles(directory=OUT)


app = FastAPI(title="Aperium tanker monitor (read-only)", version=SCHEMA_VERSION,
              description="Serves the JSON files in outputs/latest/. Shapes are defined in SCHEMA.md and schema/*.json. "
                          "All outputs are uncalibrated estimates (calibrated: false).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def load(relative):
    path = OUT / relative
    if not path.exists():
        raise HTTPException(503, f"{relative} not written yet; is aperium.run running?")
    return json.loads(path.read_text())


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


@router.get("/api/health")
async def health():
    files = {p.relative_to(OUT).as_posix(): datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()
             for p in sorted(OUT.rglob("*.json*")) if not p.name.endswith(".tmp")}
    return {"schema_version": SCHEMA_VERSION, "outputs_dir": str(OUT), "files_modified_utc": files}


@router.get("/api/schema/{name}")
async def schema(name: Literal["regions", "vessels", "event", "metrics", "sentinel", "cpi_nowcast", "cpi_scenario"]):
    return SCHEMAS[name]


@router.get("/api/regions")
async def regions():
    return load("regions.json")


@router.get("/api/regions/{region}/vessels")
async def vessels(region: Region):
    return load(f"{region}/vessels.json")


@router.get("/api/regions/{region}/metrics")
async def metrics(region: Region):
    return load(f"{region}/metrics.json")


@router.get("/api/regions/{region}/sentinel")
async def sentinel(region: Region):
    return load(f"{region}/sentinel.json")


@router.get("/api/regions/{region}/events")
async def events(region: Region, since: Optional[datetime] = Query(None, description="UTC ISO-8601; only events after this"),
                 limit: int = Query(200, ge=1, le=5000)):
    """Newest first."""
    path = OUT / region / "events.jsonl"
    if not path.exists():
        return []
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if since:
        cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        items = [e for e in items if datetime.fromisoformat(e["ts_utc"].replace("Z", "+00:00")) > cutoff]
    return items[::-1][:limit]


@router.get("/api/cpi_nowcast")
async def cpi_nowcast():
    return load("cpi_nowcast.json")


@router.get("/api/cpi/scenario")
@router.get("/cpi/scenario", include_in_schema=False)
async def cpi_scenario(disruption: float = Query(..., ge=0, le=1, description="Fraction of Hormuz flow disrupted, 0..1"),
                       days: float = Query(..., gt=0, le=365, description="Duration in days, (0, 365]")):
    """What-if shock from the cached baseline (no network); starts now. Shape: schema 'cpi_scenario'."""
    from aperium import cpi_nowcast
    return cpi_nowcast.scenario(disruption, days, OUT)


app.include_router(router)
app.mount("/api/files", files(), name="files")
app.mount("/files", files(), name="files-legacy")
