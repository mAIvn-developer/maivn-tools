"""Generic HTTP connector that exposes configured endpoints as tools.

A :class:`GenericHttpConnector` wraps an :class:`HttpClient` with a list of
declarative :class:`HttpEndpoint` definitions. Each endpoint becomes a
callable tool that can be registered on an Agent or Swarm.

Example:

.. code-block:: python

    from maivn_tools.auth import BearerTokenAuth
    from maivn_tools.connectors.generic_api import GenericHttpConnector, HttpEndpoint
    from maivn_tools.core import ProviderMetadata, AuthMode

    connector = GenericHttpConnector(
        metadata=ProviderMetadata(
            name="example",
            display_name="Example API",
            version="0.1.0",
            auth_modes=(AuthMode.BEARER,),
        ),
        base_url="https://api.example.com",
        auth=BearerTokenAuth("token"),
        endpoints=[
            HttpEndpoint(
                name="get_user",
                method="GET",
                path="/users/{user_id}",
                description="Fetch a user by id.",
            ),
        ],
    )
    agent.add_tool(connector.tools()[0])
"""

# pyright: strict

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_PATH_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


# MARK: Endpoint definition


@dataclass(frozen=True)
class HttpEndpoint:
    """Declarative definition of a single HTTP endpoint.

    Attributes:
        name: Tool name. Used as the registered callable's ``__name__``.
        method: HTTP verb.
        path: URL path. May include ``{name}`` placeholders that are filled
            from the tool's keyword arguments.
        description: Human-readable docstring for the tool.
        permissions: Declared permissions for the tool.
        destructive: Whether this tool may mutate provider state.
        query_params: Parameter names that should be sent as query strings.
            Any keyword argument that is neither a path placeholder nor a
            declared query/body parameter is rejected to keep tool surfaces
            explicit.
        body_params: Parameter names that should be sent in the JSON body.
        static_query: Static query parameters merged into every call.
        static_headers: Static headers merged into every call.
    """

    name: str
    method: str
    path: str
    description: str = ""
    permissions: PermissionSet = field(default_factory=lambda: PermissionSet(PermissionFlag.READ))
    destructive: bool = False
    query_params: tuple[str, ...] = ()
    body_params: tuple[str, ...] = ()
    static_query: dict[str, Any] = field(default_factory=dict)
    static_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("HttpEndpoint.name is required")
        if not self.method:
            raise ValueError("HttpEndpoint.method is required")
        if not self.path:
            raise ValueError("HttpEndpoint.path is required")
        # Ensure body params are only allowed on bodied verbs.
        if self.body_params and self.method.upper() in {"GET", "DELETE", "HEAD"}:
            raise ValueError(
                f"HttpEndpoint {self.name!r}: body_params not allowed on {self.method}"
            )

    @property
    def path_params(self) -> tuple[str, ...]:
        """Return the placeholder names declared in :attr:`path`."""
        return tuple(_PATH_PARAM.findall(self.path))


# MARK: Connector


class GenericHttpConnector:
    """A connector that exposes declared HTTP endpoints as tools."""

    def __init__(
        self,
        *,
        metadata: ProviderMetadata,
        base_url: str,
        endpoints: Iterable[HttpEndpoint],
        auth: AuthStrategy | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.metadata = metadata
        self.connection = connection
        self._endpoints = tuple(endpoints)
        if not self._endpoints:
            raise ValueError("GenericHttpConnector requires at least one endpoint")
        self._client = HttpClient(
            base_url=base_url,
            transport=transport,
            auth=auth or NoAuth(),
            default_headers=default_headers,
        )

    @property
    def client(self) -> HttpClient:
        """Return the underlying :class:`HttpClient`."""
        return self._client

    @property
    def endpoints(self) -> tuple[HttpEndpoint, ...]:
        """Return the endpoints this connector exposes."""
        return self._endpoints

    def tools(self) -> list[Callable[..., Any]]:
        """Return a list of callable tools, one per declared endpoint."""
        return [self._build_tool(endpoint) for endpoint in self._endpoints]

    def _build_tool(self, endpoint: HttpEndpoint) -> Callable[..., Any]:
        allowed = set(endpoint.path_params) | set(endpoint.query_params) | set(endpoint.body_params)

        def tool(**kwargs: Any) -> Any:
            unknown = set(kwargs) - allowed
            if unknown:
                raise TypeError(f"{endpoint.name}() got unexpected arguments: {sorted(unknown)!r}")

            path_values: dict[str, Any] = {}
            for placeholder in endpoint.path_params:
                if placeholder not in kwargs:
                    raise TypeError(
                        f"{endpoint.name}() missing required path argument: {placeholder!r}"
                    )
                path_values[placeholder] = kwargs[placeholder]
            rendered_path = endpoint.path.format(**path_values)

            params = dict(endpoint.static_query)
            for name in endpoint.query_params:
                if name in kwargs:
                    params[name] = kwargs[name]

            body: dict[str, Any] | None = None
            if endpoint.body_params:
                body = {name: kwargs[name] for name in endpoint.body_params if name in kwargs}

            response = self._client.request(
                method=endpoint.method,
                path=rendered_path,
                params=params,
                headers=dict(endpoint.static_headers),
                json=body,
            )
            try:
                return response.json()
            except ValueError:
                return response.text()

        tool.__name__ = endpoint.name
        tool.__qualname__ = endpoint.name
        tool.__doc__ = endpoint.description or (
            f"{endpoint.method} {endpoint.path} on {self.metadata.display_name}"
        )
        tool.permissions = endpoint.permissions  # type: ignore[attr-defined]
        tool.destructive = endpoint.destructive  # type: ignore[attr-defined]
        return tool
