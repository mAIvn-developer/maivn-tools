"""Backend resolution for copied v1 toolsets.

Public ``*ToolSet`` registration stays v1-shaped: callers still instantiate a
toolset class and pass it to :func:`maivn_tools.register_connector`. This module
resolves what sits below that public surface.
"""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter, Signature, getdoc, signature
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast, get_type_hints, runtime_checkable

from maivn._internal.compat.tooling import preserve_public_tool_dependency_guidance
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

from maivn_contracts.tools import (
    AuthRef,
    ErrorToolOutcome,
    FunctionToolSpec,
    MCPRegistryServerRef,
    MCPServerRef,
    MCPToolSpec,
    OkToolOutcome,
    SystemToolSpec,
    ToolCall,
    ToolOutcomeError,
    ToolOutcomeVariant,
    ToolSpecRef,
    ToolSpecVariant,
)

from .metadata import AuthMode, ProviderMetadata

TOOLIFY_ATTR = '__maivn_toolify__'
TOOLSET_ATTR = '__maivn_toolset__'
OUTPUT_SCHEMA_ATTR = '__maivn_output_schema__'
# Dependency arguments are filled by the host, not by the model, so they are
# excluded from the published schema exactly as the SDK's builder excludes them.
TOOL_DEPENDENCIES_ATTR = '__maivn_tool_dependencies__'
PRIVATE_DATA_DEPENDENCIES_ATTR = '__maivn_private_data_dependencies__'
INTERRUPT_DEPENDENCIES_ATTR = '__maivn_interrupt_dependencies__'
CONTRACT_VERSION = '2026-07-08'
DEFAULT_TIMEOUT_MS = 30000

type BackendKind = Literal['mcp', 'native']
type NativeReceiverScope = Literal['provider_none', 'platform_primitive']

NONE_PROVIDER_NAMES: frozenset[str] = frozenset(
    {
        'anthropic',
        'census',
        'duo',
        'loops',
        'openai',
        'segment',
        'statuspage',
        'stitch',
        'walmart_marketplace',
    }
)

PLATFORM_PROVIDER_NAMES: frozenset[str] = frozenset(
    {
        'databases',
        'email',
        'files',
        'generic_api',
        'mcp_bridge',
        'graphql',
        'imap',
        'local_files',
        'mysql',
        'openapi',
        'postgres',
        'smtp',
        'sqlite',
        'sqlserver',
        'webhook',
    }
)

NATIVE_PROVIDER_NAMES = NONE_PROVIDER_NAMES | PLATFORM_PROVIDER_NAMES


@dataclass(frozen=True)
class ToolMember:
    """One decorated method exposed by a toolset instance."""

    method_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None


@dataclass(frozen=True)
class MCPToolSetBackend:
    """MCP-backed connector backend reference."""

    provider_name: str
    namespace: str
    server_ref: MCPRegistryServerRef
    credential_ref: AuthRef | None

    kind: Literal['mcp'] = 'mcp'

    def tool_spec(self, tool: ToolMember) -> MCPToolSpec:
        """Return the owned contract spec for one MCP-backed tool."""
        return MCPToolSpec(
            kind='mcp',
            tool_id=f'{self.provider_name}.{tool.method_name}',
            namespace=self.namespace,
            version=CONTRACT_VERSION,
            idempotency='unknown',
            timeout_ms=DEFAULT_TIMEOUT_MS,
            auth=self.credential_ref,
            server_ref=self.server_ref,
            tool_name=tool.tool_name,
            schema_policy='passthrough',
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
        )


@dataclass(frozen=True)
class NativeToolSetBackend:
    """Native v1 receiver backend for platform and NONE coverage primitives."""

    provider_name: str
    namespace: str
    receiver_scope: NativeReceiverScope
    credential_ref: AuthRef | None

    kind: Literal['native'] = 'native'

    def tool_spec(self, tool: ToolMember) -> FunctionToolSpec | SystemToolSpec:
        """Return the owned contract spec for one native receiver tool."""
        tool_id = f'{self.provider_name}.{tool.method_name}'
        if self.receiver_scope == 'platform_primitive':
            return SystemToolSpec(
                kind='system',
                tool_id=tool_id,
                namespace=self.namespace,
                version=CONTRACT_VERSION,
                idempotency='unknown',
                timeout_ms=DEFAULT_TIMEOUT_MS,
                auth=self.credential_ref,
                name=tool.tool_name,
                description=tool.description,
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
            )
        return FunctionToolSpec(
            kind='function',
            tool_id=tool_id,
            namespace=self.namespace,
            version=CONTRACT_VERSION,
            idempotency='unknown',
            timeout_ms=DEFAULT_TIMEOUT_MS,
            auth=self.credential_ref,
            name=tool.tool_name,
            description=tool.description,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
        )


