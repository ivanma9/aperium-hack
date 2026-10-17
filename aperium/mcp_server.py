"""MCP server for Aperium: the collector's and tanker monitor's data as tools.

Two ways in, same tools:
  * Streamable HTTP at http://127.0.0.1:8000/mcp, mounted on the collector (aperium.app).
  * stdio:  uv run python -m aperium.mcp_server   (for harnesses that launch a command)

Every tool is a thin wrapper over one REST endpoint of the running collector
(APERIUM_API_URL, default http://127.0.0.1:8000), so MCP clients see exactly what the
HUD and REST clients see. Local and unauthenticated, like the rest of the API: it only
accepts loopback Host headers (DNS-rebinding protection) and must not be exposed publicly
without adding auth (the handoff calls for OAuth).
"""
import os
from typing import Any, Literal, Optional

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
Region = Literal["hormuz", "corpus_christi"]

mcp = MCPServer(
    "aperium",
    instructions=(
        "Energy-flow intelligence around the Strait of Hormuz. Live AIS data comes from AISstream via the "
        "collector (ships inside port geofences, per-port counts). The tanker monitor derives tanker state, "
        "gate crossings and an UNCALIBRATED US energy-CPI nowcast (calibrated: false); its CPI level is anchored "
        "on BLS/EIA prices, and AIS only supplies a Hormuz disruption shock. Say so when reporting CPI figures. "
        "Timestamps are UTC: Unix seconds for collector data, ISO-8601 for monitor data."
    ),
)


# Every tool returns a JSON object, never a bare list: list results are split into one content
# block per item, so an empty list would reach the client as no content at all.


class AperiumError(ToolError):
    """An anticipated failure: the client gets the message as an is_error result (other exceptions are hidden)."""


def api_url() -> str:
    """The collector's base URL, read per call so it can be changed without re-importing."""
    return os.getenv("APERIUM_API_URL", "http://127.0.0.1:8000").rstrip("/")


async def _get(path: str, params: Optional[dict[str, Any]] = None) -> Any:
    query = {k: v for k, v in (params or {}).items() if v is not None}
    base = api_url()
    try:
        async with httpx.AsyncClient(base_url=base, timeout=TIMEOUT) as client:
            res = await client.get(path, params=query)
    except httpx.HTTPError as exc:
        raise AperiumError(
            f"Aperium collector unreachable at {base} ({type(exc).__name__}). Start it with ./dev.sh."
        ) from None
    if res.status_code == 503:
        detail = res.json().get("detail", "") if res.headers.get("content-type", "").startswith("application/json") else ""
        raise AperiumError(
            f"Not available yet: {detail or res.text}. Tanker-monitor outputs are written by `uv run python -m "
            "aperium.run` (live) or a replay; see the README's tanker monitor section."
        )
    if res.status_code >= 400:
        raise AperiumError(f"GET {path} returned HTTP {res.status_code}: {res.text[:500]}")
    return res.json()


# ── Collector: geographies, ports, live AIS ─────────────────────────────


@mcp.tool()
async def list_geographies() -> dict[str, Any]:
    """Monitored geographies (chokepoints) with baseline flow (mb/d), bypass capacity and label, risk-premium
    multiplier, map bbox [west, south, east, north], and their port geofences. Lanes/gates are omitted;
    they are approximate drawing geometry. Source: Postgres `geographies` + `ports` tables."""
    rows = await _get("/api/geographies")
    keep = ("id", "name", "short_name", "base_mbd", "bypass_cap_mbd", "bypass_label", "premium_multiplier", "bbox", "ports")
    return {"geographies": [{k: g.get(k) for k in keep} for g in rows]}


@mcp.tool()
async def get_collector_status() -> dict[str, Any]:
    """AIS collector health: upstream connection status (e.g. receiving, missing_api_key, reconnecting),
    message/position counters, seconds since the last position, data freshness, the geofences in use,
    and whether the live event stream is listening. Check this before interpreting empty results."""
    return await _get("/api/status")


