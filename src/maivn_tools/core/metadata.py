"""Provider metadata owned by ``maivn_tools``."""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

type JsonObject = dict[str, object]


class AuthMode(StrEnum):
    """Supported authentication flows for a toolset or provider."""

    NONE = 'none'
    API_KEY = 'api_key'
    BEARER = 'bearer'
    BASIC = 'basic'
    OAUTH2_AUTH_CODE = 'oauth2_auth_code'
    OAUTH2_PKCE = 'oauth2_pkce'
    OAUTH2_CLIENT_CREDENTIALS = 'oauth2_client_credentials'
    OAUTH2_DEVICE_CODE = 'oauth2_device_code'
    SERVICE_ACCOUNT = 'service_account'
    CUSTOM = 'custom'


class ProviderCapability(StrEnum):
    """Standard capability flags a toolset may advertise."""

    READ = 'read'
    WRITE = 'write'
    SEARCH = 'search'
    EXPORT = 'export'
    IMPORT = 'import'
    WEBHOOKS = 'webhooks'
    STREAMING = 'streaming'
    BULK = 'bulk'
    DRY_RUN = 'dry_run'
    PAGINATION = 'pagination'
    RATE_LIMITED = 'rate_limited'


@dataclass(frozen=True)
class ProviderMetadata:
    """Static metadata describing a toolset or provider."""

    name: str
    display_name: str
    version: str
    description: str = ''
    auth_modes: tuple[AuthMode, ...] = ()
    scopes: dict[str, str] = field(default_factory=dict)
    capabilities: frozenset[ProviderCapability] = field(default_factory=frozenset)
    documentation_url: str | None = None
    homepage_url: str | None = None
    tags: tuple[str, ...] = ()
    extras: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate required catalog identity fields."""
        if not self.name or not self.display_name or not self.version:
            message = 'ProviderMetadata requires name, display_name, and version'
            raise ValueError(message)

    def supports_auth(self, mode: AuthMode) -> bool:
        """Return True when this provider supports ``mode``."""
        return mode in self.auth_modes

    def has_capability(self, capability: ProviderCapability) -> bool:
        """Return True when this provider advertises ``capability``."""
        return capability in self.capabilities

    def to_dict(self) -> JsonObject:
        """Return a JSON-compatible metadata representation."""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'version': self.version,
            'description': self.description,
            'auth_modes': [mode.value for mode in self.auth_modes],
            'scopes': dict(self.scopes),
            'capabilities': sorted(capability.value for capability in self.capabilities),
            'documentation_url': self.documentation_url,
            'homepage_url': self.homepage_url,
            'tags': list(self.tags),
            'extras': dict(self.extras),
        }


__all__ = [
    'AuthMode',
    'JsonObject',
    'ProviderCapability',
    'ProviderMetadata',
]
