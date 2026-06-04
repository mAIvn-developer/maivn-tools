"""Declarative MCP server specifications.

These helpers convert simple dataclass-style specs into ``maivn.MCPServer``
instances at registration time. The conversion is lazy so importing this
module does not require the ``maivn`` SDK to be installed.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# MARK: Specifications


@dataclass(frozen=True)
class MCPServerSpec:
    """Base specification for an MCP server.

    Attributes:
        name: Logical name used in tool prefixes and audit logs.
        prefix: Optional tool-name prefix applied to discovered tools.
        default_args: Default arguments applied when invoking discovered tools.
        rate_limit_per_minute: Optional rate-limit hint for the host.
        soft_error_retry: Whether the host should retry soft errors silently.
        scopes: Documentation-only scopes the server declares.
    """

    name: str
    prefix: str | None = None
    default_args: dict[str, Any] = field(default_factory=dict)
    rate_limit_per_minute: int | None = None
    soft_error_retry: bool = False
    scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MCPServerSpec.name is required")
        if self.rate_limit_per_minute is not None and self.rate_limit_per_minute < 1:
            raise ValueError("rate_limit_per_minute must be at least 1")


@dataclass(frozen=True)
class MCPStdioServer(MCPServerSpec):
    """Specification for an MCP server launched as a subprocess via stdio."""

    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.command:
            raise ValueError("MCPStdioServer.command is required")


@dataclass(frozen=True)
class MCPHttpServer(MCPServerSpec):
    """Specification for an MCP server reached over HTTP."""

    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    bearer_token: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.url:
            raise ValueError("MCPHttpServer.url is required")


# MARK: Bridge


class MCPBridge:
    """Build ``maivn.MCPServer`` instances from declarative specifications.

    The bridge imports ``maivn`` lazily on :meth:`build` so it can be defined
    and inspected in environments where the SDK is not installed.
    """

    def __init__(self, specs: Iterable[MCPServerSpec]) -> None:
        self._specs = tuple(specs)

    @property
    def specs(self) -> tuple[MCPServerSpec, ...]:
        return self._specs

    def build(self) -> list[Any]:
        """Return constructed ``maivn.MCPServer`` instances.

        Raises:
            RuntimeError: When ``maivn`` is not importable in the current
                environment.
        """
        try:
            from maivn import MCPServer  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on user env
            raise RuntimeError(
                "MCPBridge.build() requires the 'maivn' SDK to be installed."
            ) from exc

        servers: list[Any] = []
        for spec in self._specs:
            kwargs: dict[str, Any] = {
                "name": spec.name,
            }
            if spec.prefix is not None:
                kwargs["prefix"] = spec.prefix
            if spec.default_args:
                kwargs["default_args"] = dict(spec.default_args)
            if spec.rate_limit_per_minute is not None:
                kwargs["rate_limit_per_minute"] = spec.rate_limit_per_minute
            if spec.soft_error_retry:
                kwargs["soft_error_retry"] = True
            if isinstance(spec, MCPStdioServer):
                kwargs.update(
                    transport="stdio",
                    command=spec.command,
                    args=list(spec.args),
                    env=dict(spec.env),
                    cwd=spec.cwd,
                )
            elif isinstance(spec, MCPHttpServer):
                kwargs.update(
                    transport="http",
                    url=spec.url,
                    headers=dict(spec.headers),
                )
                if spec.bearer_token is not None:
                    kwargs["bearer_token"] = spec.bearer_token
            else:
                raise TypeError(f"Unsupported MCPServerSpec subtype: {type(spec).__name__}")
            servers.append(MCPServer(**kwargs))
        return servers
