# pyright: strict
"""First-class output schemas for the Tableau toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Tableau REST payloads: each
schema mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``workbook_ref`` or
``project_name`` without guessing.

Raw Tableau IDs (``project_id``/``workbook_id``/``view_id``/``datasource_id``)
appear only when a tool is called with ``include_ids=True``; the schemas list
them as optional properties.
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
        "content_permissions": {"type": "string"},
        "project_id": {"type": "string"},
    },
    "required": ["project_ref", "name"],
}

_WORKBOOK_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "workbook_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "owner_name": {"type": "string"},
        "project_name": {"type": "string"},
        "updated_at": {"type": "string"},
        "workbook_id": {"type": "string"},
    },
    "required": ["workbook_ref", "name"],
}

_VIEW_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "view_ref": {"type": "string"},
        "name": {"type": "string"},
        "content_url": {"type": "string"},
        "view_url_name": {"type": "string"},
        "view_id": {"type": "string"},
    },
    "required": ["view_ref", "name"],
}

_DATASOURCE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "datasource_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "owner_name": {"type": "string"},
        "project_name": {"type": "string"},
        "updated_at": {"type": "string"},
        "datasource_id": {"type": "string"},
    },
    "required": ["datasource_ref", "name"],
}


# MARK: - Tool output schemas

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "projects": {"type": "array", "items": _PROJECT_SUMMARY},
        "pagination": {"type": ["object", "null"]},
    },
    "required": ["projects"],
}

LIST_WORKBOOKS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "workbooks": {"type": "array", "items": _WORKBOOK_SUMMARY},
        "pagination": {"type": ["object", "null"]},
    },
    "required": ["workbooks"],
}

LIST_VIEWS_FOR_WORKBOOK_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "views": {"type": "array", "items": _VIEW_SUMMARY},
    },
    "required": ["views"],
}

LIST_DATASOURCES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "datasources": {"type": "array", "items": _DATASOURCE_SUMMARY},
        "pagination": {"type": ["object", "null"]},
    },
    "required": ["datasources"],
}


__all__ = [
    "LIST_DATASOURCES_OUTPUT",
    "LIST_PROJECTS_OUTPUT",
    "LIST_VIEWS_FOR_WORKBOOK_OUTPUT",
    "LIST_WORKBOOKS_OUTPUT",
]
