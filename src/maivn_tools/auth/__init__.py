"""Authentication strategies and secret resolvers."""

from __future__ import annotations

from .api_key import ApiKeyAuth
from .base import AuthStrategy, NoAuth
from .basic import BasicAuth
from .bearer import BearerTokenAuth
from .oauth import OAuth2BearerAuth, OAuth2Token, OAuth2TokenProvider
from .oauth_flow import (
    DeviceCodeGrant,
    OAuth2EndpointConfig,
    OAuth2Flow,
    PKCEChallenge,
    TokenCache,
    generate_pkce_challenge,
)
from .secrets import (
    ChainedSecretResolver,
    EnvironmentSecretResolver,
    MissingSecretError,
    SecretRef,
    SecretResolver,
    StaticSecretResolver,
)

__all__ = [
    "ApiKeyAuth",
    "AuthStrategy",
    "BasicAuth",
    "BearerTokenAuth",
    "ChainedSecretResolver",
    "DeviceCodeGrant",
    "EnvironmentSecretResolver",
    "MissingSecretError",
    "NoAuth",
    "OAuth2BearerAuth",
    "OAuth2EndpointConfig",
    "OAuth2Flow",
    "OAuth2Token",
    "OAuth2TokenProvider",
    "PKCEChallenge",
    "SecretRef",
    "SecretResolver",
    "StaticSecretResolver",
    "TokenCache",
    "generate_pkce_challenge",
]