type ToolSetBackend = MCPToolSetBackend | NativeToolSetBackend


@dataclass(frozen=True)
class ToolSetRegistration:
    """Resolved registration record returned by ``register_connector``."""

    toolset_name: str
    provider_name: str
    backend: ToolSetBackend
    specs: tuple[ToolSpecVariant, ...]

    def spec_ref_for(self, tool_name: str) -> ToolSpecRef:
        """Return a contract ref for a registered tool name."""
        for spec in self.specs:
            spec_name = getattr(spec, 'tool_name', getattr(spec, 'name', None))
            if spec_name == tool_name:
                return ToolSpecRef(
                    tool_id=spec.tool_id,
                    namespace=spec.namespace,
                    version=spec.version,
                )
        message = f'unknown tool name for registration: {tool_name}'
        raise KeyError(message)


@runtime_checkable
class MCPToolClient(Protocol):
    """Minimal MCP client surface used by the tools package eval."""

    def call_tool(
        self,
        server_ref: MCPServerRef,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> Awaitable[Any]:
        """Call one tool on an MCP server."""
        ...


@runtime_checkable
class ToolSetMetadataLike(Protocol):
    """Provider metadata surface needed for auth resolution."""

    auth_modes: tuple[AuthMode, ...]


class MCPToolBackendExecutor:
    """Execute MCP-backed tool calls through an injected MCP client."""

    def __init__(self, client: MCPToolClient) -> None:
        """Create an executor over an injected MCP client."""
        self._client = client

    async def execute(self, spec: MCPToolSpec, tool_call: ToolCall) -> ToolOutcomeVariant:
        """Dispatch a tool call and return an owned outcome contract."""
        start = perf_counter()
        try:
            result = await self._client.call_tool(
                spec.server_ref,
                spec.tool_name,
                tool_call.arguments,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            duration_ms = _duration_ms(start)
            message = str(exc) or type(exc).__name__
            return ErrorToolOutcome(
                call_id=tool_call.call_id,
                duration_ms=duration_ms,
                status='error',
                error=ToolOutcomeError(
                    code='mcp_tool_error',
                    message=message,
                    retryable=False,
                ),
            )
        return OkToolOutcome(
            call_id=tool_call.call_id,
            duration_ms=_duration_ms(start),
            status='ok',
            result=result,
        )


def resolve_toolset_backend(toolset: object) -> ToolSetBackend:
    """Resolve the backing strategy for a public toolset instance."""
    provider_name = provider_name_for(toolset)
    namespace = namespace_for(provider_name)
    credential_ref = _auth_ref_for(toolset)
    if provider_name in NATIVE_PROVIDER_NAMES:
        receiver_scope: NativeReceiverScope = (
            'provider_none' if provider_name in NONE_PROVIDER_NAMES else 'platform_primitive'
        )
        return NativeToolSetBackend(
            provider_name=provider_name,
            namespace=namespace,
            receiver_scope=receiver_scope,
            credential_ref=credential_ref,
        )
    return MCPToolSetBackend(
        provider_name=provider_name,
        namespace=namespace,
        server_ref=MCPRegistryServerRef(kind='registry', name=provider_name),
        credential_ref=credential_ref,
    )


def toolset_contract_specs(toolset: object) -> ToolSetRegistration:
    """Return resolved backend and owned contract specs for a toolset."""
    backend = resolve_toolset_backend(toolset)
    specs = tuple(backend.tool_spec(tool) for tool in public_tool_members(toolset))
    return ToolSetRegistration(
        toolset_name=type(toolset).__name__,
        provider_name=backend.provider_name,
        backend=backend,
        specs=specs,
    )


def public_tool_members(toolset: object) -> tuple[ToolMember, ...]:
    """Return decorated public tool methods in stable name order."""
    prefix = _toolset_prefix(toolset)
    members: list[ToolMember] = []
    for attr_name in sorted(dir(toolset)):
        if attr_name.startswith('_'):
            continue
        method = getattr(toolset, attr_name)
        options = getattr(method, TOOLIFY_ATTR, None)
        if options is None:
            continue
        option_name = getattr(options, 'name', None)
        tool_name = _tool_name(prefix, attr_name, option_name)
        output_schema = getattr(method, OUTPUT_SCHEMA_ATTR, None)
        members.append(
            ToolMember(
                method_name=attr_name,
                tool_name=tool_name,
                description=_description_for(method, tool_name, options),
                input_schema=_input_schema_for(method),
                output_schema=cast('dict[str, Any] | None', output_schema),
            )
        )
    return tuple(members)


def provider_name_for(toolset: object) -> str:
    """Return a stable connector coverage name for a toolset."""
    metadata = getattr(toolset, 'metadata', None)
    if isinstance(metadata, ProviderMetadata):
        return _normalize_provider_name(metadata.name)
    metadata_name = getattr(metadata, 'name', None)
    if isinstance(metadata_name, str) and metadata_name:
        return _normalize_provider_name(metadata_name)
    prefix = _toolset_prefix(toolset)
    if prefix:
        return _normalize_provider_name(prefix)
    name = type(toolset).__name__.removesuffix('ToolSet')
    return _normalize_provider_name(name)


def namespace_for(provider_name: str) -> str:
    """Return a contract namespace for a provider."""
    normalized = provider_name.replace('_', '-')
    return f'maivn-tools.{normalized}'


def backend_snapshot(registration: ToolSetRegistration) -> dict[str, Any]:
    """Return a JSON-compatible backend snapshot for golden tests."""
    backend = registration.backend
    payload: dict[str, Any] = {
        'kind': backend.kind,
        'provider_name': backend.provider_name,
        'namespace': backend.namespace,
        'spec_count': len(registration.specs),
    }
    if isinstance(backend, MCPToolSetBackend):
        payload['server_ref'] = backend.server_ref.model_dump(mode='json')
        if backend.credential_ref is not None:
            payload['credential_ref'] = backend.credential_ref.model_dump(mode='json')
    else:
        payload['receiver_scope'] = backend.receiver_scope
        if backend.credential_ref is not None:
            payload['credential_ref'] = backend.credential_ref.model_dump(mode='json')
    return payload


def spec_ref_for(spec: ToolSpecVariant) -> ToolSpecRef:
    """Return a contract reference for a tool spec."""
    return ToolSpecRef(tool_id=spec.tool_id, namespace=spec.namespace, version=spec.version)


def _toolset_prefix(toolset: object) -> str | None:
    options = getattr(type(toolset), TOOLSET_ATTR, None)
    prefix = getattr(options, 'prefix', None)
    if isinstance(prefix, str) and prefix:
        return prefix
    return None


def _tool_name(prefix: str | None, method_name: str, option_name: object) -> str:
    raw_name = option_name if isinstance(option_name, str) and option_name else method_name
    safe_name = _safe_identifier(raw_name)
    if prefix:
        return f'{_safe_identifier(prefix).upper()}_{safe_name}'
    return safe_name


def _description_for(method: object, tool_name: str, options: object) -> str:
    option_description = getattr(options, 'description', None)
    if isinstance(option_description, str) and option_description:
        return option_description
    doc = getdoc(method)
    if doc:
        return doc
    return f'Invoke {tool_name}.'


def _input_schema_for(method: object) -> dict[str, Any]:
    """Derive the model-facing JSON schema for one decorated tool method.

    This must agree with the SDK's own builder, because the two are the two
    branches of :func:`maivn_tools.register_connector` and a host is entitled to
    the same tool whichever branch it takes. The derivation is therefore the
    same one: resolve the annotations, then let pydantic render each of them.
    """
    callable_method = cast('Callable[..., object]', method)
    try:
        method_signature = signature(callable_method)
    except (TypeError, ValueError):
        return {'type': 'object', 'properties': {}}
    dependency_args = _dependency_arg_names(callable_method)
    resolved_hints = _resolved_type_hints(callable_method)
    properties: dict[str, Any] = {}
    definition_adapters: dict[str, TypeAdapter[object]] = {}
    required: list[str] = []
    for name, parameter in method_signature.parameters.items():
        if (
            name == 'self'
            or name in dependency_args
            or parameter.kind in (Parameter.VAR_KEYWORD, Parameter.VAR_POSITIONAL)
        ):
            continue
        properties[name] = _json_schema_for_parameter(
            parameter, resolved_hints.get(name), definition_adapters=definition_adapters
        )
        if parameter.default is Signature.empty:
            required.append(name)
    schema: dict[str, Any] = {
        'type': 'object',
        'properties': properties,
        'additionalProperties': False,
    }
    if required:
        schema['required'] = required
    if definition_adapters:
        # Share one definition namespace so recursion and colliding model names
        # have valid root references, matching the public SDK registration path.
        parameter_schemas, definitions = TypeAdapter.json_schemas(
            [(name, 'validation', adapter) for name, adapter in definition_adapters.items()]
        )
        properties.update({name: value for (name, _mode), value in parameter_schemas.items()})
        schema.update(definitions)
    preserve_public_tool_dependency_guidance(callable_method, schema)
    return schema


def _json_schema_for_parameter(
    parameter: Parameter,
    resolved_annotation: object | None,
    *,
    definition_adapters: dict[str, TypeAdapter[object]],
) -> dict[str, Any]:
    annotation = resolved_annotation or parameter.annotation
    if annotation is not Signature.empty:
        try:
            adapter: TypeAdapter[object] = TypeAdapter(annotation)
            schema = adapter.json_schema()
        except (TypeError, ValueError):
            pass
        else:
            if '$defs' in schema:
                definition_adapters[parameter.name] = adapter
            return schema
    # Reached only for an unannotated parameter or an annotation pydantic cannot
    # render. Matching the annotation object was the whole derivation before, and
    # under `from __future__ import annotations` -- which every connector module
    # carries -- `signature` yields strings, so every one of the 5945 parameters
    # in this package missed and published `{'description': <name>}`: a schema
    # that constrains nothing, sent to models as if it did.
    schema_by_annotation: dict[object, dict[str, Any]] = {
        bool: {'type': 'boolean'},
        int: {'type': 'integer'},
        float: {'type': 'number'},
        str: {'type': 'string'},
        list: {'type': 'array'},
        tuple: {'type': 'array'},
        dict: {'type': 'object'},
    }
    return schema_by_annotation.get(annotation, {'description': parameter.name})


def _resolved_type_hints(method: Callable[..., object]) -> dict[str, object]:
    try:
        return cast('dict[str, object]', get_type_hints(method, include_extras=True))
    except Exception:
        # A connector may annotate against a third-party name that is not
        # importable here; the parameter falls back rather than the whole toolset
        # failing to register.
        return {}


def _dependency_arg_names(method: object) -> frozenset[str]:
    dependencies: list[object] = []
    for attr_name in (
        PRIVATE_DATA_DEPENDENCIES_ATTR,
        TOOL_DEPENDENCIES_ATTR,
        INTERRUPT_DEPENDENCIES_ATTR,
    ):
        raw = getattr(method, attr_name, ())
        if isinstance(raw, list):
            dependencies.extend(cast('list[object]', raw))
    return frozenset(
        arg_name
        for dependency in dependencies
        if isinstance((arg_name := getattr(dependency, 'arg_name', None)), str)
    )


def _auth_ref_for(toolset: object) -> AuthRef | None:
    metadata = getattr(toolset, 'metadata', None)
    if not isinstance(metadata, (ProviderMetadata, ToolSetMetadataLike)):
        return None
    metadata_with_auth = cast(ToolSetMetadataLike, metadata)
    auth_modes = metadata_with_auth.auth_modes
    if not auth_modes:
        return None
    mode = auth_modes[0]
    if mode == AuthMode.NONE:
        return None
    scheme = _auth_scheme_for(mode)
    return AuthRef(scheme=scheme, secret_ref=f'vault://connectors/{provider_name_for(toolset)}')


def _auth_scheme_for(mode: AuthMode) -> Literal['api_key', 'bearer', 'basic', 'oauth', 'custom']:
    if mode == AuthMode.API_KEY:
        return 'api_key'
    if mode == AuthMode.BEARER:
        return 'bearer'
    if mode == AuthMode.BASIC:
        return 'basic'
    if mode in {
        AuthMode.OAUTH2_AUTH_CODE,
        AuthMode.OAUTH2_CLIENT_CREDENTIALS,
        AuthMode.OAUTH2_DEVICE_CODE,
        AuthMode.OAUTH2_PKCE,
    }:
        return 'oauth'
    return 'custom'


def _safe_identifier(value: str) -> str:
    safe = ''.join(character if character.isalnum() else '_' for character in value)
    safe = safe.strip('_')
    if not safe:
        return 'tool'
    if safe[0].isdigit():
        return f'tool_{safe}'
    return safe


def _normalize_provider_name(value: str) -> str:
    return _safe_identifier(value).lower()


def _duration_ms(start: float) -> int:
    return max(0, int((perf_counter() - start) * 1000))


__all__ = [
    'CONTRACT_VERSION',
    'DEFAULT_TIMEOUT_MS',
    'NATIVE_PROVIDER_NAMES',
    'NONE_PROVIDER_NAMES',
    'PLATFORM_PROVIDER_NAMES',
    'BackendKind',
    'MCPToolBackendExecutor',
    'MCPToolClient',
    'MCPToolSetBackend',
    'NativeReceiverScope',
    'NativeToolSetBackend',
    'ToolMember',
    'ToolSetBackend',
    'ToolSetRegistration',
    'backend_snapshot',
    'namespace_for',
    'provider_name_for',
    'public_tool_members',
    'resolve_toolset_backend',
    'spec_ref_for',
    'toolset_contract_specs',
]
