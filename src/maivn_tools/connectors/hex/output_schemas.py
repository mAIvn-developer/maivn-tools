# pyright: strict
"""First-class output schemas for the Hex toolset.

These document the connector-owned, normalized shape that :meth:`list_projects`
returns by default. It is not the raw Hex ``/api/v1/projects`` payload: the
schema mirrors exactly the compact dict the connector's ``_project_summary``
builder produces, so the assignment planner and repair loop can resolve fields
like ``project_ref`` without guessing.

The raw Hex project ID (``project_id``) is omitted unless the tool is called
with ``include_ids=True``; this schema describes the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_project_summary`` builder)

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "creator_email": {"type": "string"},
        "last_edited_at": {"type": "string"},
        "archived": {"type": "boolean"},
        "project_id": {"type": "string"},
    },
    "required": ["project_ref"],
}


# MARK: - Tool output schemas

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "projects": {"type": "array", "items": _PROJECT_SUMMARY},
        "nextAfter": {"type": ["string", "null"]},
    },
    "required": ["projects"],
}


__all__ = [
    "LIST_PROJECTS_OUTPUT",
]
