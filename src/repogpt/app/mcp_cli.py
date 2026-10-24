"""Launch the optional MCP transport without importing it in a base install."""

from __future__ import annotations

import sys
from importlib import import_module


def main() -> int:
    """Explain missing MCP extras while preserving unrelated import failures."""
    try:
        transport = import_module("repogpt.mcp_server")
    except ModuleNotFoundError as exc:
        if exc.name is None or exc.name.split(".")[0] not in {"anyio", "jsonschema", "mcp"}:
            raise
        print(
            "MCP support requires the optional extra: uv pip install 'repogpt[mcp]'",
            file=sys.stderr,
        )
        return 2
    return int(transport.main())
