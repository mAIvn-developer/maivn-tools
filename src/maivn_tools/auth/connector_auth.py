"""Machine-readable "this connection needs re-consent" signalling.

Detection is in-process; consent is always out-of-process. When a connector
discovers that its stored authorization can no longer be used, the only thing
the SDK can usefully do is stop and say *which* connection went unusable and
*why*. It must not say *how* to fix it, because the remedy is different on
every surface:

* a desktop UI renders a reconnect card and opens a redirect,
* a terminal starts a device-code grant (see
  :meth:`~maivn_tools.auth.OAuth2Flow.request_device_code`),
* an integrator's web app redirects the end user to the provider,
* a non-interactive caller (cron, CI, a queue worker) has no one to ask, so it
  must fail fast and non-zero rather than block on consent that cannot arrive.

Raising an exception gives all four the behaviour they need for free: the
interactive surfaces catch it and render their own words, and the
non-interactive one propagates and exits non-zero.

Raising::

    raise ConnectorGrantStaleError(connector_id='gmail', provider='google')

Handling::

    try:
        run()
    except ConnectorAuthRequiredError as exc:
        prompt_reconnect(exc.connector_id, exc.provider, exc.reason)

This works the same for a shipped toolset and for a customer's own OAuth
application: ``connector_id`` is whatever identifier that integration already
uses for the connection, and ``provider`` is whatever it calls the authorization
server. Neither is interpreted here.

Nothing in this module carries credential material. ``connector_id``,
``provider``, and ``reason`` are all stable identifiers chosen by the
integration, never token values, refresh tokens, account addresses, or raw
provider error text.
"""

# pyright: strict

from __future__ import annotations

from typing import Final

REASON_AUTHORIZATION_REQUIRED: Final = 'authorization_required'
"""No usable authorization is stored for this connection."""

REASON_GRANT_STALE: Final = 'grant_stale'
"""The provider explicitly rejected the stored grant."""

REASON_SCOPE_UPGRADE_REQUIRED: Final = 'scope_upgrade_required'
"""The stored grant is valid but lacks a scope this connection now needs."""


class ConnectorAuthRequiredError(RuntimeError):
    """A connection's stored authorization can no longer be used.

    This is the SDK's whole contribution to re-consent: a typed failure
    carrying enough identity for a surface to route the user to the right
    connection, and no instruction about how that surface should do it.

    Subclasses narrow :attr:`reason`; raising this class directly reports
    :data:`REASON_AUTHORIZATION_REQUIRED`.

    Args:
        connector_id: The integration's own identifier for the connection
            that went unusable (for example ``'gmail'``, or a customer's
            ``'acme-crm'``). Surfaces match on this, so it must be the same
            identifier the surface knows the connection by.
        provider: The authorization server this connection authenticates
            against (for example ``'google'``).
        reason: Why re-consent is needed. Defaults to the raising class's
            :attr:`default_reason`. Prefer the ``REASON_*`` constants;
            surfaces fall back to generic wording for anything else.
        message: Optional replacement for the derived exception text. Keep it
            value-free: it can reach logs and non-interactive stderr.
    """

    default_reason: str = REASON_AUTHORIZATION_REQUIRED

    def __init__(
        self,
        *,
        connector_id: str,
        provider: str,
        reason: str | None = None,
        message: str | None = None,
    ) -> None:
        resolved_reason = reason or type(self).default_reason
        super().__init__(
            message
            or (
                f'Connection {connector_id!r} on provider {provider!r} '
                f'needs re-authorization ({resolved_reason})'
            )
        )
        self.connector_id = connector_id
        self.provider = provider
        self.reason = resolved_reason


class ConnectorGrantStaleError(ConnectorAuthRequiredError):
    """The provider rejected the stored grant, so the user must consent again.

    Raise this when the authorization server answers a refresh with an
    explicit rejection (OAuth 2.0 ``invalid_grant``): the user revoked access,
    changed their password, or the grant expired. Retrying cannot help.
    """

    default_reason: str = REASON_GRANT_STALE


class ConnectorScopeUpgradeRequiredError(ConnectorAuthRequiredError):
    """The stored grant is live but does not cover a now-required scope.

    Raise this when the connection still authenticates but the operation needs
    permission the user has not granted, so the surface can ask for the wider
    consent rather than reporting a permission error.
    """

    default_reason: str = REASON_SCOPE_UPGRADE_REQUIRED


__all__: list[str] = [
    'REASON_AUTHORIZATION_REQUIRED',
    'REASON_GRANT_STALE',
    'REASON_SCOPE_UPGRADE_REQUIRED',
    'ConnectorAuthRequiredError',
    'ConnectorGrantStaleError',
    'ConnectorScopeUpgradeRequiredError',
]
