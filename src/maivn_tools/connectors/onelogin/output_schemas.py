# pyright: strict
"""First-class output schemas for the OneLogin toolset.

These document the connector-owned, normalized shapes that the list/mutation
tools build from the raw OneLogin v2 responses. They are not the raw provider
payloads: each schema mirrors exactly the compact dict the connector
constructs (via the ``_*_summary`` builders or an explicit envelope), so the
assignment planner and repair loop can resolve fields like ``user_ref`` or
``assigned_role_ids`` without guessing.

Tools that return the raw provider resource unchanged (``get_user``,
``create_user``, ``update_user``, ``lock_user``, ``list_events``) are
provider-dependent and intentionally not annotated here.
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
        "status": {"type": "string"},
        "last_login": {"type": "string"},
        "locked_until": {"type": "string"},
        "user_id": {"type": "integer"},
    },
    "required": ["user_ref"],
}

_ROLE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "role_ref": {"type": "string"},
        "name": {"type": "string"},
        "role_id": {"type": "integer"},
    },
    "required": ["role_ref"],
}

_APP_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "app_ref": {"type": "string"},
        "name": {"type": "string"},
        "auth_method": {"type": "string"},
        "connector_id": {"type": "integer"},
        "visible": {"type": "boolean"},
        "app_id": {"type": "integer"},
    },
    "required": ["app_ref"],
}


# MARK: - Tool output schemas

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
        "after_cursor": {"type": ["string", "null"]},
        "before_cursor": {"type": ["string", "null"]},
        "total_count": {"type": ["string", "null"]},
    },
    "required": ["users"],
}

LIST_ROLES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "roles": {"type": "array", "items": _ROLE_SUMMARY},
    },
    "required": ["roles"],
}

LIST_APPS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "apps": {"type": "array", "items": _APP_SUMMARY},
    },
    "required": ["apps"],
}

DELETE_USER_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_id": {"type": "integer"},
        "deleted": {"type": "boolean"},
        "status": {"type": "integer"},
    },
    "required": ["user_id", "deleted"],
}

ASSIGN_ROLE_TO_USER_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_id": {"type": "integer"},
        "assigned_role_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["user_id", "assigned_role_ids"],
}


__all__ = [
    "ASSIGN_ROLE_TO_USER_OUTPUT",
    "DELETE_USER_OUTPUT",
    "LIST_APPS_OUTPUT",
    "LIST_ROLES_OUTPUT",
    "LIST_USERS_OUTPUT",
]
