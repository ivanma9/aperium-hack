"""MCP server end to end: a real collector over HTTP, driven by the MCP SDK client,
over both transports (Streamable HTTP at /mcp, and stdio via `python -m aperium.mcp_server`)."""
import asyncio
import json
import socket
import sys
import time

import pytest
import uvicorn

pytest.importorskip("mcp", reason="MCP SDK needs Python 3.10+")
from mcp import Client, StdioServerParameters  # noqa: E402

from aperium.app import create_app  # noqa: E402
from aperium.tracking import normalize  # noqa: E402
from test_tracking import message  # noqa: E402

EXPECTED_TOOLS = {
    "list_geographies", "get_collector_status", "list_vessels", "get_port_metrics", "get_vessel_history",
    "list_regions", "get_flow_estimate", "list_region_tankers", "get_region_events", "get_energy_cpi_outlook",
    "run_scenario",
}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def data(result):
    """Tool result → dict. Every tool returns exactly one JSON object as text content."""
    assert not result.is_error, result.content
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


async def serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


def test_mcp_over_streamable_http_and_stdio(database_url, monkeypatch):
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("APERIUM_API_URL", base)

    async def scenario():
        app = create_app(database_url=database_url, api_key="")
        server, task = await serve(app, port)
        try:
            await app.state.store.save(normalize(message(), time.time()))  # one ship in Fujairah

            async with Client(f"{base}/mcp") as client:
                tools = {t.name for t in (await client.list_tools()).tools}
                assert EXPECTED_TOOLS <= tools

                geos = data(await client.call_tool("list_geographies", {}))["geographies"]
                assert [g["id"] for g in geos][:1] == ["hormuz"]
                assert "lanes" not in geos[0] and len(geos[0]["ports"]) == 4

                status = data(await client.call_tool("get_collector_status", {}))
                assert status["status"] == "missing_api_key"

                vessels = data(await client.call_tool("list_vessels", {"port": "fujairah"}))
                assert vessels["count"] == 1 and [v["mmsi"] for v in vessels["vessels"]] == ["123456789"]

                # Empty results are still one well-formed object, not zero content blocks.
                none = data(await client.call_tool("list_vessels", {"port": "jebel_ali"}))
                assert none == {"port": "jebel_ali", "count": 0, "vessels": []}
                history = data(await client.call_tool("get_vessel_history", {"mmsi": "123456789"}))
                assert history["count"] == 1

                metrics = data(await client.call_tool("get_port_metrics", {}))
                assert metrics["by_port"]["fujairah"]["active_vessels"] == 1

                bad = await client.call_tool("run_scenario", {"disruption": 2, "days": 10})
                assert bad.is_error and "between 0 and 1" in bad.content[0].text

                # Monitor outputs may or may not exist on this machine; either data or a readable hint.
                flow = await client.call_tool("get_flow_estimate", {"region": "hormuz"})
                assert (not flow.is_error and "crossings" in json.loads(flow.content[0].text)) or "aperium.run" in flow.content[0].text

            # stdio: the same tools from a subprocess, talking to the same collector over REST.
            params = StdioServerParameters(command=sys.executable, args=["-m", "aperium.mcp_server"],
                                           env={"APERIUM_API_URL": base, "PYTHONPATH": "."})
            async with Client(params) as client:
                assert EXPECTED_TOOLS <= {t.name for t in (await client.list_tools()).tools}
                vessels = data(await client.call_tool("list_vessels", {}))
                assert [v["mmsi"] for v in vessels["vessels"]] == ["123456789"]
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_mcp_reports_unreachable_collector(monkeypatch):
    monkeypatch.setenv("APERIUM_API_URL", f"http://127.0.0.1:{free_port()}")  # nothing listening

    async def scenario():
        from aperium.mcp_server import mcp
        async with Client(mcp) as client:  # in-memory transport
            res = await client.call_tool("get_collector_status", {})
            assert res.is_error and "unreachable" in res.content[0].text

    asyncio.run(scenario())
