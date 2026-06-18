# pyright: strict
"""First-class output schemas for the JumpCloud toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return. They are not the raw JumpCloud REST payloads: each schema
mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``user_ref`` or ``group_ref``
without guessing.

The raw provider ``*_id`` fields are only emitted when a tool is called with
``include_ids=True``; they are documented here as optional properties.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "email": {"type": "string"},
        "username": {"type": "string"},
        "name": {"type": "string"},
        "suspended": {"type": "boolean"},
        "activated": {"type": "boolean"},
        "last_login": {"type": "string"},
        "user_id": {"type": "string"},
    },
    "required": ["user_ref"],
}

_GROUP_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "group_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "type": {"type": "string"},
        "group_id": {"type": "string"},
    },
    "required": ["group_ref"],
}

_SYSTEM_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "system_ref": {"type": "string"},
        "hostname": {"type": "string"},
        "os": {"type": "string"},
        "version": {"type": "string"},
        "active": {"type": "boolean"},
        "last_contact": {"type": "string"},
        "system_id": {"type": "string"},
    },
    "required": ["system_ref"],
}

_APP_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "app_ref": {"type": "string"},
        "name": {"type": "string"},
        "sso_type": {"type": "string"},
        "active": {"type": "boolean"},
        "app_id": {"type": "string"},
    },
    "required": ["app_ref"],
}


# MARK: - Tool output schemas

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
        "totalCount": {"type": "integer"},
    },
    "required": ["users"],
}

LIST_USER_GROUPS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "groups": {"type": "array", "items": _GROUP_SUMMARY},
    },
    "required": ["groups"],
}

LIST_SYSTEMS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "systems": {"type": "array", "items": _SYSTEM_SUMMARY},
    },
    "required": ["systems"],
}

LIST_APPLICATIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "apps": {"type": "array", "items": _APP_SUMMARY},
    },
    "required": ["apps"],
}


__all__ = [
    "LIST_APPLICATIONS_OUTPUT",
    "LIST_SYSTEMS_OUTPUT",
    "LIST_USERS_OUTPUT",
    "LIST_USER_GROUPS_OUTPUT",
]
