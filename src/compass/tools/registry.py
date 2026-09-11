"""Assembling the tool bundle an agent runs with.

Two transports, one list of tools:

* ``use_mcp=True`` — start the school MCP server as a subprocess and hand the
  agent its tools. This is the real configuration and the one the deployment
  uses.
* ``use_mcp=False`` — hand the agent the same functions as in-process Strands
  tools. Used by the test suite, which should not pay for a subprocess per test,
  and as the documented fallback if a runtime makes stdio subprocesses awkward.

Either way the agent receives an identical set of capabilities, because both
transports decorate the same function objects in ``school_tools``.

The deterministic analysis tools are always added directly. They are Compass's
own arithmetic, not the school's data, so they do not belong behind the school's
protocol boundary — and they must stay available even if the MCP server is
down, because the gate depends on their exactness.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .analysis_tools import ANALYSIS_TOOLS
from .school_tools import SCHOOL_TOOLS, reset_store


@contextmanager
def agent_tools(
    use_mcp: bool = True,
    data_dir: Path | str | None = None,
) -> Iterator[list]:
    """Yield the tool list for an agent, managing the MCP lifecycle if used."""

    if data_dir is not None:
        os.environ["COMPASS_DATA_DIR"] = str(data_dir)
        reset_store()

    if not use_mcp:
        yield list(SCHOOL_TOOLS) + list(ANALYSIS_TOOLS)
        return

    from mcp import StdioServerParameters, stdio_client
    from strands.tools.mcp import MCPClient

    env = dict(os.environ)
    if data_dir is not None:
        env["COMPASS_DATA_DIR"] = str(data_dir)

    client = MCPClient(lambda: stdio_client(StdioServerParameters(
        command=sys.executable,
        args=["-m", "compass.tools.school_mcp_server"],
        env=env,
    )))

    with client:
        yield client.list_tools_sync() + list(ANALYSIS_TOOLS)
