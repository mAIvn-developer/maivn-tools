"""Connector request runtime: transport, retries, rate limits, pagination, errors."""

from __future__ import annotations

from .errors import (
    AuthError,
    ConnectorError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    RateLimitError,
    RetryableError,
    TimeoutError,
    TransportError,
    ValidationError,
    normalize_status_error,
)
from .http import (
    HttpClient,
    HttpRequest,
    HttpResponse,
    HttpTransport,
)
from .pagination import (
    CursorPaginator,
    DeltaTokenPaginator,
    OffsetPaginator,
    PageTokenPaginator,
    Paginator,
)
from .rate_limits import RateLimitPolicy, TokenBucket
from .retries import RetryPolicy

__all__ = [
    "AuthError",
    "ConnectorError",
    "CursorPaginator",
    "DeltaTokenPaginator",
    "HttpClient",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "NotFoundError",
    "OffsetPaginator",
    "PageTokenPaginator",
    "Paginator",
    "PermissionDeniedError",
    "ProviderError",
    "RateLimitError",
    "RateLimitPolicy",
    "RetryPolicy",
    "RetryableError",
    "TimeoutError",
    "TokenBucket",
    "TransportError",
    "ValidationError",
    "normalize_status_error",
]
