"""Core connector primitives: protocols, metadata, permissions, and registration."""

# pyright: strict

from __future__ import annotations

from .backends import (
    MCPToolBackendExecutor,
    MCPToolClient,
    MCPToolSetBackend,
    NativeToolSetBackend,
    ToolMember,
    ToolSetBackend,
    ToolSetRegistration,
    backend_snapshot,
    public_tool_members,
    resolve_toolset_backend,
    spec_ref_for,
    toolset_contract_specs,
)
from .connections import (
    ConnectionHealth,
    ConnectionMetadata,
    ConnectionStatus,
    TokenMetadata,
)
from .dry_run import DryRunOutcome, DryRunPlan, dry_run_capable
from .metadata import AuthMode, ProviderCapability, ProviderMetadata
from .permissions import (
    PERMISSION_FLAG_NAMES,
    PermissionFlag,
    PermissionSet,
    require_permissions,
)
from .protocols import (
    Connector,
    ConnectorTool,
    ToolFactory,
    ToolProvider,
)
from .registration import (
    register_connector,
    register_tools,
    resolve_connector_tools,
    toolset,
)

__all__ = [
    'AuthMode',
    'ConnectionHealth',
    'ConnectionMetadata',
    'ConnectionStatus',
    'Connector',
    'ConnectorTool',
    'DryRunOutcome',
    'DryRunPlan',
    'MCPToolBackendExecutor',
    'MCPToolClient',
    'MCPToolSetBackend',
    'NativeToolSetBackend',
    'PERMISSION_FLAG_NAMES',
    'PermissionFlag',
    'PermissionSet',
    'ProviderCapability',
    'ProviderMetadata',
    'TokenMetadata',
    'ToolFactory',
    'ToolMember',
    'ToolProvider',
    'ToolSetBackend',
    'ToolSetRegistration',
    'backend_snapshot',
    'dry_run_capable',
    'public_tool_members',
    'register_connector',
    'register_tools',
    'require_permissions',
    'resolve_toolset_backend',
    'resolve_connector_tools',
    'spec_ref_for',
    'toolset_contract_specs',
    'toolset',
]
