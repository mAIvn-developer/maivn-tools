"""Provider-owned OAuth authorization descriptors for connectors."""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass

from .oauth_flow import OAuth2EndpointConfig


@dataclass(frozen=True)
class OAuth2ConnectorDescriptor:
    """Public OAuth facts a host needs to authorize one connector.

    Credential values are deliberately absent. The descriptor names the
    environment variables a host resolves from the embedding application.
    """

    connector_id: str
    provider: str
    client_id_env: str
    client_secret_env: str | None
    endpoints: OAuth2EndpointConfig
    default_scopes: tuple[str, ...]
    authorization_params: tuple[tuple[str, str], ...] = ()
    requires_refresh_token: bool = False

    def __post_init__(self) -> None:
        if not self.connector_id.strip():
            raise ValueError('connector_id must be a non-empty string')
        if not self.provider.strip():
            raise ValueError('provider must be a non-empty string')
        if not self.client_id_env.strip():
            raise ValueError('client_id_env must be a non-empty string')
        if self.client_secret_env is not None and not self.client_secret_env.strip():
            raise ValueError('client_secret_env must be None or a non-empty string')
        if not self.default_scopes:
            raise ValueError('default_scopes must contain at least one scope')


_DESCRIPTORS: dict[str, OAuth2ConnectorDescriptor] = {}


def register_oauth_connector_descriptor(
    descriptor: OAuth2ConnectorDescriptor,
) -> OAuth2ConnectorDescriptor:
    """Register ``descriptor`` by connector id and return it unchanged."""
    existing = _DESCRIPTORS.get(descriptor.connector_id)
    if existing is not None and existing != descriptor:
        raise ValueError(f'OAuth descriptor already registered: {descriptor.connector_id}')
    _DESCRIPTORS[descriptor.connector_id] = descriptor
    return descriptor


def get_oauth_connector_descriptor(
    connector_id: str,
) -> OAuth2ConnectorDescriptor | None:
    """Return the registered descriptor for ``connector_id`` when present."""
    return _DESCRIPTORS.get(connector_id)


__all__ = [
    'OAuth2ConnectorDescriptor',
    'get_oauth_connector_descriptor',
    'register_oauth_connector_descriptor',
]
