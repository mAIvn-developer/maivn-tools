# pyright: strict
"""First-class output schemas for the Buffer toolset.

These document the connector-owned, normalized shape that the queue-listing
tools return by default (``include_metadata=True``). It is not the raw Buffer
GraphQL ``posts`` connection: the schema mirrors exactly the compact dict the
connector builds in ``_list_posts`` / ``_update_summary``, so the assignment
planner and repair loop can resolve fields like ``update_ref`` or
``end_cursor`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider connection instead; this schema describes the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors the connector's ``_update_summary`` builder)

_UPDATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "update_ref": {"type": "string"},
        "text": {"type": "string"},
        "status": {"type": "string"},
        "scheduled_at": {"type": ["integer", "string", "null"]},
        "sent_at": {"type": ["integer", "string", "null"]},
        "service": {"type": "string"},
        "author": {"type": "string"},
        "update_id": {"type": "string"},
        "profile_id": {"type": "string"},
    },
    "required": ["update_ref"],
}


# MARK: - Tool output schema

LIST_UPDATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "updates": {"type": "array", "items": _UPDATE_SUMMARY},
        "has_next_page": {"type": "boolean"},
        "end_cursor": {"type": ["string", "null"]},
    },
    "required": ["updates"],
}


__all__ = [
    "LIST_UPDATES_OUTPUT",
]
