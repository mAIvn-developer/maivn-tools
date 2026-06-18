"""HTTP transport and high-level client.

The runtime separates two concerns:

* :class:`HttpTransport` is the low-level interface that performs a single
  request and returns the raw response. The default implementation uses
  Python's standard library (:mod:`urllib`) so the package has no required
  third-party dependency. Tests typically supply
  :class:`maivn_tools.testing.MockTransport` instead.

* :class:`HttpClient` wraps a transport with retries, rate limiting,
  authentication, default headers, correlation IDs, and stable error
  normalization. Connector code should depend on the client and never on a
  particular transport implementation.
"""

# pyright: strict

from __future__ import annotations

import json as _json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..auth.base import AuthStrategy, NoAuth
from .errors import (
    ConnectorError,
    RateLimitError,
    TimeoutError,
    TransportError,
    normalize_status_error,
)
from .rate_limits import TokenBucket
from .retries import RetryPolicy

# MARK: Constants

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "maivn-tools/0.1"

# MARK: Request / response models


@dataclass
class HttpRequest:
    """A normalized HTTP request.

    The runtime mutates ``headers`` and ``params`` to attach auth and
    correlation metadata.
    """

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    json: Any = None
    data: bytes | None = None
    timeout: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "headers": dict(self.headers),
            "params": dict(self.params),
            "json": self.json,
            "data": self.data,
            "timeout": self.timeout,
        }


