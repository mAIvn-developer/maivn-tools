# pyright: strict
from __future__ import annotations

from inspect import getdoc
from typing import Any

from maivn import toolify, toolset
from maivn_contracts.tools import (
    FunctionToolSpec,
    MCPRegistryServerRef,
    MCPToolSpec,
    SystemToolSpec,
)

from maivn_tools.core import (
    AuthMode,
    ProviderCapability,
    ProviderMetadata,
    ToolSetRegistration,
    backend_snapshot,
    register_connector,
    resolve_toolset_backend,
    toolset_contract_specs,
)


@toolset(prefix='github')
class FakeOfficialToolSet:
    metadata = ProviderMetadata(
        name='github',
        display_name='GitHub',
        version='0.1.0',
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ}),
    )

    @toolify
    def list_issues(self, repo: str) -> dict[str, Any]:
        return {'repo': repo}


@toolset(prefix='openai')
class FakeNoneToolSet:
    metadata = ProviderMetadata(
        name='openai',
        display_name='OpenAI',
        version='0.1.0',
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ}),
    )

    @toolify
    def list_models(self) -> dict[str, Any]:
        return {'models': []}


@toolset(prefix='local_files')
class FakePlatformToolSet:
    metadata = ProviderMetadata(
        name='local_files',
        display_name='Local Files',
        version='0.1.0',
        auth_modes=(AuthMode.NONE,),
        capabilities=frozenset({ProviderCapability.READ}),
    )

    @toolify
    def read_text(self, path: str) -> dict[str, Any]:
        return {'path': path}


class FakeHost:
    def __init__(self) -> None:
        self.registrations: list[ToolSetRegistration] = []

    def add_toolset_backend(self, registration: ToolSetRegistration) -> None:
        self.registrations.append(registration)

    def add_tool(self, tool: object) -> object:
        return tool


def test_official_provider_resolves_to_mcp_contract_spec() -> None:
    registration = toolset_contract_specs(FakeOfficialToolSet())

    assert registration.backend.kind == 'mcp'
    spec = registration.specs[0]
    assert isinstance(spec, MCPToolSpec)
    server_ref = spec.server_ref
    assert isinstance(server_ref, MCPRegistryServerRef)
    assert server_ref.name == 'github'
    assert spec.auth is not None
    assert spec.auth.scheme == 'bearer'


def test_none_provider_keeps_native_function_receiver() -> None:
    registration = toolset_contract_specs(FakeNoneToolSet())

    assert registration.backend.kind == 'native'
    assert isinstance(registration.specs[0], FunctionToolSpec)
    assert backend_snapshot(registration)['receiver_scope'] == 'provider_none'


def test_platform_primitive_keeps_native_system_receiver() -> None:
    registration = toolset_contract_specs(FakePlatformToolSet())

    assert registration.backend.kind == 'native'
    assert isinstance(registration.specs[0], SystemToolSpec)
    assert registration.specs[0].auth is None
    assert backend_snapshot(registration)['receiver_scope'] == 'platform_primitive'


def test_register_connector_reports_resolved_backend_to_host() -> None:
    host = FakeHost()
    returned = register_connector(host, FakeOfficialToolSet())

    assert len(host.registrations) == 1
    assert returned == [host.registrations[0]]
    assert host.registrations[0].backend.kind == 'mcp'


def test_resolve_toolset_backend_uses_metadata_name_over_class_name() -> None:
    backend = resolve_toolset_backend(FakePlatformToolSet())

    assert backend.provider_name == 'local_files'
    assert backend.kind == 'native'


def test_backend_registration_preserves_multiline_execution_constraints() -> None:
    @toolset(prefix='layout')
    class Layout(FakeNoneToolSet):
        @toolify
        def place(self, address: str) -> str:
            """Place a rectangle.

            Ranges must not overlap. Reuse the existing identifier to replace one.
            Blank cells still occupy space; place formulas in separate ranges.
            """
            return address

    registration = toolset_contract_specs(Layout())
    spec = next(spec for spec in registration.specs if spec.tool_id == 'openai.place')
    assert isinstance(spec, FunctionToolSpec)
    assert spec.description == getdoc(Layout.place)
