# pyright: strict
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from maivn_tools.auth import BearerTokenAuth
from maivn_tools.runtime import (
    AuthError,
    CursorPaginator,
    DeltaTokenPaginator,
    HttpClient,
    NotFoundError,
    OffsetPaginator,
    PageTokenPaginator,
    PermissionDeniedError,
    ProviderError,
    RateLimitError,
    RateLimitPolicy,
    RetryableError,
    RetryPolicy,
    TokenBucket,
    TransportError,
    ValidationError,
    normalize_status_error,
)
from maivn_tools.testing import MockResponse, MockTransport, json_response, text_response


def _client(transport: MockTransport, **kwargs: Any) -> HttpClient:
    return HttpClient(
        base_url="https://api.example.test",
        transport=transport,
        sleep=lambda _: None,
        **kwargs,
    )


def test_http_client_requires_base_url_for_relative_paths() -> None:
    transport = MockTransport([MockResponse(response=json_response({}))])
    client = HttpClient(transport=transport, sleep=lambda _: None)
    with pytest.raises(ValueError):
        client.get("/relative")


def test_http_client_attaches_auth_and_correlation_headers() -> None:
    transport = MockTransport([MockResponse(response=json_response({"ok": True}))])
    client = _client(transport, auth=BearerTokenAuth("tok"))
    response = client.get("/ping", correlation_id="abc")
    assert response.json() == {"ok": True}
    request = transport.requests[0]
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["X-Request-ID"] == "abc"


def test_http_client_appends_params_and_idempotency() -> None:
    transport = MockTransport([MockResponse(response=text_response("ok"))])
    client = _client(transport)
    client.post("/widgets", params={"a": 1}, json={"x": 2}, idempotency_key="key-1")
    request = transport.requests[0]
    assert request.url.endswith("/widgets")
    assert request.params == {"a": 1}
    assert request.headers["Idempotency-Key"] == "key-1"
    assert request.json_body == {"x": 2}


def test_http_client_retries_on_5xx_then_succeeds() -> None:
    transport = MockTransport()
    transport.enqueue(MockResponse(response=lambda _: json_response({}, status=500)))
    transport.enqueue(json_response({"ok": True}))
    client = _client(
        transport,
        retry=RetryPolicy(max_attempts=2, initial_backoff_seconds=0, jitter=False),
    )
    response = client.get("/ping")
    assert response.json() == {"ok": True}
    assert len(transport.requests) == 2


def test_http_client_raises_after_max_attempts() -> None:
    transport = MockTransport()
    for _ in range(3):
        transport.enqueue(MockResponse(response=lambda _: json_response({}, status=500)))
    client = _client(
        transport,
        retry=RetryPolicy(max_attempts=2, initial_backoff_seconds=0, jitter=False),
    )
    with pytest.raises(RetryableError):
        client.get("/ping")
    assert len(transport.requests) == 2


