"""Shared helpers for the Google Workspace connectors.

The ``annotate(...)`` helper used by the previous closure-based connectors
was retired in the move to ``@toolify``: tools now carry their permission
metadata via the decorator rather than via attribute attachment. Only the
token-normalization helpers remain.
"""

# pyright: strict

from __future__ import annotations

from typing import cast

from ...auth.oauth import OAuth2BearerAuth, OAuth2Token, OAuth2TokenProvider

# MARK: Types

TokenSource = OAuth2TokenProvider | OAuth2Token | str


# MARK: Helpers


def normalize_token_provider(token: object) -> OAuth2TokenProvider:
    """Accept a callable provider, a static :class:`OAuth2Token`, or a string.

    Typed as ``object`` so the runtime type guard below is retained: callers
    pass a :data:`TokenSource`, but invalid runtime input is rejected with a
    ``TypeError`` rather than silently mis-handled.
    """
    if isinstance(token, OAuth2Token):
        static_token = token
        return lambda: static_token
    if isinstance(token, str):
        if not token:
            raise ValueError("Token string must be non-empty")
        immutable_token = OAuth2Token(access_token=token)
        return lambda: immutable_token
    if callable(token):
        return cast(OAuth2TokenProvider, token)
    raise TypeError("Token must be an OAuth2TokenProvider callable, OAuth2Token, or string")


def make_bearer_auth(token: TokenSource) -> OAuth2BearerAuth:
    """Return an OAuth bearer strategy backed by ``token``."""
    return OAuth2BearerAuth(normalize_token_provider(token))
