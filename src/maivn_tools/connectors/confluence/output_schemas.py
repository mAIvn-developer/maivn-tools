# pyright: strict
"""First-class output schemas for the Confluence toolset.

These document the connector-owned, normalized shapes that the list/search
tools return by default (``include_metadata=True``). They are not the raw
Confluence REST payloads: each schema mirrors exactly the compact dict the
connector builds via ``_summarize_content`` / ``_summarize_search`` and the
``_content_item_summary`` helper, so the assignment planner and repair loop can
resolve fields like ``page_ref`` or ``space_key`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror ``_content_item_summary`` and the search builder)

_CONTENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "page_ref": {"type": "string"},
        "title": {"type": "string"},
        "type": {"type": "string"},
        "status": {"type": "string"},
        "space_key": {"type": "string"},
        "version": {"type": "integer"},
        "url": {"type": "string"},
        "content_id": {"type": "string"},
    },
    "required": ["page_ref", "title", "type"],
}

_SEARCH_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "page_ref": {"type": "string"},
        "title": {"type": "string"},
        "type": {"type": "string"},
        "status": {"type": "string"},
        "space_key": {"type": "string"},
        "version": {"type": "integer"},
        "url": {"type": "string"},
        "content_id": {"type": "string"},
        "excerpt": {"type": "string"},
        "resultGlobalContainer": {"type": ["object", "string", "null"]},
    },
    "required": ["page_ref", "title"],
}


# MARK: - Tool output schemas

LIST_CONTENT_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "results": {"type": "array", "items": _CONTENT_SUMMARY},
        "start": {"type": "integer"},
        "limit": {"type": "integer"},
        "size": {"type": "integer"},
        "_links": {"type": "object"},
    },
    "required": ["results"],
}

SEARCH_CONTENT_OUTPUT: dict[str, JsonValue] = LIST_CONTENT_OUTPUT

SEARCH_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "results": {"type": "array", "items": _SEARCH_SUMMARY},
        "start": {"type": "integer"},
        "limit": {"type": "integer"},
        "size": {"type": "integer"},
        "totalSize": {"type": "integer"},
        "cqlQuery": {"type": "string"},
    },
    "required": ["results"],
}


__all__ = [
    "LIST_CONTENT_OUTPUT",
    "SEARCH_CONTENT_OUTPUT",
    "SEARCH_OUTPUT",
]
