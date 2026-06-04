"""Retry policy for connector requests.

The policy is intentionally simple. It models exponential backoff with full
jitter and lets callers opt in additional exception types beyond the default
:class:`RetryableError` / :class:`RateLimitError` set.
"""

# pyright: strict

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .errors import ConnectorError, RateLimitError, RetryableError, TransportError

# MARK: Retry policy


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of attempts including the initial call.
            Must be at least 1.
        initial_backoff_seconds: Backoff applied before the second attempt.
        max_backoff_seconds: Upper bound on a single backoff interval.
        backoff_multiplier: Exponential multiplier applied between attempts.
        jitter: Whether to apply full jitter on top of the computed backoff.
        retry_on: Exception types that should trigger a retry.
    """

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retry_on: tuple[type[ConnectorError], ...] = field(
        default=(RetryableError, RateLimitError, TransportError)
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")
        if self.max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be non-negative")
        if self.backoff_multiplier <= 0:
            raise ValueError("backoff_multiplier must be positive")

    def should_retry(self, attempt: int, error: BaseException) -> bool:
        """Return True when ``error`` is retryable and budget remains."""
        if attempt >= self.max_attempts:
            return False
        return isinstance(error, self.retry_on)

    def backoff_seconds(
        self,
        attempt: int,
        *,
        retry_after_seconds: float | None = None,
        rng: random.Random | None = None,
    ) -> float:
        """Return the number of seconds to wait before attempt ``attempt+1``.

        If ``retry_after_seconds`` is set (typically from a provider's
        ``Retry-After`` header) it overrides the computed value.
        """
        if retry_after_seconds is not None and retry_after_seconds >= 0:
            return min(retry_after_seconds, self.max_backoff_seconds)
        exponent = max(0, attempt - 1)
        computed = self.initial_backoff_seconds * (self.backoff_multiplier**exponent)
        capped = min(computed, self.max_backoff_seconds)
        if not self.jitter:
            return capped
        randomizer = rng or random
        return randomizer.uniform(0.0, capped)
