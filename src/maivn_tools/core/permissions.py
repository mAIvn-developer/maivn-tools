"""Permission model re-export.

The canonical home for ``PermissionFlag`` / ``PermissionSet`` is now
``maivn_shared`` (re-exported as ``from maivn import ...``). This module
re-exports them so existing ``from maivn_tools.core.permissions import ...``
imports keep working for callers who depend on the original layout.
"""

# pyright: strict

from __future__ import annotations

from maivn_shared import (
    PERMISSION_FLAG_NAMES,
    PermissionFlag,
    PermissionSet,
    require_permissions,
)

__all__ = [
    "PERMISSION_FLAG_NAMES",
    "PermissionFlag",
    "PermissionSet",
    "require_permissions",
]
