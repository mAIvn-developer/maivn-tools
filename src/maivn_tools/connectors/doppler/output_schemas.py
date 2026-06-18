# pyright: strict
"""First-class output schemas for the Doppler toolset.

These document the connector-owned, normalized shapes that the list tools
return by default. They are not the raw Doppler API payloads: each schema
mirrors exactly the compact dict the connector builds via its ``_*_summary``
helpers, so the assignment planner and repair loop can resolve fields like
``project_ref`` or ``config_ref`` without guessing.

When a list tool is called with ``include_ids=True`` it adds the raw slug
field (``project_slug``/``config_slug``); ``list_secrets`` with
``include_values=True`` returns the raw provider payload instead. These
schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "created_at": {"type": "string"},
        "project_slug": {"type": "string"},
    },
    "required": ["project_ref", "name"],
}

_CONFIG_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "config_ref": {"type": "string"},
        "name": {"type": "string"},
        "environment": {"type": "string"},
        "root": {"type": "boolean"},
        "locked": {"type": "boolean"},
        "config_slug": {"type": "string"},
    },
    "required": ["config_ref", "name"],
}

_SECRET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "secret_ref": {"type": "string"},
        "key": {"type": "string"},
        "value_type": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["secret_ref", "key"],
}


# MARK: - Tool output schemas

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "projects": {"type": "array", "items": _PROJECT_SUMMARY},
        "page": {"type": "integer"},
    },
    "required": ["projects"],
}

LIST_CONFIGS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "configs": {"type": "array", "items": _CONFIG_SUMMARY},
        "project": {"type": "string"},
    },
    "required": ["configs"],
}

LIST_SECRETS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "secrets": {"type": "array", "items": _SECRET_SUMMARY},
        "project": {"type": "string"},
        "config": {"type": "string"},
    },
    "required": ["secrets"],
}


__all__ = [
    "LIST_CONFIGS_OUTPUT",
    "LIST_PROJECTS_OUTPUT",
    "LIST_SECRETS_OUTPUT",
]
