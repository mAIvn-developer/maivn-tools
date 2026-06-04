"""Mock transport for testing connectors without live network calls.

The :class:`MockTransport` plugs into :class:`HttpClient` in place of the
default transport. Tests configure a queue of canned responses, optionally
keyed by request matchers, and the transport records every request it
receives so the test can assert on it later.

Typical use:

.. code-block:: python

    transport = MockTransport()
    transport.enqueue(json_response({"ok": True}))
    client = HttpClient(base_url="https://api.example.com", transport=transport)

    response = client.get("/ping")
    assert response.json() == {"ok": True}
    assert transport.requests[0].method == "GET"
"""

# pyright: strict

from __future__ import annotations

import json as _json
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..runtime.errors import ConnectorError
from ..runtime.http import HttpRequest, HttpResponse, HttpTransport

# MARK: Response models


@dataclass
class MockResponse:
    """A canned response (or callable factory) to return on a matched request.

    A response may either be a static :class:`HttpResponse` or a callable
    that produces one given the incoming :class:`HttpRequest`. Setting
    ``raise_error`` makes the transport raise the given exception instead of
    returning a response.
    """

    response: HttpResponse | Callable[[HttpRequest], HttpResponse] | None = None
    raise_error: BaseException | None = None
    match: Callable[[HttpRequest], bool] | None = None

    def __post_init__(self) -> None:
        if (self.response is None) == (self.raise_error is None):
            raise ValueError("MockResponse requires exactly one of 'response' or 'raise_error'")

    def matches(self, request: HttpRequest) -> bool:
        return True if self.match is None else self.match(request)

    def resolve(self, request: HttpRequest) -> HttpResponse:
        if self.raise_error is not None:
            raise self.raise_error
        assert self.response is not None
        if callable(self.response):
            return self.response(request)
        return self.response


@dataclass(frozen=True)
class RecordedRequest:
    """A read-only snapshot of a request the transport handled."""

    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any]
    json_body: Any
    data: bytes | None
    timeout: float | None


# MARK: Transport


class MockTransport(HttpTransport):
    """An :class:`HttpTransport` for tests.

    Args:
        responses: Optional iterable of pre-queued :class:`MockResponse`
            entries.
    """

    def __init__(self, responses: list[MockResponse] | None = None) -> None:
        self._queue: deque[MockResponse] = deque(responses or [])
        self._requests: list[RecordedRequest] = []

    @property
    def requests(self) -> list[RecordedRequest]:
        """Return the requests the transport has handled, in order."""
        return list(self._requests)

    def enqueue(self, response: MockResponse | HttpResponse) -> None:
        """Append a response to the queue."""
        if isinstance(response, HttpResponse):
            response = MockResponse(response=response)
        self._queue.append(response)

    def enqueue_error(self, error: ConnectorError) -> None:
        """Append an exception to the queue."""
        self._queue.append(MockResponse(raise_error=error))

    def send(self, request: HttpRequest) -> HttpResponse:
        self._requests.append(
            RecordedRequest(
                method=request.method,
                url=request.url,
                headers=dict(request.headers),
                params=dict(request.params),
                json_body=request.json,
                data=request.data,
                timeout=request.timeout,
            )
        )
        if not self._queue:
            raise AssertionError(
                f"MockTransport has no queued response for {request.method} {request.url}"
            )
        next_response = self._queue.popleft()
        if not next_response.matches(request):
            raise AssertionError(
                f"MockTransport response did not match request: {request.method} {request.url}"
            )
        return next_response.resolve(request)


# MARK: Response builders


def json_response(
    body: Any,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    url: str = "https://example.test/",
) -> HttpResponse:
    """Build a canned JSON response for use in tests."""
    payload = _json.dumps(body).encode("utf-8")
    merged_headers = {"Content-Type": "application/json"}
    if headers:
        merged_headers.update(headers)
    return HttpResponse(status=status, headers=merged_headers, body=payload, url=url)


def text_response(
    body: str,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    url: str = "https://example.test/",
) -> HttpResponse:
    """Build a canned text response for use in tests."""
    merged_headers = {"Content-Type": "text/plain; charset=utf-8"}
    if headers:
        merged_headers.update(headers)
    return HttpResponse(status=status, headers=merged_headers, body=body.encode("utf-8"), url=url)