@mcp.tool()
async def list_vessels(port: Optional[str] = None, include_stale: bool = False) -> dict[str, Any]:
    """Live AIS vessels observed inside the port geofences (latest position per MMSI): name, lat/lon,
    speed (kn), course, ITU navigational status code (1 = at anchor, 5 = moored), observation time,
    age, staleness and matching ports. `port` filters by port id (see list_geographies, e.g.
    'fujairah'); stale positions (older than the collector's STALE_SECONDS) are excluded unless
    include_stale is true. Empty can mean no receiver coverage, not no ships."""
    vessels = await _get("/api/vessels", {"port": port, "include_stale": str(include_stale).lower()})
    return {"port": port, "count": len(vessels), "vessels": vessels}


@mcp.tool()
async def get_port_metrics(port: Optional[str] = None) -> dict[str, Any]:
    """Per-port activity from live AIS: active vessels, slow (<1 kn), reported at anchor, stale, data status.
    Observed activity only; slow/anchored ships aren't necessarily waiting for a berth."""
    return await _get("/api/metrics", {"port": port})


@mcp.tool()
async def get_vessel_history(mmsi: str, limit: int = 100) -> dict[str, Any]:
    """Stored AIS observations for one vessel (MMSI), newest first. limit 1–10000."""
    rows = await _get(f"/api/vessels/{mmsi}/history", {"limit": max(1, min(limit, 10000))})
    return {"mmsi": mmsi, "count": len(rows), "observations": rows}


# ── Tanker monitor: regions, flow, CPI ──────────────────────────────────


@mcp.tool()
async def list_regions() -> dict[str, Any]:
    """Tanker-monitor regions (Strait of Hormuz = signal, Corpus Christi = context) with their summary
    state. Written by aperium.run; schema 'regions'."""
    return await _get("/api/regions")


@mcp.tool()
async def get_flow_estimate(region: Region = "hormuz") -> dict[str, Any]:
    """Tanker flow for a region: tankers present, waiting at anchor and average wait, gate crossings
    (in / out / laden out) over 24 h, 3 d and 7 d windows, laden departures per day, estimated barrels
    departed today, and AIS coverage versus baseline. Uncalibrated estimates (calibrated: false)."""
    return await _get(f"/api/regions/{region}/metrics")


@mcp.tool()
async def list_region_tankers(region: Region = "hormuz") -> dict[str, Any]:
    """Tankers the monitor is tracking in a region, with class, laden state and zone. Schema 'vessels'."""
    return await _get(f"/api/regions/{region}/vessels")


@mcp.tool()
async def get_region_events(region: Region = "hormuz", since: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    """Tanker events in a region (gate crossings, arrivals, departures, anchoring…), newest first.
    `since` is a UTC ISO-8601 timestamp; limit 1–5000."""
    events = await _get(f"/api/regions/{region}/events", {"since": since, "limit": max(1, min(limit, 5000))})
    return {"region": region, "count": len(events), "events": events}


@mcp.tool()
async def get_energy_cpi_outlook() -> dict[str, Any]:
    """Current US energy-CPI nowcast with the live Strait of Hormuz disruption shock. UNCALIBRATED
    (calibrated: false): the level is anchored on the latest BLS print and EIA weekly retail gasoline;
    AIS gate crossings only supply the disruption shock. Includes its assumptions. Schema 'cpi_nowcast'."""
    return await _get("/api/cpi_nowcast")


@mcp.tool()
async def run_scenario(disruption: float, days: float) -> dict[str, Any]:
    """What-if: shock the cached CPI baseline with a Hormuz disruption starting now. `disruption` is the
    fraction of Hormuz flow lost (0–1, e.g. 0.36), `days` its duration (0–365]. No network calls.
    UNCALIBRATED; schema 'cpi_scenario'."""
    if not 0 <= disruption <= 1:
        raise AperiumError("disruption must be between 0 and 1 (fraction of Hormuz flow lost)")
    if not 0 < days <= 365:
        raise AperiumError("days must be in (0, 365]")
    return await _get("/api/cpi/scenario", {"disruption": disruption, "days": days})


if __name__ == "__main__":
    mcp.run()  # stdio
