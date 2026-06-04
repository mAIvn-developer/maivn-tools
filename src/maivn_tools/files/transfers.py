"""Bulk transfer contracts.

Connectors that move many files at once should surface progress and outcome
information through :class:`TransferProgress` snapshots and a final
:class:`TransferOutcome`. The contract is provider-agnostic so hosts can
display a uniform progress view across providers.
"""
# pyright: strict

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# MARK: Status enum


class TransferStatus(str, Enum):
    """Lifecycle states for a bulk transfer."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELED = "canceled"


# MARK: Progress / outcome models


@dataclass(frozen=True)
class TransferProgress:
    """A snapshot of an in-flight transfer.

    Attributes:
        transferred: Bytes transferred so far.
        total: Total bytes expected, when known.
        items_completed: Item-level progress count.
        items_total: Total item count, when known.
        message: Optional human-readable status message.
    """

    transferred: int = 0
    total: int | None = None
    items_completed: int = 0
    items_total: int | None = None
    message: str | None = None

    @property
    def fraction(self) -> float | None:
        """Return progress as a fraction in ``[0, 1]`` when ``total`` is known."""
        if self.total is None or self.total <= 0:
            return None
        return min(1.0, max(0.0, self.transferred / self.total))


@dataclass(frozen=True)
class TransferOutcome:
    """Final result of a bulk transfer.

    Attributes:
        status: Terminal :class:`TransferStatus`.
        succeeded: Identifiers of items that completed successfully.
        failed: Mapping of failed item identifier to error message.
        resume_token: Optional opaque token a resumable connector can use to
            pick up where the transfer left off.
        progress: Final progress snapshot.
    """

    status: TransferStatus
    succeeded: tuple[str, ...] = ()
    failed: dict[str, str] = field(default_factory=dict)
    resume_token: str | None = None
    progress: TransferProgress = field(default_factory=TransferProgress)

    @property
    def is_terminal(self) -> bool:
        """Return True when no further work is expected for the transfer."""
        return self.status in {
            TransferStatus.SUCCEEDED,
            TransferStatus.PARTIAL,
            TransferStatus.FAILED,
            TransferStatus.CANCELED,
        }
