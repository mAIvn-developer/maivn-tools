# pyright: strict
"""First-class output schemas for the Dropbox toolset.

These document the connector-owned, normalized shape that ``list_folder``,
``list_folder_continue``, and ``search`` return by default
(``include_metadata=True``). They are not the raw Dropbox API payloads: each
schema mirrors exactly the compact dict the connector builds via
``_summarize_dropbox_entries`` / ``_dropbox_entry_summary``, so the assignment
planner and repair loop can resolve fields like ``path`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entry summary (mirrors ``_dropbox_entry_summary``)

_ENTRY_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "file_ref": {"type": "string"},
        "folder_ref": {"type": "string"},
        "entry_ref": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string"},
        "path": {"type": "string"},
        "size": {"type": "integer"},
        "modified_time": {"type": "string"},
        "id": {"type": "string"},
        "rev": {"type": "string"},
    },
    "required": ["name", "kind", "path"],
}


# MARK: - Tool output schema (mirrors ``_summarize_dropbox_entries``)

_LISTING_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ENTRY_SUMMARY},
        "has_more": {"type": "boolean"},
        "cursor": {"type": "string"},
    },
    "required": ["items"],
}

LIST_FOLDER_OUTPUT: dict[str, JsonValue] = _LISTING_OUTPUT
LIST_FOLDER_CONTINUE_OUTPUT: dict[str, JsonValue] = _LISTING_OUTPUT
SEARCH_OUTPUT: dict[str, JsonValue] = _LISTING_OUTPUT


__all__ = [
    "LIST_FOLDER_CONTINUE_OUTPUT",
    "LIST_FOLDER_OUTPUT",
    "SEARCH_OUTPUT",
]
