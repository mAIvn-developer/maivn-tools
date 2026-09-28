from __future__ import annotations

from maivn_tools.auth import get_oauth_connector_descriptor
from maivn_tools.connectors.google_workspace import GMAIL_OAUTH_DESCRIPTOR


def test_gmail_oauth_descriptor_is_registered_by_connector_id() -> None:
    descriptor = get_oauth_connector_descriptor('gmail')

    assert descriptor is not None
    assert descriptor is GMAIL_OAUTH_DESCRIPTOR
    assert descriptor.connector_id == 'gmail'
    assert descriptor.provider == 'google'
    assert descriptor.client_id_env == 'GMAIL_OAUTH_CLIENT_ID'
    assert descriptor.client_secret_env == 'GMAIL_OAUTH_CLIENT_SECRET'


def test_gmail_oauth_descriptor_carries_the_complete_consent_contract() -> None:
    descriptor = GMAIL_OAUTH_DESCRIPTOR

    assert descriptor.endpoints.authorize_url == 'https://accounts.google.com/o/oauth2/v2/auth'
    assert descriptor.endpoints.token_url == 'https://oauth2.googleapis.com/token'
    assert descriptor.default_scopes == ('https://www.googleapis.com/auth/gmail.readonly',)
    assert dict(descriptor.authorization_params) == {
        'access_type': 'offline',
        'prompt': 'consent',
    }
    assert descriptor.requires_refresh_token is True
