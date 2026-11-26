"""Discover tools and call a keyless route through the MCP command shipped to users."""

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def smoke(config, root, state_dir):
    cmd = config["mcpServers"]["ya-webmaster"]
    args = [a.replace("\u0024{PLUGIN_ROOT}", str(root)) for a in cmd["args"]]
    env = {
        k: os.environ[k]
        for k in (
            "PATH",
            "UV_CACHE_DIR",
            "UV_PYTHON_INSTALL_DIR",
            "SYSTEMROOT",
            "APPDATA",
            "LOCALAPPDATA",
            "USERPROFILE",
        )
        if k in os.environ
    }
    env["SITE_DESK_STATE_DIR"] = str(state_dir)
    env["UV_TOOL_DIR"] = str(root / "uv-tools")
    proc = StdioServerParameters(command=cmd["command"], args=args, env=env)
    async with (
        stdio_client(proc) as (reader, writer),
        ClientSession(reader, writer) as client,
    ):
        await client.initialize()
        names = {t.name for t in (await client.list_tools()).tools}
        assert {
            "entrance_map",
            "metrica_ensure_counter",
            "organization_draft",
            "watch_check",
        } <= names
        result = await client.call_tool(
            "entrance_map",
            {
                "entrance": {"name": "Door", "lat": 55.75, "lon": 37.62},
                "stops": [{"name": "Stop", "lat": 55.76, "lon": 37.61}],
            },
        )
        assert not result.isError and "rtt=pd" in str(result.content)
        assert len(list((state_dir / "maps").glob("*.gpx"))) == 1
        print(f"{len(names)} tools, walking link and GPX OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path, help="Plugin ZIP or marketplace mcp.json")
    source = ap.parse_args().source.resolve()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if source.suffix == ".zip":
            with ZipFile(source) as archive:
                archive.extractall(root)
            config = root / "mcp.json"
        else:
            config = source
        asyncio.run(smoke(json.loads(config.read_text("utf-8")), root, root / "state"))
