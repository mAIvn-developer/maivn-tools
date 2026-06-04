"""OAuth 2.0 bearer-token strategy.

The full OAuth flow (authorization code, PKCE, device code, etc.) lives
outside the strategy itself. Provider connectors are expected to obtain a
token through their preferred flow and then plug it into
:class:`OAuth2BearerAuth` via a :class:`OAuth2TokenProvider`.

The provider can lazily refresh the token without leaking the secret material
to callers; only the resulting access token is attached to requests.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from ..core.metadata import AuthMode
from .base import AuthStrategy

# MARK: - Token model


@dataclass(frozen=True)
class OAuth2Token:
    """An OAuth 2.0 access token plus public lifecycle metadata.

    ``refresh_token`` is present only on the initial authorization-code
    exchange (when the authorization server is configured to return one
    — for Google this requires ``access_type=offline`` plus
    ``prompt=consent``). It is *not* refreshed on every call, so callers
    that persist tokens should carry the refresh token forward across
    runs.
    """

    access_token: str
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()
    refresh_token: str | None = None

    def is_expired(self, *, leeway: timedelta = timedelta(seconds=30)) -> bool:
        """Return True when the token is at or past expiry minus ``leeway``."""
        if self.expires_at is None:
            return False
        return datetime.now(tz=timezone.utc) >= self.expires_at - leeway


OAuth2TokenProvider = Callable[[], OAuth2Token]
"""A zero-argument callable that returns the current OAuth access token.

The provider is responsible for caching and refreshing as appropriate. It
will be invoked once per request, so providers should avoid network calls on
the hot path when the cached token is still valid.
"""


# MARK: - Bearer strategy


class OAuth2BearerAuth(AuthStrategy):
    """Attach a bearer token sourced from an :data:`OAuth2TokenProvider`.

    Args:
        provider: Callable returning the current :class:`OAuth2Token`.
        header: Header name to write. Defaults to ``"Authorization"``.
        scheme: Authorization scheme prefix. Defaults to ``"Bearer"``.
    """

    mode = AuthMode.OAUTH2_AUTH_CODE

    def __init__(
        self,
        provider: OAuth2TokenProvider,
        *,
        header: str = "Authorization",
        scheme: str = "Bearer",
    ) -> None:
        if not callable(provider):
            raise TypeError("provider must be callable")
        self._provider = provider
        self._header = header
        self._scheme = scheme

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        # Widen to object so the runtime guard below stays meaningful even
        # though the provider's declared return type is OAuth2Token.
        token = cast(object, self._provider())
        if not isinstance(token, OAuth2Token):
            raise TypeError("OAuth2 token provider must return OAuth2Token")
        headers = dict(request.get("headers") or {})
        headers[self._header] = f"{self._scheme} {token.access_token}"
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "header": self._header,
            "scheme": self._scheme,
        }