@dataclass
class HttpResponse:
    """A normalized HTTP response."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    def text(self, *, encoding: str = "utf-8", errors: str = "replace") -> str:
        """Return the response body decoded as text."""
        return self.body.decode(encoding, errors=errors)

    def json(self) -> Any:
        """Decode the response body as JSON.

        Raises :class:`ValueError` when the body is empty or not JSON.
        """
        if not self.body:
            raise ValueError("Response body is empty; cannot decode JSON")
        return _json.loads(self.body.decode("utf-8"))

    def header(self, name: str) -> str | None:
        """Return the value of ``name`` using case-insensitive lookup."""
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return None


# MARK: Transports


class HttpTransport(ABC):
    """Abstract HTTP transport.

    Implementations must convert an :class:`HttpRequest` into an
    :class:`HttpResponse`. Network errors must be raised as
    :class:`TransportError` (or :class:`TimeoutError`), not provider-specific
    exceptions.
    """

    @abstractmethod
    def send(self, request: HttpRequest) -> HttpResponse:
        """Send ``request`` and return the response."""


class UrllibTransport(HttpTransport):
    """Default :class:`HttpTransport` backed by :mod:`urllib.request`."""

    def send(self, request: HttpRequest) -> HttpResponse:
        url = request.url
        # SSRF/LFI guard: urllib.request.urlopen also handles ``file:``,
        # ``ftp:`` and ``data:`` URLs. A connector (or a model-influenced URL)
        # pointing at ``file:///etc/passwd`` would otherwise read local files,
        # so reject anything that is not plain HTTP(S) before opening it.
        scheme = urllib.parse.urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(
                f"Unsupported URL scheme {scheme!r}: only 'http' and 'https' are allowed"
            )
        if request.params:
            sep = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(request.params, doseq=True)}"

        body: bytes | None = None
        headers = dict(request.headers)
        if request.json is not None:
            body = _json.dumps(request.json).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif request.data is not None:
            body = request.data

        urllib_request = urllib.request.Request(
            url=url,
            data=body,
            headers=headers,
            method=request.method.upper(),
        )
        timeout = request.timeout if request.timeout is not None else DEFAULT_TIMEOUT_SECONDS

        try:
            with urllib.request.urlopen(urllib_request, timeout=timeout) as resp:
                return HttpResponse(
                    status=resp.getcode(),
                    headers={k: v for k, v in resp.headers.items()},
                    body=resp.read(),
                    url=resp.geturl(),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status=exc.code,
                headers={k: v for k, v in exc.headers.items()} if exc.headers else {},
                body=exc.read() if hasattr(exc, "read") else b"",
                url=url,
            )
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if "timed out" in str(reason).lower():
                raise TimeoutError(f"Request to {url} timed out") from exc
            raise TransportError(f"Request to {url} failed: {reason}") from exc
        except TimeoutError:
            raise
        except OSError as exc:
            raise TransportError(f"Request to {url} failed: {exc}") from exc


# MARK: Client


class HttpClient:
    """Connector-facing HTTP client with retries, rate limits, and auth.

    Args:
        base_url: Optional base URL prepended to relative request paths.
        transport: Transport implementation. Defaults to
            :class:`UrllibTransport`.
        auth: :class:`AuthStrategy` applied to every request.
        retry: :class:`RetryPolicy` controlling retries.
        rate_limit: Optional :class:`TokenBucket` enforcing throttling.
        default_headers: Headers merged into every request. Per-request
            headers win on conflict.
        timeout: Default timeout in seconds for outgoing requests.
        user_agent: ``User-Agent`` to send when no override is supplied.
        sleep: Sleep function. Overridable for tests.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: HttpTransport | None = None,
        auth: AuthStrategy | None = None,
        retry: RetryPolicy | None = None,
        rate_limit: TokenBucket | None = None,
        default_headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._transport = transport or UrllibTransport()
        self._auth = auth or NoAuth()
        self._retry = retry or RetryPolicy()
        self._rate_limit = rate_limit
        self._default_headers = dict(default_headers or {})
        self._default_headers.setdefault("User-Agent", user_agent)
        self._timeout = timeout
        self._sleep = sleep

    @property
    def auth(self) -> AuthStrategy:
        """Return the configured auth strategy."""
        return self._auth

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: bytes | None = None,
        timeout: float | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> HttpResponse:
        """Issue an HTTP request and return the response.

        Raises:
            ProviderError: When the response carries a 4xx or 5xx status the
                runtime maps to a stable provider error.
            TransportError: When the underlying transport fails.
        """
        url = self._resolve_url(path)
        merged_headers: dict[str, str] = dict(self._default_headers)
        merged_headers.update(headers or {})
        merged_headers.setdefault("X-Request-ID", correlation_id or uuid.uuid4().hex)
        if idempotency_key is not None:
            merged_headers.setdefault("Idempotency-Key", idempotency_key)
        request = HttpRequest(
            method=method.upper(),
            url=url,
            headers=merged_headers,
            params=dict(params or {}),
            json=json,
            data=data,
            timeout=timeout if timeout is not None else self._timeout,
        )
        applied = self._auth.apply(request.to_dict())
        request.headers = dict(applied.get("headers") or {})
        request.params = dict(applied.get("params") or {})
        return self._send_with_retry(request)

    def get(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("DELETE", path, **kwargs)

    def _resolve_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if self._base_url is None:
            raise ValueError(
                f"Relative path supplied to HttpClient without a base_url. path={path!r}"
            )
        if path.startswith("/"):
            return f"{self._base_url}{path}"
        return f"{self._base_url}/{path}"

    def _send_with_retry(self, request: HttpRequest) -> HttpResponse:
        attempt = 1
        while True:
            self._await_rate_limit()
            try:
                response = self._transport.send(request)
            except ConnectorError as exc:
                if not self._retry.should_retry(attempt, exc):
                    raise
                self._sleep(self._retry.backoff_seconds(attempt))
                attempt += 1
                continue

            if response.status < 400:
                return response

            error = self._build_error(response)
            if not self._retry.should_retry(attempt, error):
                raise error

            retry_after: float | None = None
            if isinstance(error, RateLimitError):
                retry_after = error.retry_after_seconds
            self._sleep(self._retry.backoff_seconds(attempt, retry_after_seconds=retry_after))
            attempt += 1

    def _await_rate_limit(self) -> None:
        if self._rate_limit is None:
            return
        while not self._rate_limit.try_acquire():
            self._sleep(self._rate_limit.time_until_available())

    @staticmethod
    def _build_error(response: HttpResponse) -> ConnectorError:
        retry_after_header = response.header("Retry-After")
        retry_after_seconds: float | None = None
        if retry_after_header:
            try:
                retry_after_seconds = float(retry_after_header)
            except ValueError:
                retry_after_seconds = None
        message = _summarize_body(response)
        return normalize_status_error(
            response.status,
            message,
            detail={"url": response.url, "headers": dict(response.headers)},
            retry_after_seconds=retry_after_seconds,
        )


# MARK: Helpers


def _summarize_body(response: HttpResponse) -> str:
    snippet: str
    try:
        body = response.text()
    except UnicodeDecodeError:
        body = "<binary body>"
    snippet = body.strip()
    if len(snippet) > 200:
        snippet = snippet[:200] + "..."
    return f"HTTP {response.status} for {response.url}: {snippet or '<empty body>'}"
