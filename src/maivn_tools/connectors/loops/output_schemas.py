# pyright: strict
"""First-class output schemas for the Loops toolset.

These document the connector-owned, normalized shape that ``list_mailing_lists``
returns by default. The schema mirrors exactly the compact dict the connector
builds via ``_list_summary`` (plus the wrapper envelope), not the raw Loops
``/lists`` payload. When the tool is called with ``include_raw=True`` it returns
the raw provider response instead; this schema describes the default form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors the connector's ``_list_summary`` builder)

_LIST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "list_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "is_public": {"type": ["boolean", "null"]},
        "list_id": {"type": "string"},
    },
    "required": ["list_ref"],
}

# MARK: - Tool output schemas

LIST_MAILING_LISTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "lists": {"type": "array", "items": _LIST_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["lists"],
}


__all__ = [
    "LIST_MAILING_LISTS_OUTPUT",
]
