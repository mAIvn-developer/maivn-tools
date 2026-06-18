# pyright: strict
"""First-class output schemas for the Auth0 toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Auth0 Management API
payloads: each schema mirrors exactly the compact dict the connector builds
(``user_ref``, ``role_ref``, ...), so the assignment planner and repair loop can
resolve fields without guessing.

Tools that return the raw provider response unchanged (``get_user``,
``create_user``, ``update_user``, ``list_logs``) are intentionally not described
here. Raw provider IDs (``user_id``, ``role_id``, ...) are only present when a
tool is called with ``include_ids=True``, so they are optional in these schemas.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "email": {"type": "string"},
        "name": {"type": "string"},
        "blocked": {"type": "boolean"},
        "email_verified": {"type": "boolean"},
        "last_login": {"type": "string"},
        "logins_count": {"type": "integer"},
        "user_id": {"type": "string"},
    },
    "required": ["user_ref"],
}

_ROLE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "role_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "role_id": {"type": "string"},
    },
    "required": ["role_ref"],
}

_CONNECTION_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "connection_ref": {"type": "string"},
        "name": {"type": "string"},
        "strategy": {"type": "string"},
        "is_domain_connection": {"type": "boolean"},
        "connection_id": {"type": "string"},
    },
    "required": ["connection_ref"],
}

_CLIENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "app_ref": {"type": "string"},
        "name": {"type": "string"},
        "app_type": {"type": "string"},
        "is_first_party": {"type": "boolean"},
        "client_id": {"type": "string"},
    },
    "required": ["app_ref"],
}

_ORG_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "org_ref": {"type": "string"},
        "name": {"type": "string"},
        "display_name": {"type": "string"},
        "org_id": {"type": "string"},
    },
    "required": ["org_ref"],
}


# MARK: - Tool output schemas

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"users": {"type": "array", "items": _USER_SUMMARY}},
    "required": ["users"],
}

LIST_ROLES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"roles": {"type": "array", "items": _ROLE_SUMMARY}},
    "required": ["roles"],
}

LIST_CONNECTIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"connections": {"type": "array", "items": _CONNECTION_SUMMARY}},
    "required": ["connections"],
}

LIST_CLIENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"apps": {"type": "array", "items": _CLIENT_SUMMARY}},
    "required": ["apps"],
}

LIST_ORGANIZATIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"organizations": {"type": "array", "items": _ORG_SUMMARY}},
    "required": ["organizations"],
}


__all__ = [
    "LIST_CLIENTS_OUTPUT",
    "LIST_CONNECTIONS_OUTPUT",
    "LIST_ORGANIZATIONS_OUTPUT",
    "LIST_ROLES_OUTPUT",
    "LIST_USERS_OUTPUT",
]
