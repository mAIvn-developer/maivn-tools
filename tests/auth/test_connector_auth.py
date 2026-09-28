"""Contract tests for the shared connector re-authorization error family."""

# pyright: strict

from __future__ import annotations

import pytest

import maivn_tools
from maivn_tools.auth import (
    REASON_AUTHORIZATION_REQUIRED,
    REASON_GRANT_STALE,
    REASON_SCOPE_UPGRADE_REQUIRED,
    ConnectorAuthRequiredError,
    ConnectorGrantStaleError,
    ConnectorScopeUpgradeRequiredError,
)


def test_family_is_exported_from_the_package_root() -> None:
    """Integrators import these by name; moving them is a breaking change."""
    assert maivn_tools.ConnectorAuthRequiredError is ConnectorAuthRequiredError
    assert maivn_tools.ConnectorGrantStaleError is ConnectorGrantStaleError
    assert maivn_tools.ConnectorScopeUpgradeRequiredError is ConnectorScopeUpgradeRequiredError


def test_one_except_clause_catches_every_member() -> None:
    """Surfaces handle re-consent with a single handler, not a type list."""
    assert issubclass(ConnectorGrantStaleError, ConnectorAuthRequiredError)
    assert issubclass(ConnectorScopeUpgradeRequiredError, ConnectorAuthRequiredError)
    assert issubclass(ConnectorAuthRequiredError, RuntimeError)


def test_identity_survives_the_raise() -> None:
    """Without identity a surface cannot say WHICH connection to reconnect."""
    with pytest.raises(ConnectorAuthRequiredError) as caught:
        raise ConnectorGrantStaleError(connector_id='acme-crm', provider='acme')

    assert caught.value.connector_id == 'acme-crm'
    assert caught.value.provider == 'acme'
    assert caught.value.reason == REASON_GRANT_STALE


@pytest.mark.parametrize(
    ('exc_type', 'expected'),
    [
        (ConnectorAuthRequiredError, REASON_AUTHORIZATION_REQUIRED),
        (ConnectorGrantStaleError, REASON_GRANT_STALE),
        (ConnectorScopeUpgradeRequiredError, REASON_SCOPE_UPGRADE_REQUIRED),
    ],
)
def test_each_member_reports_its_own_reason(
    exc_type: type[ConnectorAuthRequiredError], expected: str
) -> None:
    """A shared default would collapse three distinct remedies into one."""
    error = exc_type(connector_id='gmail', provider='google')

    assert error.reason == expected


def test_an_explicit_reason_overrides_the_class_default() -> None:
    """Custom OAuth apps have failure modes this package cannot enumerate."""
    error = ConnectorAuthRequiredError(
        connector_id='acme-crm',
        provider='acme',
        reason='tenant_migrated',
    )

    assert error.reason == 'tenant_migrated'


def test_the_derived_message_names_what_went_stale_not_how_to_fix_it() -> None:
    """A raise site that prescribes a remedy is wrong on every other surface."""
    text = str(ConnectorGrantStaleError(connector_id='gmail', provider='google'))

    assert 'gmail' in text
    assert 'google' in text
    assert REASON_GRANT_STALE in text
    for remedy in ('studio', 'reconnect in', 'run ', 'click', 'browser'):
        assert remedy not in text.casefold()


def test_a_caller_supplied_message_replaces_the_derived_one() -> None:
    """Connectors own their wording; identity still travels on the attributes."""
    error = ConnectorGrantStaleError(
        connector_id='gmail',
        provider='google',
        message='The saved Gmail authorization is no longer accepted.',
    )

    assert str(error) == 'The saved Gmail authorization is no longer accepted.'
    assert error.connector_id == 'gmail'
    assert error.reason == REASON_GRANT_STALE


def test_a_non_interactive_caller_gets_a_failure_it_cannot_ignore() -> None:
    """Blocking a cron job on consent that cannot arrive would hang it forever."""
    with pytest.raises(ConnectorAuthRequiredError):
        raise ConnectorAuthRequiredError(connector_id='gmail', provider='google')
