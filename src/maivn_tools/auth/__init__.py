"""Authentication strategies and secret resolvers."""

from __future__ import annotations

from .api_key import ApiKeyAuth
from .base import AuthStrategy, NoAuth
from .basic import BasicAuth
from .bearer import BearerTokenAuth
from .connector_auth import (
    REASON_AUTHORIZATION_REQUIRED,
    REASON_GRANT_STALE,
    REASON_SCOPE_UPGRADE_REQUIRED,
    ConnectorAuthRequiredError,
    ConnectorGrantStaleError,
    ConnectorScopeUpgradeRequiredError,
)
from .oauth import OAuth2BearerAuth, OAuth2Token, OAuth2TokenProvider
from .oauth_descriptor import (
    OAuth2ConnectorDescriptor,
    get_oauth_connector_descriptor,
    register_oauth_connector_descriptor,
)
from .oauth_flow import (
    DeviceCodeGrant,
    OAuth2EndpointConfig,
    OAuth2Flow,
    OAuth2ProviderError,
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
    'REASON_AUTHORIZATION_REQUIRED',
    'REASON_GRANT_STALE',
    'REASON_SCOPE_UPGRADE_REQUIRED',
    'ApiKeyAuth',
    'AuthStrategy',
    'BasicAuth',
    'BearerTokenAuth',
    'ChainedSecretResolver',
    'ConnectorAuthRequiredError',
    'ConnectorGrantStaleError',
    'ConnectorScopeUpgradeRequiredError',
    'DeviceCodeGrant',
    'EnvironmentSecretResolver',
    'MissingSecretError',
    'NoAuth',
    'OAuth2BearerAuth',
    'OAuth2ConnectorDescriptor',
    'OAuth2EndpointConfig',
    'OAuth2Flow',
    'OAuth2ProviderError',
    'OAuth2Token',
    'OAuth2TokenProvider',
    'PKCEChallenge',
    'SecretRef',
    'SecretResolver',
    'StaticSecretResolver',
    'TokenCache',
    'generate_pkce_challenge',
    'get_oauth_connector_descriptor',
    'register_oauth_connector_descriptor',
]
