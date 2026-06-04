"""AWS Signature Version 4 auth strategy."""

# pyright: strict

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import urllib.parse
from typing import Any, cast

from ...auth.base import AuthStrategy
from ...core.metadata import AuthMode

# MARK: Constants

_UNSIGNED = "UNSIGNED-PAYLOAD"


# MARK: Helpers


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


# MARK: Auth strategy


class SigV4Auth(AuthStrategy):
    """Sign each request with AWS SigV4 (Authorization header)."""

    mode = AuthMode.API_KEY

    def __init__(
        self,
        *,
        access_key: str,
        secret_key: str,
        region: str,
        service: str,
        session_token: str | None = None,
        sign_payload: bool = True,
    ) -> None:
        if not access_key or not secret_key or not region or not service:
            raise ValueError("access_key, secret_key, region, and service are required")
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._service = service
        self._session_token = session_token
        self._sign_payload = sign_payload

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        method = (request.get("method") or "GET").upper()
        url = request.get("url") or ""
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        params: dict[str, Any] = dict(request.get("params") or {})
        body: Any = request.get("data") or b""
        json_body: Any = request.get("json")
        if json_body is not None and not body:
            import json as _json

            body = _json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        if isinstance(body, str):
            body = body.encode("utf-8")
        elif body is None:
            body = b""

        now = _dt.datetime.now(_dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        headers: dict[str, Any] = dict(request.get("headers") or {})
        headers["host"] = host
        headers["x-amz-date"] = amz_date
        if self._session_token:
            headers["x-amz-security-token"] = self._session_token
        if self._sign_payload:
            payload_hash = hashlib.sha256(body).hexdigest()
        else:
            payload_hash = _UNSIGNED
        headers["x-amz-content-sha256"] = payload_hash

        # Canonical query string
        flat: list[tuple[str, str]] = []
        for k, v in params.items():
            if isinstance(v, (list, tuple)):
                seq = cast("tuple[Any, ...] | list[Any]", v)
                for item in seq:
                    flat.append((k, str(item)))
            else:
                flat.append((k, str(v)))
        flat.sort()
        canonical_qs = urllib.parse.urlencode(flat, quote_via=urllib.parse.quote)

        # Canonical headers (lowercased keys, trimmed values, sorted)
        sortable: list[tuple[str, str]] = sorted(
            (k.lower(), str(v).strip()) for k, v in headers.items()
        )
        canonical_headers = "".join(f"{k}:{v}\n" for k, v in sortable)
        signed_headers = ";".join(k for k, _ in sortable)

        canonical_path = urllib.parse.quote(path, safe="/-_.~")
        canonical_request = "\n".join(
            [
                method,
                canonical_path,
                canonical_qs,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        algo = "AWS4-HMAC-SHA256"
        scope = f"{date_stamp}/{self._region}/{self._service}/aws4_request"
        string_to_sign = "\n".join(
            [
                algo,
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            _signing_key(self._secret_key, date_stamp, self._region, self._service),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["Authorization"] = (
            f"{algo} Credential={self._access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "scheme": "aws-sigv4",
            "region": self._region,
            "service": self._service,
        }
