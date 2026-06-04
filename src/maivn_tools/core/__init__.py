"""Core connector primitives: protocols, metadata, permissions, and registration."""

# pyright: strict

from __future__ import annotations

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
    "AuthMode",
    "ConnectionHealth",
    "ConnectionMetadata",
    "ConnectionStatus",
    "Connector",
    "ConnectorTool",
    "DryRunOutcome",
    "DryRunPlan",
    "PERMISSION_FLAG_NAMES",
    "PermissionFlag",
    "PermissionSet",
    "ProviderCapability",
    "ProviderMetadata",
    "TokenMetadata",
    "ToolFactory",
    "ToolProvider",
    "dry_run_capable",
    "register_connector",
    "register_tools",
    "require_permissions",
    "resolve_connector_tools",
    "toolset",
]
