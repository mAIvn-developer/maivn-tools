# pyright: strict
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from maivn_tools.auth import (
    OAuth2EndpointConfig,
    OAuth2Flow,
    OAuth2Token,
    TokenCache,
    generate_pkce_challenge,
)
from maivn_tools.testing import MockTransport, json_response


def _flow(transport: MockTransport, **overrides: str) -> OAuth2Flow:
    endpoints = OAuth2EndpointConfig(
        authorize_url="https://idp.example.test/oauth/authorize",
        token_url="https://idp.example.test/oauth/token",
        device_authorization_url="https://idp.example.test/oauth/device",
    )
    return OAuth2Flow(
        client_id="client-id",
        client_secret="client-secret",
        endpoints=endpoints,
        transport=transport,
        **overrides,
    )


def test_oauth_flow_validates_inputs() -> None:
    endpoints = OAuth2EndpointConfig(token_url="https://x/token")
    with pytest.raises(ValueError):
        OAuth2Flow(client_id="", endpoints=endpoints)
    with pytest.raises(ValueError):
        OAuth2Flow(client_id="x", endpoints=OAuth2EndpointConfig())
    with pytest.raises(ValueError):
        OAuth2Flow(client_id="x", endpoints=endpoints, token_auth_style="bogus")


def test_authorization_url_includes_required_params() -> None:
    flow = _flow(MockTransport())
    pkce = generate_pkce_challenge()
    url = flow.authorization_url(
        redirect_uri="https://app.example.test/callback",
        scope="read write",
        state="abc",
        pkce=pkce,
        extra={"prompt": "consent"},
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client-id"]
    assert params["redirect_uri"] == ["https://app.example.test/callback"]
    assert params["scope"] == ["read write"]
    assert params["state"] == ["abc"]
    assert params["code_challenge"] == [pkce.challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert params["prompt"] == ["consent"]


def test_generate_pkce_challenge_obeys_length_bounds() -> None:
    with pytest.raises(ValueError):
        generate_pkce_challenge(length=10)
    with pytest.raises(ValueError):
        generate_pkce_challenge(length=200)
    pkce = generate_pkce_challenge(length=64)
    assert len(pkce.verifier) == 64
    assert pkce.method == "S256"


def test_authorization_url_requires_authorize_endpoint() -> None:
    flow = OAuth2Flow(
        client_id="c",
        endpoints=OAuth2EndpointConfig(token_url="https://idp/token"),
    )
    with pytest.raises(ValueError):
        flow.authorization_url(redirect_uri="x")


def test_exchange_code_posts_form_with_basic_auth() -> None:
    transport = MockTransport()
    transport.enqueue(
        json_response(
            {
                "access_token": "at-1",
                "expires_in": 3600,
                "scope": "read write",
            }
        )
    )
    flow = _flow(transport)
    token = flow.exchange_code(
        "code-123",
        redirect_uri="https://app.example.test/callback",
        pkce_verifier="verifier",
    )
    assert token.access_token == "at-1"
    assert token.scopes == ("read", "write")
    assert token.expires_at is not None

    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == "https://idp.example.test/oauth/token"
    assert request.headers["Authorization"].startswith("Basic ")
    body = parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["code-123"]
    assert body["code_verifier"] == ["verifier"]


def test_exchange_code_requires_non_empty_code() -> None:
    flow = _flow(MockTransport())
    with pytest.raises(ValueError):
        flow.exchange_code("", redirect_uri="https://x")


def test_refresh_token_sends_grant_and_optional_scope() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"access_token": "at-2", "expires_in": 60}))
    flow = _flow(transport)
    token = flow.refresh("refresh-xyz", scope="read")
    assert token.access_token == "at-2"
    body = parse_qs(transport.requests[0].data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["refresh-xyz"]
    assert body["scope"] == ["read"]


def test_refresh_token_requires_non_empty() -> None:
    flow = _flow(MockTransport())
    with pytest.raises(ValueError):
        flow.refresh("")


def test_client_credentials_grant() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"access_token": "at-cc"}))
    flow = _flow(transport)
    token = flow.client_credentials(scope="api")
    assert token.access_token == "at-cc"
    assert token.expires_at is None
    body = parse_qs(transport.requests[0].data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["grant_type"] == ["client_credentials"]
    assert body["scope"] == ["api"]


def test_body_auth_style_sends_client_credentials_in_body() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"access_token": "at-body"}))
    flow = _flow(transport, token_auth_style="body")
    flow.client_credentials()
    request = transport.requests[0]
    assert "Authorization" not in request.headers
    body = parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["client_id"] == ["client-id"]
    assert body["client_secret"] == ["client-secret"]


