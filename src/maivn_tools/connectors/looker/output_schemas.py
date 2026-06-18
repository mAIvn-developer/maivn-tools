# pyright: strict
"""First-class output schemas for the Looker toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return when Looker hands back a JSON array. They are not the raw
Looker API 4.0 payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``look_ref`` or ``dashboard_ref`` without guessing.

Raw Looker IDs (``look_id``/``dashboard_id``/``user_id``) appear only when the
tool is called with ``include_ids=True``; they are documented here as optional
properties and are not required.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_LOOK_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "look_ref": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "view_count": {"type": "integer"},
        "updated_at": {"type": "string"},
        "look_id": {"type": ["integer", "string"]},
    },
    "required": ["look_ref"],
}

_DASHBOARD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "dashboard_ref": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "view_count": {"type": "integer"},
        "updated_at": {"type": "string"},
        "dashboard_id": {"type": ["integer", "string"]},
    },
    "required": ["dashboard_ref"],
}

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "is_disabled": {"type": "boolean"},
        "user_id": {"type": ["integer", "string"]},
    },
    "required": ["user_ref"],
}


# MARK: - Tool output schemas

LIST_LOOKS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "looks": {"type": "array", "items": _LOOK_SUMMARY},
    },
    "required": ["looks"],
}

LIST_DASHBOARDS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "dashboards": {"type": "array", "items": _DASHBOARD_SUMMARY},
    },
    "required": ["dashboards"],
}

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
    },
    "required": ["users"],
}


__all__ = [
    "LIST_DASHBOARDS_OUTPUT",
    "LIST_LOOKS_OUTPUT",
    "LIST_USERS_OUTPUT",
]
