"""Helpers for attaching MCP servers to mAIvn Agents.

The mAIvn SDK already exposes ``MCPServer`` directly. The helpers in this
module sit on top of that, packaging common configurations (stdio, http,
``uvx`` auto-setup) behind smaller declarative interfaces. They are
intentionally light because the SDK already does the heavy lifting.

The bridge avoids importing ``maivn`` at module load time so the helpers are
usable in environments where the SDK is not yet installed.
"""

from __future__ import annotations

from .bridge import (
    MCPBridge,
    MCPHttpServer,
    MCPServerSpec,
    MCPStdioServer,
)

__all__ = [
    "MCPBridge",
    "MCPHttpServer",
    "MCPServerSpec",
    "MCPStdioServer",
]
