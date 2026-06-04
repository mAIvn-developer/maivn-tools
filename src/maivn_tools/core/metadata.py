"""Provider metadata re-export.

The canonical home for ``AuthMode``, ``ProviderCapability`` and
``ProviderMetadata`` is now ``maivn_shared`` (re-exported as
``from maivn import ...``). This module re-exports them so existing
``from maivn_tools.core.metadata import ...`` imports keep working.
"""

# pyright: strict

from __future__ import annotations

from maivn_shared import AuthMode, ProviderCapability, ProviderMetadata

__all__ = [
    "AuthMode",
    "ProviderCapability",
    "ProviderMetadata",
]
