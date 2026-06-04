"""API-key auth strategy."""

# pyright: strict

from __future__ import annotations

from typing import Any

from ..core.metadata import AuthMode
from .base import AuthStrategy

# MARK: - API-key strategy


class ApiKeyAuth(AuthStrategy):
    """Attach an API key to either a header or a query parameter.

    Args:
        api_key: The secret key value. Never logged or returned by
            :meth:`describe`.
        header: Header name to set, when authenticating via header.
        query_param: Query parameter name to set, when authenticating via URL.
        prefix: Optional prefix to prepend to the key (for providers that
            require ``"Token <key>"``).

    Exactly one of ``header`` or ``query_param`` must be provided.
    """

    mode = AuthMode.API_KEY

    def __init__(
        self,
        api_key: str,
        *,
        header: str | None = None,
        query_param: str | None = None,
        prefix: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        if (header is None) == (query_param is None):
            raise ValueError("Specify exactly one of 'header' or 'query_param'")
        self._api_key = api_key
        self._header = header
        self._query_param = query_param
        self._prefix = prefix

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        value = f"{self._prefix} {self._api_key}" if self._prefix else self._api_key
        if self._header is not None:
            headers = dict(request.get("headers") or {})
            headers[self._header] = value
            request["headers"] = headers
        else:
            params = dict(request.get("params") or {})
            assert self._query_param is not None
            params[self._query_param] = value
            request["params"] = params
        return request

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "location": "header" if self._header else "query",
            "name": self._header or self._query_param,
            "has_prefix": self._prefix is not None,
        }
