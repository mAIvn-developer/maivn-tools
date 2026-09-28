# pyright: strict
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple, cast

from maivn import toolify, toolset
from maivn_contracts.tools import (
    MCPRegistryServerRef,
    MCPServerRef,
    MCPToolSpec,
    ToolCall,
    ToolCallLineage,
)

from maivn_tools.core import AuthMode, ProviderCapability, ProviderMetadata, register_connector
from maivn_tools.core.backends import (
    MCPToolBackendExecutor,
    ToolSetRegistration,
    spec_ref_for,
)


class MCPBackendEvalResult(NamedTuple):
    registration: ToolSetRegistration
    tool_call: ToolCall
    outcome_result: dict[str, Any]


@toolset(prefix='github')
class FakeGitHubToolSet:
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


class FakeSDKTransport:
    def __init__(self) -> None:
        self.registrations: list[ToolSetRegistration] = []

    def add_toolset_backend(self, registration: ToolSetRegistration) -> None:
        self.registrations.append(registration)

    def add_tool(self, tool: object) -> object:
        return tool


class FakeMCPServer:
    def __init__(self) -> None:
        self.calls: list[tuple[MCPRegistryServerRef, str, dict[str, Any]]] = []

    async def call_tool(
        self,
        server_ref: MCPServerRef,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(server_ref, MCPRegistryServerRef):
            message = 'fake MCP eval only supports registry server refs'
            raise TypeError(message)
        payload = dict(arguments)
        self.calls.append((server_ref, tool_name, payload))
        return {'server': server_ref.name, 'tool': tool_name, 'arguments': payload}


async def run_mcp_backend_eval() -> MCPBackendEvalResult:
    transport = FakeSDKTransport()
    register_connector(transport, FakeGitHubToolSet())
    registration = transport.registrations[0]
    spec = cast('MCPToolSpec', registration.specs[0])
    tool_call = ToolCall(
        call_id='call-1',
        spec_ref=spec_ref_for(spec),
        arguments={'repo': 'maivn-platform'},
        lineage=ToolCallLineage(session_id='session-1', invocation_id='invoke-1'),
    )

    outcome = await MCPToolBackendExecutor(FakeMCPServer()).execute(spec, tool_call)
    if outcome.status != 'ok':
        message = f'eval expected ok outcome, got {outcome.status}'
        raise AssertionError(message)
    return MCPBackendEvalResult(
        registration=registration,
        tool_call=tool_call,
        outcome_result=cast('dict[str, Any]', outcome.result),
    )