def test_token_request_rejects_payload_without_access_token() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"error": "invalid_request"}))
    flow = _flow(transport)
    with pytest.raises(ValueError):
        flow.client_credentials()


def test_device_code_request_and_polling() -> None:
    transport = MockTransport()
    transport.enqueue(
        json_response(
            {
                "device_code": "dev-1",
                "user_code": "ABCD-1234",
                "verification_uri": "https://idp.example.test/device",
                "verification_uri_complete": "https://idp.example.test/device?user_code=ABCD-1234",
                "expires_in": 900,
                "interval": 10,
            }
        )
    )
    transport.enqueue(json_response({"access_token": "device-at", "expires_in": 60}))
    flow = _flow(transport)
    grant = flow.request_device_code(scope="read")
    assert grant.user_code == "ABCD-1234"
    assert grant.interval == 10
    token = flow.poll_device_code(grant.device_code)
    assert token.access_token == "device-at"


def test_device_code_requires_endpoint() -> None:
    flow = OAuth2Flow(
        client_id="c",
        endpoints=OAuth2EndpointConfig(token_url="https://idp/token"),
    )
    with pytest.raises(ValueError):
        flow.request_device_code()


def test_token_cache_reuses_until_expiry_and_refreshes() -> None:
    calls: list[int] = []

    def refresh() -> OAuth2Token:
        calls.append(1)
        return OAuth2Token(
            access_token=f"tok-{len(calls)}",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=1),
        )

    cache = TokenCache(refresh, leeway=timedelta(seconds=0))
    first = cache()
    second = cache()
    assert first.access_token == second.access_token == "tok-1"
    assert len(calls) == 1

    cache.clear()
    third = cache()
    assert third.access_token == "tok-2"
    assert len(calls) == 2


def test_token_cache_refreshes_when_token_has_expired() -> None:
    state = {"expired": True}

    def refresh() -> OAuth2Token:
        return OAuth2Token(
            access_token="fresh",
            expires_at=(
                datetime.now(tz=timezone.utc) - timedelta(seconds=1)
                if state["expired"]
                else datetime.now(tz=timezone.utc) + timedelta(minutes=5)
            ),
        )

    cache = TokenCache(refresh)
    expired = cache()
    assert expired.access_token == "fresh"
    # Second call refreshes because the cached token is past expiry.
    state["expired"] = False
    second = cache()
    assert second.access_token == "fresh"


def test_client_credentials_cache_helper_invokes_flow() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"access_token": "cc-1", "expires_in": 3600}))
    transport.enqueue(json_response({"access_token": "cc-2", "expires_in": 3600}))
    flow = _flow(transport)
    cache = flow.client_credentials_cache(scope="api")
    first = cache()
    second = cache()
    assert first.access_token == "cc-1"
    assert second.access_token == "cc-1"  # cached
    cache.clear()
    third = cache()
    assert third.access_token == "cc-2"


def test_set_preloads_cache() -> None:
    cache = TokenCache(lambda: OAuth2Token(access_token="should-not-run"))
    preloaded = OAuth2Token(
        access_token="preloaded",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
    )
    cache.set(preloaded)
    assert cache().access_token == "preloaded"
