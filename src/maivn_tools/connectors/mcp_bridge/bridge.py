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
            message = 'MCPServerSpec.name is required'
            raise ValueError(message)
        if self.rate_limit_per_minute is not None and self.rate_limit_per_minute < 1:
            message = 'rate_limit_per_minute must be at least 1'
            raise ValueError(message)


@dataclass(frozen=True)
class MCPStdioServer(MCPServerSpec):
    """Specification for an MCP server launched as a subprocess via stdio."""

    command: str = ''
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.command:
            message = 'MCPStdioServer.command is required'
            raise ValueError(message)


@dataclass(frozen=True)
class MCPHttpServer(MCPServerSpec):
    """Specification for an MCP server reached over HTTP."""

    url: str = ''
    headers: dict[str, str] = field(default_factory=dict)
    bearer_token: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.url:
            message = 'MCPHttpServer.url is required'
            raise ValueError(message)


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
        from maivn import MCPServer  # noqa: PLC0415 - intentional lazy SDK seam

        servers: list[Any] = []
        for spec in self._specs:
            kwargs: dict[str, Any] = {
                'name': spec.name,
            }
            if spec.prefix is not None:
                kwargs['tool_name_prefix'] = spec.prefix
            if spec.default_args:
                kwargs['default_tool_args'] = dict(spec.default_args)
            if spec.rate_limit_per_minute is not None:
                kwargs['max_calls_per_minute'] = spec.rate_limit_per_minute
            if spec.soft_error_retry:
                kwargs['soft_error_handling'] = {'enabled': True}
            if isinstance(spec, MCPStdioServer):
                kwargs.update(
                    transport='stdio',
                    command=spec.command,
                    args=list(spec.args),
                    env=dict(spec.env),
                    working_dir=spec.cwd,
                )
            elif isinstance(spec, MCPHttpServer):
                headers = dict(spec.headers)
                if spec.bearer_token is not None:
                    headers['Authorization'] = f'Bearer {spec.bearer_token}'
                kwargs.update(
                    transport='http',
                    url=spec.url,
                    headers=headers,
                )
            else:
                message = f'Unsupported MCPServerSpec subtype: {type(spec).__name__}'
                raise TypeError(message)
            servers.append(MCPServer(**kwargs))
        return servers
