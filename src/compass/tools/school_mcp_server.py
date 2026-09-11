"""FastMCP server exposing the university's systems to the agent.

Design note — why MCP and not just Python functions
---------------------------------------------------
Compass's premise is that a student's rules are spread across systems that do
not talk to each other: the catalogue, the degree audit, the calendar, the
announcement feed. Modelling those as an **MCP server** puts the integration
boundary in the same place the real world puts it, and means the agent's tools
are discoverable, versioned and independently testable. A different
institution's systems could be dropped in behind the same protocol without
touching any agent code.

The server is deliberately **read-only and dumb**. It answers questions about
data and decides nothing. All judgement lives in the agents, and the decision
about whether to interrupt the student lives in ``compass.gate``.

The tool functions themselves live in ``compass.tools.school_tools`` so that the
direct-``@tool`` fallback path and this server cannot drift apart.

Run it standalone to poke at it:

    python -m compass.tools.school_mcp_server
"""

from __future__ import annotations

from fastmcp import FastMCP

from .school_tools import SCHOOL_FUNCTIONS

mcp = FastMCP(
    name="compass-school",
    instructions=(
        "Read-only access to a university's module catalogue, degree "
        "requirements, academic calendar, announcement feed and a single "
        "student's record. All data is synthetic."
    ),
)

# Decorate the shared function objects — one definition, two transports.
for _fn in SCHOOL_FUNCTIONS:
    mcp.tool(_fn)


if __name__ == "__main__":
    mcp.run()
