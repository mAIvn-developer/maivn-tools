"""Public protocols for connectors and tool providers.

These :class:`typing.Protocol` definitions describe the minimum surface a
connector must expose to be usable by ``maivn-tools`` registration helpers
and by hosts that want to inspect connector contents without importing every
provider package.

Concrete connectors can implement these protocols structurally; no inheritance
is required.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from .connections import ConnectionMetadata
from .metadata import ProviderMetadata
from .permissions import PermissionSet

ToolFactory = Callable[..., Any]
"""A zero- or low-argument callable returning an SDK-compatible tool object.

The returned value should be one of the shapes accepted by
``maivn.Agent.add_tool``: a callable, a Pydantic model class, or a prebuilt
SDK tool object.
"""


@runtime_checkable
class ConnectorTool(Protocol):
    """A single tool exposed by a connector.

    The protocol is intentionally minimal so connectors are free to expose
    plain functions, callable classes, or SDK tool objects. Hosts can inspect
    ``permissions`` and ``destructive`` to decide whether the tool is allowed
    to run in the current context.
    """

    name: str
    description: str
    permissions: PermissionSet
    destructive: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class ToolProvider(Protocol):
    """An object that can produce a collection of tool callables."""

    def tools(self) -> list[ToolFactory]:
        """Return the tool factories this provider exposes."""
        ...


@runtime_checkable
class Connector(Protocol):
    """A fully featured connector.

    A connector advertises its provider metadata, exposes a configured
    connection, and yields a list of tools that can be registered on Agents
    or Swarms. Connectors should be cheap to construct: any expensive setup
    work (network calls, credential resolution) should run lazily.
    """

    metadata: ProviderMetadata
    connection: ConnectionMetadata | None

    def tools(self) -> list[ToolFactory]:
        """Return the tool factories this connector exposes."""
        ...
