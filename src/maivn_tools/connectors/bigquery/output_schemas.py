# pyright: strict
"""First-class output schemas for the BigQuery toolset.

These document the connector-owned, normalized shapes that the list tools
return by default (``include_metadata=True``). They are not the raw BigQuery
REST payloads: each schema mirrors exactly the compact dict the connector
builds via ``_dataset_summary`` / ``_table_summary``, so the assignment planner
and repair loop can resolve fields like ``dataset_id`` or ``table_id`` without
guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_DATASET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "dataset_ref": {"type": "string"},
        "dataset_id": {"type": "string"},
        "project_id": {"type": "string"},
        "location": {"type": "string"},
        "friendly_name": {"type": "string"},
        "labels": {"type": "object"},
    },
    "required": ["dataset_ref", "dataset_id"],
}

_TABLE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table_ref": {"type": "string"},
        "table_id": {"type": "string"},
        "dataset_id": {"type": "string"},
        "project_id": {"type": "string"},
        "type": {"type": "string"},
        "friendly_name": {"type": "string"},
        "labels": {"type": "object"},
    },
    "required": ["table_ref", "table_id"],
}


# MARK: - Tool output schemas

LIST_DATASETS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "datasets": {"type": "array", "items": _DATASET_SUMMARY},
        "nextPageToken": {"type": "string"},
    },
    "required": ["datasets"],
}

LIST_TABLES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "tables": {"type": "array", "items": _TABLE_SUMMARY},
        "nextPageToken": {"type": "string"},
    },
    "required": ["tables"],
}


__all__ = [
    "LIST_DATASETS_OUTPUT",
    "LIST_TABLES_OUTPUT",
]
