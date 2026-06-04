# pyright: strict
from __future__ import annotations

import hashlib
import hmac
import time
from base64 import b64encode

import pytest

from maivn_tools.events import (
    AuditEvent,
    AuditEventKind,
    AuditEventSeverity,
    InMemoryAuditSink,
    SignatureAlgorithm,
    SignatureMismatchError,
    WebhookVerifier,
    verify_hmac_signature,
)


def test_audit_event_requires_provider_and_tool() -> None:
    with pytest.raises(ValueError):
        AuditEvent(kind=AuditEventKind.READ, provider="", tool="x")
    with pytest.raises(ValueError):
        AuditEvent(kind=AuditEventKind.READ, provider="x", tool="")


def test_audit_event_to_dict_round_trip() -> None:
    event = AuditEvent(
        kind=AuditEventKind.WRITE,
        provider="example",
        tool="tool",
        connection_id="c1",
        actor="user-1",
        target="t1",
        severity=AuditEventSeverity.NOTICE,
        detail={"a": 1},
    )
    payload = event.to_dict()
    assert payload["kind"] == "write"
    assert payload["severity"] == "notice"
    assert payload["detail"] == {"a": 1}
    assert "timestamp" in payload


def test_in_memory_audit_sink_collects_and_clears() -> None:
    sink = InMemoryAuditSink()
    event = AuditEvent(kind=AuditEventKind.READ, provider="x", tool="t")
    sink.emit(event)
    assert sink.events == [event]
    sink.clear()
    assert sink.events == []


def _sign(secret: str, payload: bytes, algorithm: SignatureAlgorithm, encoding: str) -> str:
    hashers = {
        SignatureAlgorithm.HMAC_SHA1: hashlib.sha1,
        SignatureAlgorithm.HMAC_SHA256: hashlib.sha256,
        SignatureAlgorithm.HMAC_SHA512: hashlib.sha512,
    }
    mac = hmac.new(secret.encode("utf-8"), payload, hashers[algorithm])
    if encoding == "hex":
        return mac.hexdigest()
    return b64encode(mac.digest()).decode("ascii")


def test_verify_hmac_signature_hex_and_base64_paths() -> None:
    payload = b"data"
    for algorithm in SignatureAlgorithm:
        for encoding in ("hex", "base64"):
            sig = _sign("secret", payload, algorithm, encoding)
            verify_hmac_signature("secret", payload, sig, algorithm=algorithm, encoding=encoding)


def test_verify_hmac_signature_rejects_missing_or_wrong() -> None:
    with pytest.raises(SignatureMismatchError):
        verify_hmac_signature("secret", b"data", "")
    with pytest.raises(SignatureMismatchError):
        verify_hmac_signature("secret", b"data", "deadbeef")
    with pytest.raises(SignatureMismatchError):
        verify_hmac_signature("secret", b"data", "not-base64!", encoding="base64")


def test_verify_hmac_signature_unsupported_encoding() -> None:
    with pytest.raises(ValueError):
        verify_hmac_signature("s", b"x", "sig", encoding="hexadecimal")


def test_webhook_verifier_basic_verification() -> None:
    payload = b"hello"
    sig = _sign("s", payload, SignatureAlgorithm.HMAC_SHA256, "hex")
    verifier = WebhookVerifier(secret="s", signature_header="X-Sig")
    verifier.verify({"X-Sig": sig}, payload)


def test_webhook_verifier_missing_signature_header() -> None:
    verifier = WebhookVerifier(secret="s", signature_header="X-Sig")
    with pytest.raises(SignatureMismatchError):
        verifier.verify({}, b"hello")


def test_webhook_verifier_enforces_timestamp_tolerance() -> None:
    payload = b"hello"
    sig = _sign("s", payload, SignatureAlgorithm.HMAC_SHA256, "hex")
    verifier = WebhookVerifier(
        secret="s",
        signature_header="X-Sig",
        timestamp_header="X-Ts",
        tolerance_seconds=10,
    )
    now = time.time()
    verifier.verify({"X-Sig": sig, "X-Ts": str(now)}, payload, now=now)
    with pytest.raises(SignatureMismatchError):
        verifier.verify({"X-Sig": sig, "X-Ts": str(now - 999)}, payload, now=now)
    with pytest.raises(SignatureMismatchError):
        verifier.verify({"X-Sig": sig, "X-Ts": "not-a-number"}, payload, now=now)
    with pytest.raises(SignatureMismatchError):
        verifier.verify({"X-Sig": sig}, payload, now=now)
