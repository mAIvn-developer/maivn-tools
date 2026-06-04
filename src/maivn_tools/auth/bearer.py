"""Bearer-token auth strategy."""

# pyright: strict

from __future__ import annotations

from typing import Any

from ..core.metadata import AuthMode
from .base import AuthStrategy

# MARK: - Bearer-token strategy


class BearerTokenAuth(AuthStrategy):
    """Attach a bearer token via the ``Authorization`` header.

    Args:
        token: The bearer token value. Never logged or returned by
            :meth:`describe`.
        scheme: Authorization scheme to use. Defaults to ``"Bearer"``.
        header: Header to write. Defaults to ``"Authorization"`` and rarely
            needs to be changed.
    """

    mode = AuthMode.BEARER

    def __init__(
        self,
        token: str,
        *,
        scheme: str = "Bearer",
        header: str = "Authorization",
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        if not scheme:
            raise ValueError("scheme must be a non-empty string")
        if not header:
            raise ValueError("header must be a non-empty string")
        self._token = token
        self._scheme = scheme
        self._header = header

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers[self._header] = f"{self._scheme} {self._token}"
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "scheme": self._scheme,
            "header": self._header,
        }
