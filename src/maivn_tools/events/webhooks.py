"""Webhook helpers: signature verification and replay protection.

Provider webhooks vary in signature algorithm and timestamp format. The
helpers here implement the two patterns that cover the majority of providers:

* HMAC-SHA256 signatures with hex or base64 digests.
* Optional timestamp validation to mitigate replay attacks.

Concrete provider connectors should wrap :class:`WebhookVerifier` with the
header names, signature format, and tolerance their provider expects.
"""

# pyright: strict

from __future__ import annotations

import hashlib
import hmac
import time
from base64 import b64decode
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

# MARK: Signature types


class SignatureAlgorithm(str, Enum):
    """Supported HMAC algorithms."""

    HMAC_SHA1 = "sha1"
    HMAC_SHA256 = "sha256"
    HMAC_SHA512 = "sha512"


class SignatureMismatchError(ValueError):
    """Raised when a webhook signature is missing, malformed, or incorrect."""


# MARK: Algorithm registry

# ``hashlib._Hash`` is the only stdlib type naming a hash object, but it is
# module-private; we type the constructors as ``Callable[[], Any]`` (which is
# what ``hmac.new`` accepts for ``digestmod``) to avoid the private reference.
_ALGORITHM_TO_HASH: dict[SignatureAlgorithm, Callable[[], Any]] = {
    SignatureAlgorithm.HMAC_SHA1: hashlib.sha1,
    SignatureAlgorithm.HMAC_SHA256: hashlib.sha256,
    SignatureAlgorithm.HMAC_SHA512: hashlib.sha512,
}


def verify_hmac_signature(
    secret: str | bytes,
    payload: bytes,
    signature: str,
    *,
    algorithm: SignatureAlgorithm = SignatureAlgorithm.HMAC_SHA256,
    encoding: str = "hex",
) -> None:
    """Verify a webhook signature against ``payload``.

    Args:
        secret: Shared secret used to sign the payload.
        payload: Raw request body bytes.
        signature: Signature value supplied by the provider.
        algorithm: HMAC algorithm used by the provider.
        encoding: Digest encoding (``"hex"`` or ``"base64"``).

    Raises:
        SignatureMismatchError: When the signature does not match.
    """
    if not signature:
        raise SignatureMismatchError("Signature header is empty")
    hasher = _ALGORITHM_TO_HASH[algorithm]
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    mac = hmac.new(key, payload, hasher)
    if encoding == "hex":
        expected = mac.hexdigest()
        provided = signature.strip()
    elif encoding == "base64":
        expected = mac.digest()
        try:
            provided_bytes = b64decode(signature.strip(), validate=True)
        except Exception as exc:  # noqa: BLE001 - we re-raise as a stable type
            raise SignatureMismatchError("Signature is not valid base64") from exc
        if not hmac.compare_digest(expected, provided_bytes):
            raise SignatureMismatchError("Signature does not match payload")
        return
    else:
        raise ValueError(f"Unsupported signature encoding: {encoding!r}")
    if not hmac.compare_digest(expected, provided):
        raise SignatureMismatchError("Signature does not match payload")


@dataclass(frozen=True)
class WebhookVerifier:
    """Verifies provider webhook payloads against a shared secret.

    Args:
        secret: Shared signing secret.
        signature_header: Header containing the signature value.
        algorithm: HMAC algorithm used by the provider.
        encoding: Digest encoding (``"hex"`` or ``"base64"``).
        timestamp_header: Optional header containing a Unix timestamp.
        tolerance_seconds: Maximum allowed clock skew when
            ``timestamp_header`` is provided.
    """

    secret: str
    signature_header: str = "X-Maivn-Signature"
    algorithm: SignatureAlgorithm = SignatureAlgorithm.HMAC_SHA256
    encoding: str = "hex"
    timestamp_header: str | None = None
    tolerance_seconds: int = 300

    def verify(
        self,
        headers: Mapping[str, str],
        payload: bytes,
        *,
        now: float | None = None,
    ) -> None:
        """Verify ``payload`` using the supplied headers.

        Raises:
            SignatureMismatchError: When the signature is missing or wrong.
            ValueError: When timestamp validation fails (replay protection).
        """
        signature = _lookup_header(headers, self.signature_header)
        if signature is None:
            raise SignatureMismatchError(f"Missing signature header {self.signature_header!r}")

        if self.timestamp_header is not None:
            ts_value = _lookup_header(headers, self.timestamp_header)
            if ts_value is None:
                raise SignatureMismatchError(f"Missing timestamp header {self.timestamp_header!r}")
            try:
                ts = float(ts_value)
            except ValueError as exc:
                raise SignatureMismatchError("Timestamp header is not numeric") from exc
            reference = now if now is not None else time.time()
            if abs(reference - ts) > self.tolerance_seconds:
                raise SignatureMismatchError("Timestamp outside allowed tolerance; possible replay")

        verify_hmac_signature(
            self.secret,
            payload,
            signature,
            algorithm=self.algorithm,
            encoding=self.encoding,
        )


def _lookup_header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None
