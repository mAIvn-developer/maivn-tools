"""GraphQL connector.

The connector exposes individual GraphQL operations as callable tools. Each
operation is registered with an explicit permission set so destructive
mutations are visible at registration time rather than discovered at runtime.

The connector does not parse the GraphQL document; it forwards the supplied
query string as-is and lets the server handle validation.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.errors import ProviderError
from ...runtime.http import HttpClient, HttpTransport

# MARK: Operation definition


@dataclass(frozen=True)
class GraphQLOperation:
    """Definition of a single GraphQL operation exposed as a tool."""

    name: str
    query: str
    operation_name: str | None = None
    description: str = ""
    permissions: PermissionSet = field(default_factory=lambda: PermissionSet(PermissionFlag.READ))
    destructive: bool = False
    variables_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("GraphQLOperation.name is required")
        if not self.query:
            raise ValueError("GraphQLOperation.query is required")


# MARK: Connector


class GraphQLConnector:
    """A connector that exposes GraphQL operations as callable tools."""

    def __init__(
        self,
        *,
        metadata: ProviderMetadata,
        endpoint: str,
        operations: Iterable[GraphQLOperation],
        auth: AuthStrategy | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.metadata = metadata
        self.connection = connection
        self._endpoint = endpoint
        self._operations = tuple(operations)
        if not self._operations:
            raise ValueError("GraphQLConnector requires at least one operation")
        self._client = HttpClient(
            transport=transport,
            auth=auth or NoAuth(),
            default_headers=default_headers,
        )

    @property
    def client(self) -> HttpClient:
        """Return the underlying HTTP client."""
        return self._client

    def tools(self) -> list[Any]:
        return [self._build_tool(op) for op in self._operations]

    def _build_tool(self, op: GraphQLOperation) -> Callable[..., Any]:
        allowed: set[str] = set(op.variables_allowlist)

        def tool(variables: Mapping[str, Any] | None = None) -> Any:
            vars_dict: dict[str, Any] = dict(variables or {})
            if allowed:
                unknown = set(vars_dict) - allowed
                if unknown:
                    raise TypeError(
                        f"{op.name}() received unexpected variables: {sorted(unknown)!r}"
                    )
            payload: dict[str, Any] = {"query": op.query, "variables": vars_dict}
            if op.operation_name is not None:
                payload["operationName"] = op.operation_name
            response = self._client.post(self._endpoint, json=payload)
            result: Any = response.json()
            if isinstance(result, dict):
                data_dict = cast(dict[str, Any], result)
                if data_dict.get("errors"):
                    raise ProviderError(
                        f"GraphQL operation {op.name!r} failed",
                        detail={"errors": data_dict["errors"]},
                    )
                if "data" in data_dict:
                    return data_dict["data"]
            return cast(Any, result)

        tool.__name__ = op.name
        tool.__qualname__ = op.name
        tool.__doc__ = op.description or f"Execute GraphQL operation {op.name!r}."
        tool.permissions = op.permissions  # type: ignore[attr-defined]
        tool.destructive = op.destructive  # type: ignore[attr-defined]
        return tool


__all__ = ["GraphQLConnector", "GraphQLOperation"]
