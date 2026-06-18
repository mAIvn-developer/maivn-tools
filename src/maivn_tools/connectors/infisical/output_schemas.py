# pyright: strict
"""First-class output schemas for the Infisical toolset.

These document the connector-owned, normalized shapes that ``list_projects``
and ``list_secrets`` build by default (``include_values=False``). They are not
the raw Infisical payloads: each schema mirrors exactly the compact dict the
connector's ``_project_summary`` / ``_secret_summary`` builders produce, so the
assignment planner and repair loop can resolve fields like ``project_ref`` or
``secret_ref`` without guessing.

The single-secret reads (``get_secret``) and write tools return the raw
provider response and are intentionally not described here.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "environments": {"type": "array", "items": {"type": "string"}},
        "workspace_id": {"type": "string"},
    },
    "required": ["project_ref", "name", "slug"],
}

_SECRET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "secret_ref": {"type": "string"},
        "key": {"type": "string"},
        "type": {"type": "string"},
        "comment": {"type": "string"},
        "updated_at": {"type": "string"},
        "secret_id": {"type": "string"},
        "secret_path": {"type": "string"},
    },
    "required": ["secret_ref", "key"],
}


# MARK: - Tool output schemas

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "projects": {"type": "array", "items": _PROJECT_SUMMARY},
    },
    "required": ["projects"],
}

LIST_SECRETS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "secrets": {"type": "array", "items": _SECRET_SUMMARY},
        "workspace_id": {"type": "string"},
        "environment": {"type": "string"},
        "secret_path": {"type": "string"},
    },
    "required": ["secrets"],
}


__all__ = [
    "LIST_PROJECTS_OUTPUT",
    "LIST_SECRETS_OUTPUT",
]
