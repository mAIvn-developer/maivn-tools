# pyright: strict
"""First-class output schemas for the Okta toolset.

These document the connector-owned, normalized shapes that the listing tools
build (via the ``_*_summary`` helpers). They are not the raw Okta payloads:
each schema mirrors exactly the compact dict the connector constructs, so the
assignment planner and repair loop can resolve fields like ``user_ref`` or
``next_after`` without guessing.

Tools that return the raw provider response unchanged (``get_user``,
``create_user``, ``update_user``, ``list_factors``, ``list_system_logs``) are
intentionally not described here.
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
        "login": {"type": "string"},
        "status": {"type": "string"},
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

_APP_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "app_ref": {"type": "string"},
        "name": {"type": "string"},
        "label": {"type": "string"},
        "status": {"type": "string"},
        "sign_on_mode": {"type": "string"},
        "app_id": {"type": "string"},
    },
    "required": ["app_ref"],
}


# MARK: - Tool output schemas

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
        "next_after": {"type": ["string", "null"]},
    },
    "required": ["users"],
}

LIST_GROUPS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "groups": {"type": "array", "items": _GROUP_SUMMARY},
        "next_after": {"type": ["string", "null"]},
    },
    "required": ["groups"],
}

LIST_APPLICATIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "apps": {"type": "array", "items": _APP_SUMMARY},
        "next_after": {"type": ["string", "null"]},
    },
    "required": ["apps"],
}


__all__ = [
    "LIST_APPLICATIONS_OUTPUT",
    "LIST_GROUPS_OUTPUT",
    "LIST_USERS_OUTPUT",
]
