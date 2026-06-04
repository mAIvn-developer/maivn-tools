"""Secret-resolver interfaces.

A :class:`SecretResolver` translates a :class:`SecretRef` (an indirect
reference like ``"env:GITHUB_TOKEN"``) into the underlying secret value. The
resolver layer keeps secret material out of connector constructors so the
same connector code can run against environment variables, vault providers,
or test fixtures.

The package ships an environment-variable resolver and a static (in-memory)
resolver. Vault integrations should live in optional sub-packages or in
third-party plugins.
"""

# pyright: strict

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# MARK: - Errors


class MissingSecretError(KeyError):
    """Raised when a :class:`SecretResolver` cannot find a requested secret."""


@dataclass(frozen=True)
class SecretRef:
    """A reference to a secret value held by a resolver.

    The reference itself is safe to log; the resolved value is not.

    Attributes:
        name: Logical name of the secret (``"github_token"``,
            ``"smtp_password"``).
        scheme: Optional scheme hint for resolvers that support multiple
            backends (``"env"``, ``"vault"``, ``"static"``).
    """

    name: str
    scheme: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SecretRef.name is required")


# MARK: - Resolver base


class SecretResolver(ABC):
    """Abstract base class for secret resolvers."""

    @abstractmethod
    def resolve(self, ref: SecretRef) -> str:
        """Return the secret value referenced by ``ref``.

        Raises:
            MissingSecretError: When the secret cannot be located.
        """

    def try_resolve(self, ref: SecretRef) -> str | None:
        """Return the secret value, or ``None`` when it cannot be located."""
        try:
            return self.resolve(ref)
        except MissingSecretError:
            return None


# MARK: - Resolvers


class EnvironmentSecretResolver(SecretResolver):
    """Resolve secrets from process environment variables.

    Args:
        env: Optional mapping to read from. Defaults to ``os.environ``.
        prefix: Optional prefix to prepend to ``SecretRef.name`` when looking
            up environment variables. Useful for sandboxing tests.
    """

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        prefix: str = "",
    ) -> None:
        self._env = env if env is not None else os.environ
        self._prefix = prefix

    def resolve(self, ref: SecretRef) -> str:
        if ref.scheme not in (None, "env"):
            raise MissingSecretError(
                f"EnvironmentSecretResolver cannot resolve scheme {ref.scheme!r}"
            )
        key = f"{self._prefix}{ref.name}"
        value = self._env.get(key)
        if value is None:
            raise MissingSecretError(f"Environment variable {key!r} is not set")
        return value


class StaticSecretResolver(SecretResolver):
    """In-memory secret resolver. Intended for tests and local development.

    Args:
        secrets: Mapping of secret name to secret value.
    """

    def __init__(self, secrets: Mapping[str, str]) -> None:
        self._secrets = dict(secrets)

    def resolve(self, ref: SecretRef) -> str:
        if ref.scheme not in (None, "static"):
            raise MissingSecretError(f"StaticSecretResolver cannot resolve scheme {ref.scheme!r}")
        try:
            return self._secrets[ref.name]
        except KeyError as exc:
            raise MissingSecretError(f"Secret {ref.name!r} is not registered") from exc


class ChainedSecretResolver(SecretResolver):
    """Try each resolver in order and return the first match."""

    def __init__(self, resolvers: Iterable[SecretResolver]) -> None:
        self._resolvers = list(resolvers)
        if not self._resolvers:
            raise ValueError("ChainedSecretResolver requires at least one resolver")

    def resolve(self, ref: SecretRef) -> str:
        for resolver in self._resolvers:
            value = resolver.try_resolve(ref)
            if value is not None:
                return value
        raise MissingSecretError(f"No resolver in chain could resolve secret {ref.name!r}")
