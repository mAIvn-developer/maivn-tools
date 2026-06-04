"""Generic webhook listener that verifies and normalizes provider payloads.

The listener is transport-agnostic: it takes raw headers and a body, runs the
payload through a :class:`WebhookVerifier`, and returns a normalized event
record. Hosts mount it under whichever HTTP framework they prefer.
"""

# pyright: strict

from __future__ import annotations

import json as _json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...events.webhooks import SignatureMismatchError, WebhookVerifier

# MARK: Event record


@dataclass(frozen=True)
class NormalizedWebhookEvent:
    """A verified webhook event after normalization.

    Attributes:
        provider: Provider name from the surrounding connector.
        event_type: Provider event type, when present.
        payload: Parsed payload. Best-effort JSON decoded when the body looks
            like JSON, otherwise stored as raw text.
        headers: Original headers from the request.
        raw: Raw request body bytes.
    """

    provider: str
    event_type: str | None
    payload: Any
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes = b""


# MARK: Listener


class WebhookListener:
    """Verify and normalize webhook events for a single provider.

    Args:
        provider: Provider name recorded on each normalized event.
        verifier: :class:`WebhookVerifier` configured with the provider's
            signing rules.
        event_type_header: Optional header to read for the event type.
        normalize: Optional callable that further normalizes the parsed
            payload. Should return a JSON-serializable structure.
    """

    def __init__(
        self,
        *,
        provider: str,
        verifier: WebhookVerifier,
        event_type_header: str | None = None,
        normalize: Callable[[Any], Any] | None = None,
    ) -> None:
        if not provider:
            raise ValueError("WebhookListener.provider is required")
        self._provider = provider
        self._verifier = verifier
        self._event_type_header = event_type_header
        self._normalize = normalize

    def handle(
        self,
        headers: Mapping[str, str],
        body: bytes,
    ) -> NormalizedWebhookEvent:
        """Verify and normalize a single webhook delivery.

        Raises:
            SignatureMismatchError: When verification fails.
        """
        self._verifier.verify(headers, body)
        try:
            payload: Any = _json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, _json.JSONDecodeError):
            payload = body.decode("latin-1", errors="replace")
        if self._normalize is not None:
            payload = self._normalize(payload)
        event_type: str | None = None
        if self._event_type_header is not None:
            event_type = _lookup_header(headers, self._event_type_header)
        return NormalizedWebhookEvent(
            provider=self._provider,
            event_type=event_type,
            payload=payload,
            headers=dict(headers),
            raw=body,
        )

    def try_handle(
        self,
        headers: Mapping[str, str],
        body: bytes,
    ) -> NormalizedWebhookEvent | None:
        """Return ``None`` instead of raising on verification failure."""
        try:
            return self.handle(headers, body)
        except SignatureMismatchError:
            return None


# MARK: Helpers


def _lookup_header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


__all__ = ["NormalizedWebhookEvent", "WebhookListener"]
