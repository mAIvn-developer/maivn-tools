"""OAuth 2.0 flow helpers.

The Tier 0 :class:`OAuth2BearerAuth` strategy attaches a cached access token
to outgoing requests. The flow layer here is what populates and refreshes
that cache. It supports the four flows connectors need most:

* Authorization code (with optional PKCE)
* Client credentials
* Refresh token
* Device code (helper for headless / CLI installations)

Tokens are kept in memory inside a :class:`TokenCache` and refreshed on
demand. The cache exposes the same :data:`OAuth2TokenProvider` protocol the
bearer-auth strategy expects, so connectors can do::

    flow = OAuth2Flow(...)
    cache = flow.client_credentials_cache(scope="read")
    auth = OAuth2BearerAuth(cache)

without writing any token-management code.
"""

# pyright: strict

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import urlencode

from ..runtime.http import HttpClient, HttpTransport
from .oauth import OAuth2Token


@dataclass(frozen=True)
class OAuth2EndpointConfig:
    """URLs for an OAuth 2.0 authorization server."""

    authorize_url: str = ""
    token_url: str = ""
    device_authorization_url: str | None = None


@dataclass(frozen=True)
class PKCEChallenge:
    """A PKCE verifier/challenge pair."""

    verifier: str
    challenge: str
    method: str = "S256"


