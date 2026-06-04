# pyright: strict

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from maivn_tools.core import (
    PERMISSION_FLAG_NAMES,
    AuthMode,
    ConnectionHealth,
    ConnectionMetadata,
    ConnectionStatus,
    DryRunOutcome,
    DryRunPlan,
    PermissionFlag,
    PermissionSet,
    ProviderCapability,
    ProviderMetadata,
    TokenMetadata,
    ToolFactory,
    dry_run_capable,
    register_connector,
    register_tools,
    require_permissions,
    toolset,
)


def test_provider_metadata_validates_required_fields() -> None:
    with pytest.raises(ValueError):
        ProviderMetadata(name="", display_name="x", version="0.1")
    with pytest.raises(ValueError):
        ProviderMetadata(name="x", display_name="", version="0.1")
    with pytest.raises(ValueError):
        ProviderMetadata(name="x", display_name="x", version="")


def test_provider_metadata_serializable_and_supports_checks() -> None:
    md = ProviderMetadata(
        name="example",
        display_name="Example",
        version="0.1.0",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        scopes={"read": "read all"},
    )
    assert md.supports_auth(AuthMode.BEARER) is True
    assert md.supports_auth(AuthMode.OAUTH2_PKCE) is False
    assert md.has_capability(ProviderCapability.READ)
    payload = md.to_dict()
    assert payload["name"] == "example"
    assert payload["auth_modes"] == ["bearer", "api_key"]
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, list)
    assert "read" in capabilities
    assert payload["scopes"] == {"read": "read all"}


def test_connection_metadata_to_dict_omits_secret_material() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = TokenMetadata(
        fingerprint="abc12345",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        scopes=("read",),
        refreshable=True,
    )
    md = ConnectionMetadata(
        connection_id="c1",
        provider="example",
        auth_mode=AuthMode.BEARER,
        scopes=("read",),
        token=token,
        health=ConnectionHealth(status=ConnectionStatus.ACTIVE, checked_at=now),
        created_at=now,
        updated_at=now,
    )
    payload = md.to_dict()
    assert payload["token"]["fingerprint"] == "abc12345"
    assert "access_token" not in payload["token"]
    assert payload["health"]["status"] == "active"
    assert md.is_active()


def test_connection_metadata_requires_ids() -> None:
    with pytest.raises(ValueError):
        ConnectionMetadata(connection_id="", provider="x")
    with pytest.raises(ValueError):
        ConnectionMetadata(connection_id="x", provider="")


def test_token_metadata_expiry() -> None:
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    tok = TokenMetadata(expires_at=past)
    assert tok.is_expired()
    forever = TokenMetadata()
    assert forever.is_expired() is False


def test_permission_flag_names_cover_every_flag() -> None:
    assert set(PERMISSION_FLAG_NAMES) == {
        PermissionFlag.READ,
        PermissionFlag.WRITE,
        PermissionFlag.DELETE,
        PermissionFlag.EXPORT,
        PermissionFlag.IMPORT,
        PermissionFlag.ADMIN,
        PermissionFlag.IMPERSONATE,
    }


def test_permission_set_helpers() -> None:
    ps = PermissionSet(PermissionFlag.READ | PermissionFlag.WRITE)
    assert ps.includes(PermissionFlag.READ)
    assert PermissionFlag.WRITE in ps
    assert ps.to_list() == ["read", "write"]
    combined = ps | PermissionFlag.DELETE
    assert combined.is_destructive() is True
    assert PermissionSet().is_empty()
    assert PermissionSet.from_names(["read"]) == PermissionSet(PermissionFlag.READ)
    assert PermissionSet.all().includes(PermissionFlag.ADMIN)
    assert (
        PermissionSet(PermissionFlag.READ | PermissionFlag.WRITE) & PermissionFlag.READ
    ) == PermissionSet(PermissionFlag.READ)


def test_permission_set_from_names_rejects_unknown_flags() -> None:
    with pytest.raises(ValueError):
        PermissionSet.from_names(["bogus"])


def test_require_permissions_reports_missing_flags() -> None:
    granted = PermissionSet(PermissionFlag.READ)
    with pytest.raises(PermissionError):
        require_permissions(granted, PermissionFlag.WRITE)
    require_permissions(granted, PermissionFlag.READ)


def test_dry_run_outcome_is_serializable() -> None:
    plan = DryRunPlan(
        operation="create",
        target="widgets/new",
        before=None,
        after={"name": "x"},
        notes="freshly minted",
    )
    outcome = DryRunOutcome(tool="create_widget", plans=(plan,), warnings=("preview",))
    payload = outcome.to_dict()
    assert payload["tool"] == "create_widget"
    assert payload["plans"][0]["operation"] == "create"
    assert payload["plans"][0]["after"] == {"name": "x"}
    assert outcome.is_noop() is False
    assert DryRunOutcome(tool="noop").is_noop()


def test_dry_run_capable_marker() -> None:
    @dry_run_capable
    def update() -> str:
        return "ok"

    assert cast(bool, cast(Any, update).__maivn_dry_run_capable__) is True


class _FakeHost:
    def __init__(self) -> None:
        self.registered: list[Any] = []

    def add_tool(self, tool: Any) -> Any:
        self.registered.append(tool)
        return tool


class _FakeProvider:
    def tools(self) -> list[ToolFactory]:
        return [lambda: 1, lambda: 2]


class _FakeConnector:
    metadata: ProviderMetadata = ProviderMetadata(name="x", display_name="X", version="0.1")
    connection: None = None

    def tools(self) -> list[ToolFactory]:
        return [lambda: 1]


def test_toolset_dispatch_for_connectors_and_providers_and_iterables() -> None:
    assert len(toolset(_FakeConnector())) == 1
    assert len(toolset(_FakeProvider())) == 2
    iterable: list[ToolFactory] = [lambda: 1, lambda: 2, lambda: 3]
    assert toolset(iterable) == iterable


def test_register_tools_uses_host_add_tool() -> None:
    host = _FakeHost()
    tools: list[ToolFactory] = [lambda: 1, lambda: 2]
    registered = register_tools(host, tools)
    assert registered == tools
    assert host.registered == tools


def test_register_tools_requires_add_tool() -> None:
    with pytest.raises(TypeError):
        register_tools(object(), [])  # type: ignore[arg-type]


def test_register_connector_attaches_every_tool() -> None:
    host = _FakeHost()
    registered = register_connector(host, _FakeProvider())
    assert len(registered) == 2
    assert len(host.registered) == 2
