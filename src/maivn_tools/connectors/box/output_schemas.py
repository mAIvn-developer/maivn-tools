# pyright: strict
"""First-class output schemas for the Box toolset.

These document the connector-owned, normalized shape that the browse/search
tools return by default (``include_metadata=True``). They are not the raw Box
``/items``/``/search`` payloads: each schema mirrors exactly the compact dict
the connector builds in ``_summarize_box_entries`` / ``_box_entry_summary``, so
the assignment planner and repair loop can resolve fields like ``file_ref`` or
``folder_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entry summary (mirrors ``_box_entry_summary``)

# A single normalized entry. ``_box_entry_summary`` keys the ref/id by entry
# type, so a listing may carry ``file_ref``/``folder_ref``/``item_ref`` and,
# when ``include_ids=True``, ``file_id``/``folder_id``/``id`` plus ``parent_id``.
_ENTRY_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "file_ref": {"type": "string"},
        "folder_ref": {"type": "string"},
        "item_ref": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string"},
        "size": {"type": "integer"},
        "modified_time": {"type": "string"},
        "owner": {"type": "string"},
        "file_id": {"type": "string"},
        "folder_id": {"type": "string"},
        "id": {"type": "string"},
        "parent_id": {"type": "string"},
    },
    "required": ["name", "kind"],
}


# MARK: - Listing wrapper (mirrors ``_summarize_box_entries``)

_ENTRY_LISTING: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ENTRY_SUMMARY},
        "total_count": {"type": "integer"},
        "offset": {"type": "integer"},
        "limit": {"type": "integer"},
    },
    "required": ["items"],
}


# MARK: - Tool output schemas

LIST_FOLDER_ITEMS_OUTPUT: dict[str, JsonValue] = _ENTRY_LISTING
SEARCH_OUTPUT: dict[str, JsonValue] = _ENTRY_LISTING


__all__ = [
    "LIST_FOLDER_ITEMS_OUTPUT",
    "SEARCH_OUTPUT",
]