def test_http_client_normalizes_known_statuses() -> None:
    cases: list[tuple[int, type]] = [
        (400, ValidationError),
        (401, AuthError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (422, ValidationError),
        (429, RateLimitError),
    ]
    for status, exc_type in cases:
        transport = MockTransport(
            [MockResponse(response=lambda _, s=status: json_response({}, status=s))]
        )
        client = _client(
            transport,
            retry=RetryPolicy(max_attempts=1, initial_backoff_seconds=0, jitter=False),
        )
        with pytest.raises(exc_type):
            client.get("/ping")


def test_http_client_honors_retry_after_header() -> None:
    sleeps: list[float] = []
    transport = MockTransport()
    transport.enqueue(
        MockResponse(
            response=lambda _: json_response({}, status=429, headers={"Retry-After": "0.25"})
        )
    )
    transport.enqueue(json_response({"ok": True}))

    client = HttpClient(
        base_url="https://api.example.test",
        transport=transport,
        retry=RetryPolicy(
            max_attempts=2, initial_backoff_seconds=5, jitter=False, max_backoff_seconds=10
        ),
        sleep=sleeps.append,
    )
    client.get("/ping")
    assert sleeps == [0.25]


def test_normalize_status_error_default_5xx_is_retryable() -> None:
    err = normalize_status_error(503, "down")
    assert isinstance(err, RetryableError)
    other = normalize_status_error(418, "teapot")
    assert isinstance(other, ProviderError)
    rate = normalize_status_error(429, "stop", retry_after_seconds=2.0)
    assert isinstance(rate, RateLimitError)
    assert rate.retry_after_seconds == 2.0


def test_retry_policy_validation_and_backoff() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    policy = RetryPolicy(
        max_attempts=4,
        initial_backoff_seconds=1.0,
        backoff_multiplier=2.0,
        max_backoff_seconds=10.0,
        jitter=False,
    )
    assert policy.backoff_seconds(1) == 1.0
    assert policy.backoff_seconds(2) == 2.0
    assert policy.backoff_seconds(3) == 4.0
    assert policy.backoff_seconds(99) == 10.0
    assert policy.backoff_seconds(5, retry_after_seconds=20.0) == 10.0
    assert policy.should_retry(1, TransportError("x")) is True
    assert policy.should_retry(99, TransportError("x")) is False
    assert policy.should_retry(1, ValueError("x")) is False


def test_token_bucket_consumes_and_recovers() -> None:
    times: list[float] = [0.0]

    def now() -> float:
        return times[0]

    bucket = TokenBucket(RateLimitPolicy(requests_per_second=2.0, burst=2), now=now)
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False
    times[0] = 0.5
    assert bucket.try_acquire() is True
    times[0] = 0.5
    assert bucket.try_acquire() is False
    approx = cast(Callable[..., object], cast(object, pytest.approx))
    assert bucket.time_until_available() == approx(0.5, abs=1e-6)


def test_token_bucket_validates_inputs() -> None:
    with pytest.raises(ValueError):
        TokenBucket(RateLimitPolicy(requests_per_second=2, burst=1)).try_acquire(0)


def test_rate_limit_policy_validation() -> None:
    with pytest.raises(ValueError):
        RateLimitPolicy(requests_per_second=0, burst=1)
    with pytest.raises(ValueError):
        RateLimitPolicy(requests_per_second=1, burst=0)
    with pytest.raises(ValueError):
        RateLimitPolicy(requests_per_second=1, burst=1, scope="")


def test_cursor_paginator_walks_until_none() -> None:
    pages: list[tuple[dict[str, Any], Any]] = [
        ({"items": [1, 2]}, "c2"),
        ({"items": [3]}, None),
    ]
    iterator = iter(pages)

    def fetch(_cursor: Any) -> tuple[dict[str, Any], Any]:
        return next(iterator)

    paginator = CursorPaginator(fetch)
    assert list(paginator.iter_items()) == [1, 2, 3]


def test_offset_paginator_stops_on_short_page() -> None:
    pages: list[dict[str, Any]] = [
        {"items": [1, 2]},
        {"items": [3]},
    ]
    iterator = iter(pages)

    def fetch(offset: int, limit: int) -> dict[str, Any]:
        return next(iterator)

    paginator = OffsetPaginator(fetch, page_size=2)
    assert list(paginator.iter_items()) == [1, 2, 3]


def test_offset_paginator_honors_total_key() -> None:
    pages: list[dict[str, Any]] = [
        {"items": [1, 2], "total": 3},
        {"items": [3], "total": 3},
    ]
    iterator = iter(pages)
    paginator = OffsetPaginator(
        lambda offset, limit: next(iterator), page_size=2, total_key="total"
    )
    assert list(paginator.iter_items()) == [1, 2, 3]


def test_page_token_paginator() -> None:
    pages: list[dict[str, Any]] = [
        {"items": [1], "next_page_token": "t"},
        {"items": [2], "next_page_token": ""},
    ]
    iterator = iter(pages)
    paginator = PageTokenPaginator(lambda _: next(iterator))
    assert list(paginator.iter_items()) == [1, 2]


def test_delta_token_paginator_captures_final_token() -> None:
    pages: list[dict[str, Any]] = [
        {"items": [1], "next_link": "/next"},
        {"items": [2], "delta_token": "d-1"},
    ]
    iterator = iter(pages)
    paginator = DeltaTokenPaginator(lambda _: next(iterator))
    assert list(paginator.iter_items()) == [1, 2]
    assert paginator.final_delta_token == "d-1"


def test_mock_transport_records_requests_and_raises_when_empty() -> None:
    transport = MockTransport([MockResponse(response=json_response({}))])
    client = _client(transport)
    client.get("/x")
    assert transport.requests[0].method == "GET"
    with pytest.raises(AssertionError):
        client.get("/x")


def test_mock_response_validates_inputs() -> None:
    with pytest.raises(ValueError):
        MockResponse()
    with pytest.raises(ValueError):
        MockResponse(response=json_response({}), raise_error=ValueError())


def test_mock_response_match_predicate() -> None:
    transport = MockTransport(
        [
            MockResponse(
                response=json_response({"ok": True}),
                match=lambda req: req.method == "POST",
            )
        ]
    )
    client = _client(transport)
    with pytest.raises(AssertionError):
        client.get("/x")
