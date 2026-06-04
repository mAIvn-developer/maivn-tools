# pyright: strict
from __future__ import annotations

import sys
from typing import Any

import pytest

from maivn_tools.connectors.mcp_bridge import (
    MCPBridge,
    MCPHttpServer,
    MCPServerSpec,
    MCPStdioServer,
)


def test_mcp_server_spec_validates_inputs() -> None:
    with pytest.raises(ValueError):
        MCPServerSpec(name="")
    with pytest.raises(ValueError):
        MCPServerSpec(name="x", rate_limit_per_minute=0)


def test_mcp_stdio_server_requires_command() -> None:
    with pytest.raises(ValueError):
        MCPStdioServer(name="x")


def test_mcp_http_server_requires_url() -> None:
    with pytest.raises(ValueError):
        MCPHttpServer(name="x")


def test_mcp_bridge_passes_kwargs_to_fake_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    class FakeMCPServer:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    fake_module = type("FakeMaivnModule", (), {"MCPServer": FakeMCPServer})
    monkeypatch.setitem(sys.modules, "maivn", fake_module)

    bridge = MCPBridge(
        [
            MCPStdioServer(
                name="fs",
                command="uvx",
                args=("mcp-filesystem",),
                env={"FOO": "bar"},
                prefix="fs.",
                rate_limit_per_minute=10,
                soft_error_retry=True,
                default_args={"root": "/srv"},
            ),
            MCPHttpServer(
                name="search",
                url="https://mcp.example.com",
                headers={"X-Tenant": "abc"},
                bearer_token="token",
            ),
        ]
    )
    servers = bridge.build()
    assert len(servers) == 2

    stdio = captured[0]
    assert stdio["transport"] == "stdio"
    assert stdio["command"] == "uvx"
    assert stdio["args"] == ["mcp-filesystem"]
    assert stdio["env"] == {"FOO": "bar"}
    assert stdio["prefix"] == "fs."
    assert stdio["rate_limit_per_minute"] == 10
    assert stdio["soft_error_retry"] is True
    assert stdio["default_args"] == {"root": "/srv"}

    http = captured[1]
    assert http["transport"] == "http"
    assert http["url"] == "https://mcp.example.com"
    assert http["headers"] == {"X-Tenant": "abc"}
    assert http["bearer_token"] == "token"


def test_mcp_bridge_rejects_unknown_spec_subtype(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMCPServer:
        def __init__(self, **kwargs: Any) -> None:
            pass

    fake_module = type("FakeMaivnModule", (), {"MCPServer": FakeMCPServer})
    monkeypatch.setitem(sys.modules, "maivn", fake_module)

    bridge = MCPBridge([MCPServerSpec(name="x")])
    with pytest.raises(TypeError):
        bridge.build()
