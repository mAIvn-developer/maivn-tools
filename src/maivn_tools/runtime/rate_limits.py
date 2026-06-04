"""Rate-limit policy and a portable token-bucket implementation.

Connectors declare their rate-limit expectations through
:class:`RateLimitPolicy`. The :class:`TokenBucket` provides a small in-process
limiter suitable for connectors that need cooperative throttling without
pulling in a third-party dependency.

Hosts that already enforce rate limits at a higher level can ignore these
helpers; they are opt-in.
"""

# pyright: strict

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# MARK: Policy


@dataclass(frozen=True)
class RateLimitPolicy:
    """Declared rate-limit expectations for a tool or connection.

    Attributes:
        requests_per_second: Allowed sustained request rate.
        burst: Maximum number of tokens that can be held at once.
        scope: Free-form scope tag (``"per_connection"``, ``"per_tool"``,
            ``"per_tenant"``).
    """

    requests_per_second: float
    burst: int
    scope: str = "per_connection"

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if self.burst < 1:
            raise ValueError("burst must be at least 1")
        if not self.scope:
            raise ValueError("scope must be a non-empty string")


# MARK: Token bucket


class TokenBucket:
    """A thread-safe token-bucket rate limiter.

    Args:
        policy: The :class:`RateLimitPolicy` to enforce.
        now: Optional time source override, useful in tests.

    Example:

    .. code-block:: python

        bucket = TokenBucket(RateLimitPolicy(requests_per_second=5, burst=10))
        if bucket.try_acquire():
            ...
        else:
            time.sleep(bucket.time_until_available())
    """

    def __init__(
        self,
        policy: RateLimitPolicy,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._now = now
        self._tokens = float(policy.burst)
        self._last = now()
        self._lock = threading.Lock()

    @property
    def policy(self) -> RateLimitPolicy:
        """Return the policy this bucket enforces."""
        return self._policy

    def _refill_locked(self) -> None:
        now = self._now()
        elapsed = max(0.0, now - self._last)
        if elapsed > 0:
            self._tokens = min(
                float(self._policy.burst),
                self._tokens + elapsed * self._policy.requests_per_second,
            )
            self._last = now

    def try_acquire(self, tokens: int = 1) -> bool:
        """Attempt to take ``tokens`` from the bucket without blocking."""
        if tokens < 1:
            raise ValueError("tokens must be at least 1")
        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def time_until_available(self, tokens: int = 1) -> float:
        """Return the seconds until ``tokens`` will be available."""
        if tokens < 1:
            raise ValueError("tokens must be at least 1")
        with self._lock:
            self._refill_locked()
            deficit = tokens - self._tokens
            if deficit <= 0:
                return 0.0
            return deficit / self._policy.requests_per_second

    def available_tokens(self) -> float:
        """Return the number of tokens currently available."""
        with self._lock:
            self._refill_locked()
            return self._tokens
