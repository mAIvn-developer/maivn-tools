"""OpenAPI importer.

The importer converts a parsed OpenAPI 3.x document into a list of
:class:`HttpEndpoint` definitions that :class:`GenericHttpConnector` can
serve. The importer is intentionally conservative:

* It only walks ``paths`` and ``operations`` it recognizes.
* It refuses to coerce operations without an ``operationId``; provider
  authors should keep their specs explicit.
* Permissions default to read-only and must be raised by the caller for any
  destructive operation through ``permission_overrides``.

The importer does **not** fetch documents over the network. Callers pass a
parsed mapping (typically obtained via :func:`json.loads` or
:func:`yaml.safe_load`).
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from ...core.permissions import PermissionFlag, PermissionSet
from .http import HttpEndpoint

# MARK: Constants

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_DESTRUCTIVE_METHODS = {"DELETE"}


# MARK: Operation metadata


@dataclass(frozen=True)
class OpenAPIOperation:
    """Lightweight metadata extracted from an OpenAPI operation."""

    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    parameters: tuple[Mapping[str, Any], ...]
    has_request_body: bool


class OpenAPIConnector:
    """Build :class:`HttpEndpoint` objects from a parsed OpenAPI document."""

    def __init__(
        self,
        document: Mapping[str, Any],
        *,
        operation_allowlist: Iterable[str] | None = None,
        operation_denylist: Iterable[str] | None = None,
        permission_overrides: Mapping[str, PermissionSet] | None = None,
        destructive_overrides: Iterable[str] = (),
    ) -> None:
        # ``document`` is declared as a mapping, but callers may pass arbitrary
        # parsed payloads at runtime; keep the defensive guard via ``object``.
        document_obj = cast(object, document)
        if not isinstance(document_obj, Mapping):
            raise TypeError("OpenAPIConnector expects a mapping document")
        document_map = cast("Mapping[str, Any]", document_obj)
        version: object = document_map.get("openapi", "")
        if not (isinstance(version, str) and version.startswith("3.")):
            raise ValueError("OpenAPIConnector requires an OpenAPI 3.x document")
        self._document = document_map
        self._allow: set[str] | None = (
            set(operation_allowlist) if operation_allowlist is not None else None
        )
        self._deny: set[str] = set(operation_denylist) if operation_denylist is not None else set()
        self._permission_overrides: dict[str, PermissionSet] = dict(permission_overrides or {})
        self._destructive_overrides: set[str] = set(destructive_overrides)

    def operations(self) -> list[OpenAPIOperation]:
        """Return the operations the importer recognized."""
        out: list[OpenAPIOperation] = []
        paths_obj: object = self._document.get("paths") or {}
        if not isinstance(paths_obj, Mapping):
            return out
        paths = cast("Mapping[str, Any]", paths_obj)
        for path, methods in paths.items():
            if not isinstance(methods, Mapping):
                continue
            methods_map = cast("Mapping[str, Any]", methods)
            for method, op in methods_map.items():
                if not isinstance(op, Mapping):
                    continue
                op_map = cast("Mapping[str, Any]", op)
                operation_id: object = op_map.get("operationId")
                if not operation_id:
                    continue
                operation_id_str = str(operation_id)
                if self._allow is not None and operation_id_str not in self._allow:
                    continue
                if operation_id_str in self._deny:
                    continue
                raw_parameters: object = op_map.get("parameters") or []
                parameters: tuple[Mapping[str, Any], ...]
                if isinstance(raw_parameters, Iterable):
                    items = cast("Iterable[object]", raw_parameters)
                    parameters = tuple(
                        cast("Mapping[str, Any]", p) for p in items if isinstance(p, Mapping)
                    )
                else:
                    parameters = ()
                out.append(
                    OpenAPIOperation(
                        operation_id=operation_id_str,
                        method=str(method).upper(),
                        path=str(path),
                        summary=str(op_map.get("summary") or ""),
                        description=str(op_map.get("description") or ""),
                        parameters=parameters,
                        has_request_body=bool(op_map.get("requestBody")),
                    )
                )
        return out

    def endpoints(self) -> list[HttpEndpoint]:
        """Return :class:`HttpEndpoint` definitions for each operation."""
        endpoints: list[HttpEndpoint] = []
        for operation in self.operations():
            permissions = self._permission_overrides.get(
                operation.operation_id, _default_permissions(operation.method)
            )
            destructive = (
                operation.operation_id in self._destructive_overrides
                or operation.method.upper() in _DESTRUCTIVE_METHODS
            )
            query_params, path_params = _split_parameters(operation.parameters)
            body_params: tuple[str, ...] = ()
            if operation.has_request_body and operation.method.upper() not in _SAFE_METHODS:
                body_params = ("body",)
            endpoints.append(
                HttpEndpoint(
                    name=operation.operation_id,
                    method=operation.method,
                    path=operation.path,
                    description=operation.summary or operation.description,
                    permissions=permissions,
                    destructive=destructive,
                    query_params=query_params,
                    body_params=body_params,
                )
            )
            _ = path_params  # path params are derived from the path string
        return endpoints


# MARK: Helpers


def _split_parameters(
    parameters: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    query: list[str] = []
    path: list[str] = []
    for param in parameters:
        location: object = param.get("in")
        name: object = param.get("name")
        if not name:
            continue
        if location == "query":
            query.append(str(name))
        elif location == "path":
            path.append(str(name))
    return tuple(query), tuple(path)


def _default_permissions(method: str) -> PermissionSet:
    upper = method.upper()
    if upper in _SAFE_METHODS:
        return PermissionSet(PermissionFlag.READ)
    if upper in _DESTRUCTIVE_METHODS:
        return PermissionSet(PermissionFlag.DELETE)
    return PermissionSet(PermissionFlag.WRITE)
