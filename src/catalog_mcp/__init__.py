"""A read-only MCP server over a governed data catalog.

The runnable version of https://cordata.tech/en/blog/governed-mesh-over-mcp.
"""

__version__ = "0.1.0"

# The protocol revision and SDK this was verified against. Stated in code as
# well as the README, so `server/discover` and a reader agree on how current it is.
PROTOCOL_REVISION = "2026-07-28"
