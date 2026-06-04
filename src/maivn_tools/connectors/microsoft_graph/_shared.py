"""Shared helpers for the Microsoft Graph connectors.

The ``annotate(...)`` helper used by the previous closure-based connectors
was retired in the move to ``@toolify``: tools now carry their permission
metadata via the decorator rather than via attribute attachment. Only the
HTTP client helper remains.
"""

# pyright: strict

from __future__ import annotations

from ...auth.oauth import OAuth2BearerAuth, OAuth2Token, OAuth2TokenProvider
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

GRAPH_API_URL = "https://graph.microsoft.com/v1.0"

TokenSource = OAuth2TokenProvider | OAuth2Token | str


# MARK: - Client factory


def make_graph_client(
    token: TokenSource,
    *,
    transport: HttpTransport | None = None,
    base_url: str = GRAPH_API_URL,
) -> HttpClient:
    """Return an :class:`HttpClient` configured for Microsoft Graph."""
    return HttpClient(
        base_url=base_url,
        auth=OAuth2BearerAuth(_normalize_token_provider(token)),
        transport=transport,
        default_headers={"Accept": "application/json"},
    )


# MARK: - Helpers


def _normalize_token_provider(token: TokenSource) -> OAuth2TokenProvider:
    if isinstance(token, str):
        if not token:
            raise ValueError("Token string must be non-empty")
        constant = OAuth2Token(access_token=token)
        return lambda: constant
    if isinstance(token, OAuth2Token):
        captured = token
        return lambda: captured
    if callable(token):
        return token
    raise TypeError("Token must be an OAuth2TokenProvider callable, OAuth2Token, or string")
