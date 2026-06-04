"""Auth strategy base classes.

Every connector uses an :class:`AuthStrategy` to attach credentials to an
outgoing request. The strategy interface is intentionally narrow:

* :meth:`AuthStrategy.apply` mutates a request representation in-place.
* :meth:`AuthStrategy.describe` returns a public, secret-free dictionary.

That contract lets the request runtime stay agnostic about credential
material while still surfacing public metadata for audit logs and connection
catalogs.
"""

# pyright: strict

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.metadata import AuthMode

# MARK: - Strategy base


class AuthStrategy(ABC):
    """Base class for credential strategies.

    Subclasses must implement :meth:`apply`. They may override
    :meth:`describe` to expose extra public metadata, but must never include
    secret material in the returned dictionary.
    """

    mode: AuthMode = AuthMode.NONE

    @abstractmethod
    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        """Attach credentials to ``request`` and return the updated mapping.

        ``request`` is a plain dictionary with the same shape used by the
        request runtime: ``method``, ``url``, ``headers``, ``params``,
        ``json``, ``data``. Strategies should only modify the relevant
        sub-mappings (typically ``headers`` or ``params``).
        """

    def describe(self) -> dict[str, Any]:
        """Return public metadata describing this strategy.

        The returned dictionary must be JSON-serializable and must not
        include any secret material.
        """
        return {"mode": self.mode.value}


# MARK: - No-op strategy


class NoAuth(AuthStrategy):
    """No-op strategy for endpoints that do not require credentials."""

    mode = AuthMode.NONE

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        return request
