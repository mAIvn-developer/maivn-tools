# pyright: strict
"""First-class output schemas for the Kubernetes toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_metadata=True``). They are not the raw
Kubernetes API payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``name`` or ``namespace`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
The optional ``uid``/``resource_version`` fields appear only when
``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_NAMESPACE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "namespace_ref": {"type": "string"},
        "name": {"type": "string"},
        "phase": {"type": "string"},
        "created_at": {"type": "string"},
        "uid": {"type": "string"},
    },
    "required": ["namespace_ref", "name"],
}

_POD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pod_ref": {"type": "string"},
        "name": {"type": "string"},
        "namespace": {"type": "string"},
        "phase": {"type": "string"},
        "ready": {"type": "string"},
        "node": {"type": "string"},
        "start_time": {"type": "string"},
        "uid": {"type": "string"},
        "resource_version": {"type": "string"},
    },
    "required": ["pod_ref", "name", "namespace"],
}

_DEPLOYMENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "deployment_ref": {"type": "string"},
        "name": {"type": "string"},
        "namespace": {"type": "string"},
        "replicas": {"type": "integer"},
        "ready_replicas": {"type": "integer"},
        "available_replicas": {"type": "integer"},
        "uid": {"type": "string"},
        "resource_version": {"type": "string"},
    },
    "required": ["deployment_ref", "name", "namespace"],
}

_SERVICE_PORT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "port": {"type": "integer"},
        "target_port": {"type": ["integer", "string"]},
        "protocol": {"type": "string"},
    },
}

_SERVICE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "service_ref": {"type": "string"},
        "name": {"type": "string"},
        "namespace": {"type": "string"},
        "type": {"type": "string"},
        "cluster_ip": {"type": "string"},
        "ports": {"type": "array", "items": _SERVICE_PORT},
        "uid": {"type": "string"},
    },
    "required": ["service_ref", "name", "namespace"],
}


# MARK: - Tool output schemas

LIST_NAMESPACES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "namespaces": {"type": "array", "items": _NAMESPACE_SUMMARY},
    },
    "required": ["namespaces"],
}

LIST_PODS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pods": {"type": "array", "items": _POD_SUMMARY},
        "continue": {"type": "string"},
    },
    "required": ["pods"],
}

LIST_DEPLOYMENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "deployments": {"type": "array", "items": _DEPLOYMENT_SUMMARY},
    },
    "required": ["deployments"],
}

LIST_SERVICES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "services": {"type": "array", "items": _SERVICE_SUMMARY},
    },
    "required": ["services"],
}


__all__ = [
    "LIST_DEPLOYMENTS_OUTPUT",
    "LIST_NAMESPACES_OUTPUT",
    "LIST_PODS_OUTPUT",
    "LIST_SERVICES_OUTPUT",
]
