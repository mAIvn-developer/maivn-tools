"""Connection metadata models.

A :class:`ConnectionMetadata` describes a configured link between a connector
and a provider account or tenant. It records the public attributes a host
needs to display, audit, or rotate the connection, but never the underlying
secret material.

Secrets, refresh tokens, and other credential payloads belong in the
auth-strategy / secret-resolver layer
(:mod:`maivn_tools.auth`). The connection metadata only carries hashed or
redacted references to those values, plus rotation metadata that is safe to
expose.
"""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .metadata import AuthMode


class ConnectionStatus(str, Enum):
    """Lifecycle states for a connection."""

    UNCONFIGURED = "unconfigured"
    PENDING_AUTH = "pending_auth"
    ACTIVE = "active"
    DEGRADED = "degraded"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


@dataclass(frozen=True)
class TokenMetadata:
    """Public metadata about an issued credential.

    No secret material is stored here. ``fingerprint`` is a short, irreversible
    identifier (for example, the first eight characters of a SHA-256 hash of
    the token) suitable for log correlation.
    """

    fingerprint: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()
    refreshable: bool = False

    def is_expired(self, *, now: datetime | None = None) -> bool:
        """Return True when ``expires_at`` is in the past."""
        if self.expires_at is None:
            return False
        reference = now or datetime.now(tz=timezone.utc)
        return reference >= self.expires_at


@dataclass(frozen=True)
class ConnectionHealth:
    """Latest health signal observed for a connection."""

    status: ConnectionStatus = ConnectionStatus.UNCONFIGURED
    checked_at: datetime | None = None
    detail: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class ConnectionMetadata:
    """Identity and lifecycle metadata for a configured connection.

    Attributes:
        connection_id: Stable identifier assigned by the host.
        provider: Provider name from :class:`ProviderMetadata`.
        account: Provider-side account or user identifier, when known.
        tenant: Provider-side tenant or workspace identifier, when known.
        auth_mode: Auth flow used to establish this connection.
        scopes: Scopes granted to this connection.
        token: Public token metadata; never the secret itself.
        health: Latest health snapshot.
        labels: Arbitrary host-side labels (``"env=prod"``, ``"owner=team"``).
        created_at: Time the connection was first configured.
        updated_at: Time the connection was last modified.
    """

    connection_id: str
    provider: str
    auth_mode: AuthMode = AuthMode.NONE
    account: str | None = None
    tenant: str | None = None
    scopes: tuple[str, ...] = ()
    token: TokenMetadata | None = None
    health: ConnectionHealth = field(default_factory=ConnectionHealth)
    labels: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("ConnectionMetadata.connection_id is required")
        if not self.provider:
            raise ValueError("ConnectionMetadata.provider is required")

    def is_active(self) -> bool:
        """Return True when the connection is in the ACTIVE status."""
        return self.health.status is ConnectionStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable, secret-free dictionary view."""
        token_view: dict[str, Any] | None = None
        if self.token is not None:
            token_view = {
                "fingerprint": self.token.fingerprint,
                "issued_at": _isoformat(self.token.issued_at),
                "expires_at": _isoformat(self.token.expires_at),
                "scopes": list(self.token.scopes),
                "refreshable": self.token.refreshable,
            }
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "auth_mode": self.auth_mode.value,
            "account": self.account,
            "tenant": self.tenant,
            "scopes": list(self.scopes),
            "token": token_view,
            "health": {
                "status": self.health.status.value,
                "checked_at": _isoformat(self.health.checked_at),
                "detail": self.health.detail,
                "latency_ms": self.health.latency_ms,
            },
            "labels": dict(self.labels),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
