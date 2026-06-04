"""Dry-run contract for write-capable tools.

Connector tools that mutate provider state should accept a ``dry_run``
parameter. When ``dry_run=True`` the tool must:

1. Validate input as if the call were real.
2. Compute the change set it would apply.
3. Return a :class:`DryRunOutcome` describing the planned change.
4. Never mutate the provider.

Hosts can use these outcomes to preview destructive operations to users,
gate them behind explicit approval, or feed them into audit pipelines.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar


@dataclass(frozen=True)
class DryRunPlan:
    """Description of a single change a tool would apply.

    Attributes:
        operation: Verb describing the change (``"create"``, ``"update"``,
            ``"delete"``, ``"export"``).
        target: Identifier of the target object (URL, ID, path). Optional for
            operations that create new objects.
        before: Public snapshot of the target prior to the change. Must be
            JSON-serializable. Use ``None`` for create operations.
        after: Public snapshot of the target after the change would be
            applied. Must be JSON-serializable. Use ``None`` for delete
            operations.
        notes: Free-form notes the tool wishes to surface to the caller.
    """

    operation: str
    target: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    notes: str | None = None


@dataclass(frozen=True)
class DryRunOutcome:
    """Result of executing a tool in dry-run mode."""

    tool: str
    plans: tuple[DryRunPlan, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def is_noop(self) -> bool:
        """Return True when the dry run produced no planned changes."""
        return len(self.plans) == 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the outcome."""
        return {
            "tool": self.tool,
            "plans": [
                {
                    "operation": plan.operation,
                    "target": plan.target,
                    "before": plan.before,
                    "after": plan.after,
                    "notes": plan.notes,
                }
                for plan in self.plans
            ],
            "warnings": list(self.warnings),
        }


P = ParamSpec("P")
R = TypeVar("R")


def dry_run_capable(func: Callable[P, R]) -> Callable[P, R]:
    """Marker decorator declaring that a callable honors the dry-run contract.

    The decorator is a no-op at runtime; it only attaches a
    ``__maivn_dry_run_capable__`` attribute so hosts and tests can discover
    which tools support dry runs without executing them.
    """
    setattr(func, "__maivn_dry_run_capable__", True)  # noqa: B010
    return func
