"""OAuth authorization contract shared by Google Workspace Gmail consumers."""

# pyright: strict

from __future__ import annotations

from ...auth import (
    OAuth2ConnectorDescriptor,
    OAuth2EndpointConfig,
    register_oauth_connector_descriptor,
)


GMAIL_OAUTH_DESCRIPTOR = register_oauth_connector_descriptor(
    OAuth2ConnectorDescriptor(
        connector_id='gmail',
        provider='google',
        client_id_env='GMAIL_OAUTH_CLIENT_ID',
        client_secret_env='GMAIL_OAUTH_CLIENT_SECRET',
        endpoints=OAuth2EndpointConfig(
            authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
            token_url='https://oauth2.googleapis.com/token',
        ),
        default_scopes=('https://www.googleapis.com/auth/gmail.readonly',),
        authorization_params=(
            ('access_type', 'offline'),
            ('prompt', 'consent'),
        ),
        requires_refresh_token=True,
    )
)


__all__ = ['GMAIL_OAUTH_DESCRIPTOR']
