# pyright: strict
"""First-class output schemas for the Duo Security toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools build from the raw Duo Admin API ``response`` array. They are not the
raw Duo payloads: each schema mirrors exactly the compact dict the connector
constructs, so the assignment planner and repair loop can resolve fields like
``user_ref`` or ``username`` without guessing.

Raw ``user_id`` / ``group_id`` / ``phone_id`` are omitted unless the tool is
called with ``include_ids=True``; the schemas list them as optional properties.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "username": {"type": "string"},
        "email": {"type": "string"},
        "realname": {"type": "string"},
        "status": {"type": "string"},
        "last_login": {"type": ["string", "null"]},
        "user_id": {"type": "string"},
    },
    "required": ["user_ref", "username"],
}

_PHONE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "phone_ref": {"type": "string"},
        "number": {"type": "string"},
        "name": {"type": "string"},
        "platform": {"type": "string"},
        "type": {"type": "string"},
        "activated": {"type": "boolean"},
        "phone_id": {"type": "string"},
    },
    "required": ["phone_ref"],
}

_GROUP_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "group_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "status": {"type": "string"},
        "mobile_otp_enabled": {"type": "boolean"},
        "push_enabled": {"type": "boolean"},
        "group_id": {"type": "string"},
    },
    "required": ["group_ref"],
}


# MARK: - Tool output schemas

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
        "metadata": {"type": "object"},
    },
    "required": ["users"],
}

LIST_PHONES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "phones": {"type": "array", "items": _PHONE_SUMMARY},
    },
    "required": ["phones"],
}

LIST_GROUPS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "groups": {"type": "array", "items": _GROUP_SUMMARY},
    },
    "required": ["groups"],
}


__all__ = [
    "LIST_GROUPS_OUTPUT",
    "LIST_PHONES_OUTPUT",
    "LIST_USERS_OUTPUT",
]
