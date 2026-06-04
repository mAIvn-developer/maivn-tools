"""HTTP Basic auth strategy."""

# pyright: strict

from __future__ import annotations

from base64 import b64encode
from typing import Any

from ..core.metadata import AuthMode
from .base import AuthStrategy

# MARK: - Basic auth strategy


class BasicAuth(AuthStrategy):
    """Attach HTTP Basic credentials to the ``Authorization`` header.

    Args:
        username: User identifier.
        password: Secret password value.
    """

    mode = AuthMode.BASIC

    def __init__(self, username: str, password: str | None) -> None:
        if not username:
            raise ValueError("username must be a non-empty string")
        if password is None:
            raise ValueError("password must be a string")
        self._username = username
        self._password = password

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        token = b64encode(f"{self._username}:{self._password}".encode()).decode("ascii")
        headers = dict(request.get("headers") or {})
        headers["Authorization"] = f"Basic {token}"
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "username": self._username}
