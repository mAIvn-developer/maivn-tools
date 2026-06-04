"""Registration helpers for attaching connector tools to Agents and Swarms.

Two register paths coexist:

* **Toolset connectors** — classes decorated with ``maivn.toolset`` whose
  methods are decorated with ``maivn.toolify``. These are registered via
  ``host.add_toolset(instance)`` in one call. The SDK walks the instance,
  builds one ``MethodTool`` per ``@toolify``-marked method, and registers
  each on the host. Provider connectors shipped in ``maivn-tools`` use
  this pattern.

* **Builder connectors** — legacy / data-driven connectors that expose
  ``connector.tools() -> list[Callable]``. Each callable is registered via
  ``host.add_tool(callable)``. The generic adapters
  (``GenericHttpConnector``, ``OpenAPIConnector``, ``GraphQLConnector``,
  ``WebhookListener``, ``MCPBridge``) keep this style because their tool
  surface is data-driven, not method-driven.

:func:`register_connector` picks the right path automatically based on
whether the class carries the ``__maivn_toolset__`` marker.

These helpers do not import ``maivn`` at module load time. They duck-type
the host so ``maivn-tools`` can be imported in environments where the SDK
is not installed (e.g. for static analysis).
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, cast, runtime_checkable

from .protocols import Connector, ToolFactory, ToolProvider

TOOLSET_ATTR = "__maivn_toolset__"
"""Class attribute set by ``maivn.toolset``. Mirrors the SDK constant so we
do not need to import from ``maivn`` to inspect a connector class."""


@runtime_checkable
class _ToolHost(Protocol):
    """Minimum host surface required to register tools.

    Hosts that support the toolset path additionally implement
    ``add_toolset``; the dispatch in :func:`register_connector` checks for
    that method dynamically rather than requiring it on the Protocol.
    """

    def add_tool(self, tool: Any, *args: Any, **kwargs: Any) -> Any: ...


def resolve_connector_tools(
    source: Connector | ToolProvider | Iterable[ToolFactory],
) -> list[ToolFactory]:
    """Resolve a builder-style connector or iterable into a list of factories.

    Toolset-decorated connectors do not pass through this helper; they go
    directly to ``host.add_toolset``. Call this only when inspecting the
    tool surface of a builder connector without registering anything.
    """
    if isinstance(source, Connector):
        return list(source.tools())
    if isinstance(source, ToolProvider):
        return list(source.tools())
    return list(source)


def register_tools(host: _ToolHost, tools: Iterable[ToolFactory]) -> list[Any]:
    """Register an iterable of tool factories on a host via ``add_tool``.

    Used internally by :func:`register_connector` for builder connectors.
    Hosts that need to expose a custom tool list can call this directly.
    """
    if not hasattr(host, "add_tool"):
        raise TypeError(
            "register_tools requires a host with an 'add_tool' method "
            "(e.g. maivn.Agent or maivn.Swarm)."
        )
    registered: list[Any] = []
    for tool in tools:
        registered.append(host.add_tool(tool))
    return registered


def register_connector(host: _ToolHost, connector: object) -> list[Any]:
    """Attach every tool a connector exposes to ``host``.

    Dispatch:

    * If ``type(connector)`` carries the ``__maivn_toolset__`` marker,
      register through ``host.add_toolset(connector)``. The host walks the
      instance and builds one :class:`MethodTool` per ``@toolify``-marked
      method.
    * Otherwise, treat the connector as a builder and call its ``tools()``
      method, registering each returned callable via ``host.add_tool``.

    Returns the list of tool objects the host produced, in the order the
    connector advertised them.
    """
    if hasattr(type(connector), TOOLSET_ATTR):
        add_toolset: Any = getattr(host, "add_toolset", None)
        if add_toolset is None:
            raise TypeError(
                "register_connector received a @toolset connector but the host "
                "does not implement 'add_toolset'. Upgrade to maivn>=0.3.0."
            )
        return list(add_toolset(connector))
    # ``connector`` is a builder-style source here; narrow for the resolver.
    builder = cast("Connector | ToolProvider | Iterable[ToolFactory]", connector)
    return register_tools(host, resolve_connector_tools(builder))


# ``toolset`` aliases ``resolve_connector_tools``; the name collides with
# ``maivn.toolset``, so ``resolve_connector_tools`` is preferred.
toolset = resolve_connector_tools


__all__ = [
    "TOOLSET_ATTR",
    "register_connector",
    "register_tools",
    "resolve_connector_tools",
    "toolset",
]
