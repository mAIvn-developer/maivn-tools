"""Audit event model and pluggable sinks.

Connector tools emit audit events to record the operations they perform so
hosts can produce compliance trails. The model is intentionally narrow:

* :class:`AuditEvent` is an immutable dataclass.
* :class:`AuditSink` is an abstract receiver. Hosts can plug in any
  forwarder (file, syslog, OpenTelemetry, Supabase, etc.).
* :class:`InMemoryAuditSink` is a tested in-memory implementation suitable
  for tests and local development.
"""

# pyright: strict

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# MARK: Enums


class AuditEventKind(str, Enum):
    """Normalized event types for connector activity."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXPORT = "export"
    IMPORT = "import"
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    CREDENTIAL_ACCESS = "credential.access"
    CREDENTIAL_ROTATE = "credential.rotate"
    ADMIN = "admin"
    DRY_RUN = "dry_run"


class AuditEventSeverity(str, Enum):
    """Severity levels surfaced by audit events."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"


# MARK: Event model


@dataclass(frozen=True)
class AuditEvent:
    """An immutable audit record.

    Attributes:
        kind: Normalized event type.
        provider: Provider name from :class:`ProviderMetadata`.
        tool: Tool name that emitted the event.
        connection_id: Optional connection identifier.
        actor: Optional identifier of the principal that triggered the event.
        target: Optional target identifier (URL, ID, path).
        severity: Severity level.
        timestamp: Event time, defaulting to ``datetime.now(timezone.utc)``.
        detail: Free-form, JSON-serializable detail map. Must not contain
            secrets or other sensitive material.
    """

    kind: AuditEventKind
    provider: str
    tool: str
    connection_id: str | None = None
    actor: str | None = None
    target: str | None = None
    severity: AuditEventSeverity = AuditEventSeverity.INFO
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("AuditEvent.provider is required")
        if not self.tool:
            raise ValueError("AuditEvent.tool is required")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the event."""
        return {
            "kind": self.kind.value,
            "provider": self.provider,
            "tool": self.tool,
            "connection_id": self.connection_id,
            "actor": self.actor,
            "target": self.target,
            "severity": self.severity.value,
            "timestamp": self.timestamp.isoformat(),
            "detail": dict(self.detail),
        }


# MARK: Sinks


class AuditSink(ABC):
    """Receiver for :class:`AuditEvent` instances."""

    @abstractmethod
    def emit(self, event: AuditEvent) -> None:
        """Record ``event``. Implementations must be exception-safe."""


class InMemoryAuditSink(AuditSink):
    """Audit sink that retains events in a list.

    Intended for tests and local development. Production callers should plug
    in a sink that forwards to their preferred audit pipeline.
    """

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        """Drop all retained events."""
        self.events.clear()