@dataclass(frozen=True)
class DeviceCodeGrant:
    """The response from a device-authorization request."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


def generate_pkce_challenge(length: int = 64) -> PKCEChallenge:
    """Return a fresh PKCE verifier / S256 challenge pair."""
    if length < 43 or length > 128:
        raise ValueError("PKCE verifier length must be between 43 and 128")
    verifier = secrets.token_urlsafe(length)[:length]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEChallenge(verifier=verifier, challenge=challenge)


class OAuth2Flow:
    """Coordinator for OAuth 2.0 grants and token exchanges.

    The class is transport-pluggable: tests inject a :class:`MockTransport`
    and assert on the recorded requests. Provider connectors construct the
    flow once and reuse it for repeated token refreshes.

    Args:
        client_id: OAuth client identifier.
        client_secret: OAuth client secret. Optional for public clients
            using PKCE.
        endpoints: :class:`OAuth2EndpointConfig` for the authorization
            server.
        transport: Optional :class:`HttpTransport` override.
        token_auth_style: How to send client credentials at the token
            endpoint. ``"basic"`` (HTTP Basic, default) or ``"body"``.
    """

    def __init__(
        self,
        *,
        client_id: str,
        endpoints: OAuth2EndpointConfig,
        client_secret: str | None = None,
        transport: HttpTransport | None = None,
        token_auth_style: str = "basic",
    ) -> None:
        if not client_id:
            raise ValueError("client_id is required")
        if not endpoints.token_url:
            raise ValueError("OAuth2EndpointConfig.token_url is required")
        if token_auth_style not in {"basic", "body"}:
            raise ValueError("token_auth_style must be 'basic' or 'body'")
        self._client_id = client_id
        self._client_secret = client_secret
        self._endpoints = endpoints
        self._token_auth_style = token_auth_style
        self._http = HttpClient(transport=transport)

    @property
    def endpoints(self) -> OAuth2EndpointConfig:
        return self._endpoints

    # MARK: - Authorization URL builders

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        scope: str | None = None,
        state: str | None = None,
        pkce: PKCEChallenge | None = None,
        extra: Mapping[str, str] | None = None,
    ) -> str:
        """Return the URL the user agent must visit to grant authorization."""
        if not self._endpoints.authorize_url:
            raise ValueError("OAuth2EndpointConfig.authorize_url is required for this flow")
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
        }
        if scope is not None:
            params["scope"] = scope
        if state is not None:
            params["state"] = state
        if pkce is not None:
            params["code_challenge"] = pkce.challenge
            params["code_challenge_method"] = pkce.method
        if extra:
            params.update(extra)
        sep = "&" if "?" in self._endpoints.authorize_url else "?"
        return f"{self._endpoints.authorize_url}{sep}{urlencode(params)}"

    # MARK: - Token exchanges

    def exchange_code(
        self,
        code: str,
        *,
        redirect_uri: str,
        pkce_verifier: str | None = None,
    ) -> OAuth2Token:
        """Exchange an authorization code for an access token."""
        if not code:
            raise ValueError("code must be a non-empty string")
        body: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if pkce_verifier is not None:
            body["code_verifier"] = pkce_verifier
        return self._token_request(body)

    def refresh(self, refresh_token: str, *, scope: str | None = None) -> OAuth2Token:
        """Refresh an access token using a refresh token."""
        if not refresh_token:
            raise ValueError("refresh_token must be a non-empty string")
        body: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if scope is not None:
            body["scope"] = scope
        return self._token_request(body)

    def client_credentials(self, *, scope: str | None = None) -> OAuth2Token:
        """Obtain a token using the client-credentials grant."""
        body: dict[str, str] = {"grant_type": "client_credentials"}
        if scope is not None:
            body["scope"] = scope
        return self._token_request(body)

    def request_device_code(self, *, scope: str | None = None) -> DeviceCodeGrant:
        """Begin a device-code grant.

        The caller is responsible for displaying the user-facing code and
        verification URI, then calling :meth:`poll_device_code` until it
        returns a token.
        """
        if not self._endpoints.device_authorization_url:
            raise ValueError(
                "OAuth2EndpointConfig.device_authorization_url is required for device flow"
            )
        body: dict[str, str] = {"client_id": self._client_id}
        if scope is not None:
            body["scope"] = scope
        headers, form = self._build_request(body)
        response = self._http.post(
            self._endpoints.device_authorization_url,
            data=form.encode("utf-8"),
            headers=headers,
        )
        payload: dict[str, Any] = response.json()
        return DeviceCodeGrant(
            device_code=payload["device_code"],
            user_code=payload["user_code"],
            verification_uri=payload["verification_uri"],
            verification_uri_complete=payload.get("verification_uri_complete"),
            expires_in=int(payload.get("expires_in", 600)),
            interval=int(payload.get("interval", 5)),
        )

    def poll_device_code(self, device_code: str) -> OAuth2Token:
        """Exchange a device code for an access token.

        Callers typically invoke this in a loop honoring the ``interval``
        returned by :meth:`request_device_code`.
        """
        body: dict[str, str] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": self._client_id,
        }
        return self._token_request(body)

    # MARK: - Token cache helpers

    def client_credentials_cache(self, *, scope: str | None = None) -> TokenCache:
        """Return a :class:`TokenCache` that refreshes via client credentials."""
        cache = TokenCache(lambda: self.client_credentials(scope=scope))
        return cache

    def refresh_token_cache(
        self,
        refresh_token: str,
        *,
        scope: str | None = None,
    ) -> TokenCache:
        """Return a cache that refreshes via the supplied refresh token.

        The refresh token is held inside the cache closure; rotating
        providers must replace the cache when a new refresh token is
        issued.
        """
        return TokenCache(lambda: self.refresh(refresh_token, scope=scope))

    # MARK: - Internal

    def _build_request(self, body: dict[str, str]) -> tuple[dict[str, str], str]:
        headers: dict[str, str] = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        merged = dict(body)
        if self._token_auth_style == "basic":
            token = base64.b64encode(
                f"{self._client_id}:{self._client_secret or ''}".encode()
            ).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        else:
            merged["client_id"] = self._client_id
            if self._client_secret is not None:
                merged["client_secret"] = self._client_secret
        return headers, urlencode(merged)

    def _token_request(self, body: dict[str, str]) -> OAuth2Token:
        headers, form = self._build_request(body)
        response = self._http.post(
            self._endpoints.token_url,
            data=form.encode("utf-8"),
            headers=headers,
        )
        raw: object = response.json()
        if not isinstance(raw, dict) or "access_token" not in raw:
            raise ValueError("Token endpoint did not return an access_token")
        payload: dict[str, Any] = cast(dict[str, Any], raw)
        expires_at: datetime | None = None
        if "expires_in" in payload:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(
                seconds=int(payload["expires_in"])
            )
        scopes: tuple[str, ...] = ()
        scope_value = payload.get("scope")
        if isinstance(scope_value, str):
            scopes = tuple(scope_value.split())
        refresh_token: str | None = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            refresh_token = None
        return OAuth2Token(
            access_token=payload["access_token"],
            expires_at=expires_at,
            scopes=scopes,
            refresh_token=refresh_token,
        )


class TokenCache:
    """Thread-safe access-token cache.

    The cache stores a single :class:`OAuth2Token` and a refresh callable.
    On each ``__call__`` it returns the cached token if still valid, or
    invokes the refresh callable.
    """

    def __init__(
        self,
        refresh: Callable[[], OAuth2Token],
        *,
        leeway: timedelta = timedelta(seconds=30),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._refresh = refresh
        self._leeway = leeway
        self._clock = clock
        self._token: OAuth2Token | None = None
        self._lock = threading.Lock()

    def set(self, token: OAuth2Token) -> None:
        """Preload the cache with an existing token."""
        with self._lock:
            self._token = token

    def clear(self) -> None:
        """Drop any cached token."""
        with self._lock:
            self._token = None

    def __call__(self) -> OAuth2Token:
        with self._lock:
            token = self._token
            if token is not None and not _is_expired(token, self._leeway):
                return token
            self._token = self._refresh()
            return self._token


def _is_expired(token: OAuth2Token, leeway: timedelta) -> bool:
    if token.expires_at is None:
        return False
    return datetime.now(tz=timezone.utc) >= token.expires_at - leeway


__all__: list[str] = [
    "DeviceCodeGrant",
    "OAuth2EndpointConfig",
    "OAuth2Flow",
    "PKCEChallenge",
    "TokenCache",
    "generate_pkce_challenge",
]
