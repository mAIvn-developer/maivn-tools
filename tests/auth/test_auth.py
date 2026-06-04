# pyright: strict
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maivn_tools.auth import (
    ApiKeyAuth,
    BasicAuth,
    BearerTokenAuth,
    ChainedSecretResolver,
    EnvironmentSecretResolver,
    MissingSecretError,
    NoAuth,
    OAuth2BearerAuth,
    OAuth2Token,
    SecretRef,
    StaticSecretResolver,
)


def test_no_auth_passthrough() -> None:
    req = {"headers": {"X": "Y"}}
    assert NoAuth().apply(req) is req


def test_api_key_requires_exactly_one_destination() -> None:
    with pytest.raises(ValueError):
        ApiKeyAuth("k")
    with pytest.raises(ValueError):
        ApiKeyAuth("k", header="X", query_param="q")
    with pytest.raises(ValueError):
        ApiKeyAuth("", header="X")


def test_api_key_header_and_query_modes() -> None:
    header_strategy = ApiKeyAuth("k", header="X-Api-Key", prefix="Token")
    req = header_strategy.apply({})
    assert req["headers"]["X-Api-Key"] == "Token k"
    assert header_strategy.describe()["location"] == "header"

    query_strategy = ApiKeyAuth("k", query_param="api_key")
    req = query_strategy.apply({})
    assert req["params"]["api_key"] == "k"
    assert query_strategy.describe()["location"] == "query"
    assert "api_key" not in query_strategy.describe()  # value never leaked


def test_bearer_token_validates_inputs_and_attaches_header() -> None:
    with pytest.raises(ValueError):
        BearerTokenAuth("")
    with pytest.raises(ValueError):
        BearerTokenAuth("x", scheme="")
    with pytest.raises(ValueError):
        BearerTokenAuth("x", header="")
    strategy = BearerTokenAuth("abc", scheme="Token", header="Authorization")
    req = strategy.apply({})
    assert req["headers"]["Authorization"] == "Token abc"
    desc = strategy.describe()
    assert desc == {"mode": "bearer", "scheme": "Token", "header": "Authorization"}


def test_basic_auth_validates_and_encodes_header() -> None:
    with pytest.raises(ValueError):
        BasicAuth("", "x")
    strategy = BasicAuth("user", "pw")
    req = strategy.apply({})
    assert req["headers"]["Authorization"].startswith("Basic ")
    assert strategy.describe() == {"mode": "basic", "username": "user"}


def test_oauth2_bearer_calls_provider_each_request() -> None:
    expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
    calls: list[int] = []

    def provider() -> OAuth2Token:
        calls.append(1)
        return OAuth2Token(access_token="tok", expires_at=expires_at)

    strategy = OAuth2BearerAuth(provider)
    req1 = strategy.apply({})
    req2 = strategy.apply({})
    assert req1["headers"]["Authorization"] == "Bearer tok"
    assert req2["headers"]["Authorization"] == "Bearer tok"
    assert len(calls) == 2


def test_oauth2_bearer_rejects_non_callable_and_bad_return() -> None:
    with pytest.raises(TypeError):
        OAuth2BearerAuth("not-callable")  # type: ignore[arg-type]

    strategy = OAuth2BearerAuth(lambda: "not a token")  # type: ignore[arg-type, return-value]
    with pytest.raises(TypeError):
        strategy.apply({})


def test_oauth2_token_is_expired_with_leeway() -> None:
    past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    assert OAuth2Token("x", expires_at=past).is_expired()
    assert OAuth2Token("x", expires_at=future).is_expired() is False
    assert OAuth2Token("x").is_expired() is False


def test_secret_ref_validation() -> None:
    with pytest.raises(ValueError):
        SecretRef("")


def test_environment_secret_resolver() -> None:
    env = {"MAIVN_TOKEN": "value"}
    resolver = EnvironmentSecretResolver(env=env, prefix="MAIVN_")
    assert resolver.resolve(SecretRef("TOKEN")) == "value"
    assert resolver.try_resolve(SecretRef("UNKNOWN")) is None
    with pytest.raises(MissingSecretError):
        resolver.resolve(SecretRef("UNKNOWN"))


def test_environment_resolver_rejects_other_schemes() -> None:
    resolver = EnvironmentSecretResolver(env={"X": "y"})
    with pytest.raises(MissingSecretError):
        resolver.resolve(SecretRef("X", scheme="vault"))


def test_static_secret_resolver() -> None:
    resolver = StaticSecretResolver({"token": "val"})
    assert resolver.resolve(SecretRef("token")) == "val"
    with pytest.raises(MissingSecretError):
        resolver.resolve(SecretRef("missing"))


def test_chained_resolver_walks_sources() -> None:
    chain = ChainedSecretResolver(
        [
            StaticSecretResolver({"a": "1"}),
            StaticSecretResolver({"b": "2"}),
        ]
    )
    assert chain.resolve(SecretRef("b")) == "2"
    with pytest.raises(MissingSecretError):
        chain.resolve(SecretRef("c"))


def test_chained_resolver_requires_at_least_one() -> None:
    with pytest.raises(ValueError):
        ChainedSecretResolver([])
