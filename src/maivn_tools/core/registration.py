"""Registration helpers for attaching connector tools to hosts.

Toolset connectors keep their v1 public shape: classes are decorated with
``maivn.toolset`` and methods are decorated with ``maivn.toolify``. The backing
strategy below that public shape is now resolved here. Official/community
providers return MCP-backed contract specs, while the explicit NONE and
PLATFORM primitives keep native v1 receiver specs.
"""

# pyright: strict

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable

from .backends import TOOLSET_ATTR, ToolSetRegistration, toolset_contract_specs
from .protocols import Connector, ToolFactory, ToolProvider


@runtime_checkable
class _ToolHost(Protocol):
    """Minimum host surface required to register builder connector tools."""

    def add_tool(self, tool: Any, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class _ToolSetBackendHost(Protocol):
    """Optional host surface for receiving resolved toolset registrations."""

    def add_toolset_backend(self, registration: ToolSetRegistration) -> Any: ...


def resolve_connector_tools(
    source: Connector | ToolProvider | Iterable[ToolFactory],
) -> list[ToolFactory]:
    """Resolve a builder-style connector or iterable into a list of factories."""
    if isinstance(source, Connector):
        return list(source.tools())
    if isinstance(source, ToolProvider):
        return list(source.tools())
    return list(source)


def register_tools(host: _ToolHost, tools: Iterable[ToolFactory]) -> list[Any]:
    """Register an iterable of tool factories on a host via ``add_tool``."""
    if not hasattr(host, 'add_tool'):
        message = (
            "register_tools requires a host with an 'add_tool' method "
            '(for example, maivn.Agent or maivn.Swarm).'
        )
        raise TypeError(message)
    return [host.add_tool(tool) for tool in tools]


def register_connector(host: _ToolHost, connector: object) -> list[Any]:
    """Attach every tool a connector exposes to ``host``.

    Toolset connectors return a :class:`ToolSetRegistration` carrying owned
    contract specs. Hosts that expose ``add_toolset_backend`` also receive the
    resolved registration directly. Builder connectors retain the v1 native
    ``tools()`` path and register each callable through ``add_tool``.
    """
    if hasattr(type(connector), TOOLSET_ATTR):
        registration = toolset_contract_specs(connector)
        if isinstance(host, _ToolSetBackendHost):
            host.add_toolset_backend(registration)
        add_toolset: Any = getattr(host, 'add_toolset', None)
        if add_toolset is not None:
            return list(add_toolset(connector))
        return [registration]
    builder = cast('Connector | ToolProvider | Iterable[ToolFactory]', connector)
    return register_tools(host, resolve_connector_tools(builder))


toolset = resolve_connector_tools


__all__ = [
    'TOOLSET_ATTR',
    'ToolSetRegistration',
    'register_connector',
    'register_tools',
    'resolve_connector_tools',
    'toolset',
]
