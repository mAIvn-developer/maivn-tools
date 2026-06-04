"""Stable public exception hierarchy for connector failures.

Provider APIs raise a wide variety of error shapes. The runtime maps them onto
this small hierarchy so callers can write portable error handling without
catching provider-specific exceptions. Each exception preserves a public,
secret-free message and an optional ``detail`` payload.

The hierarchy looks like::

    ConnectorError
    ├── TransportError
    │   └── TimeoutError
    ├── ProviderError
    │   ├── AuthError
    │   ├── PermissionDeniedError
    │   ├── NotFoundError
    │   ├── ValidationError
    │   ├── RateLimitError
    │   └── RetryableError
    └── (anything else)
"""

# pyright: strict

from __future__ import annotations

from typing import Any

# MARK: Exception hierarchy


class ConnectorError(Exception):
    """Base class for all connector-raised errors."""

    def __init__(
        self,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.detail = dict(detail) if detail else {}
        self.status = status

    def public_message(self) -> str:
        """Return the human-readable message, with no secret material."""
        return str(self)


class TransportError(ConnectorError):
    """Network-level failure that prevented a response from being received."""


class TimeoutError(TransportError):  # noqa: A001 - intentional public alias
    """Specialization of :class:`TransportError` for request timeouts."""


class ProviderError(ConnectorError):
    """The provider returned a response that indicates a failure."""


class AuthError(ProviderError):
    """Credentials were missing, invalid, or expired."""


class PermissionDeniedError(ProviderError):
    """The provider rejected the request due to insufficient scope or role."""


class NotFoundError(ProviderError):
    """The provider could not locate the requested resource."""


class ValidationError(ProviderError):
    """The provider rejected the request body or parameters as invalid."""


class RateLimitError(ProviderError):
    """The provider returned a rate-limit response.

    Attributes:
        retry_after_seconds: Number of seconds the provider suggests waiting
            before retrying, when supplied.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        detail: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message, detail=detail, status=status)
        self.retry_after_seconds = retry_after_seconds


class RetryableError(ProviderError):
    """The provider returned a transient error worth retrying."""


# MARK: Status mapping

_STATUS_MAP: dict[int, type[ProviderError]] = {
    400: ValidationError,
    401: AuthError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ValidationError,
    422: ValidationError,
    429: RateLimitError,
}


def normalize_status_error(
    status: int,
    message: str,
    *,
    detail: dict[str, Any] | None = None,
    retry_after_seconds: float | None = None,
) -> ProviderError:
    """Map an HTTP status code onto a stable :class:`ProviderError` subtype.

    Status codes in the 5xx range that are not otherwise mapped become
    :class:`RetryableError`. Everything else falls back to
    :class:`ProviderError`.
    """
    cls = _STATUS_MAP.get(status)
    if cls is None:
        if 500 <= status < 600:
            cls = RetryableError
        else:
            cls = ProviderError
    if cls is RateLimitError:
        return RateLimitError(
            message,
            retry_after_seconds=retry_after_seconds,
            detail=detail,
            status=status,
        )
    return cls(message, detail=detail, status=status)
