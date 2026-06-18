# pyright: strict
"""First-class output schemas for the Instagram toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_metadata=True``). They are not the raw
Instagram Graph payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``media_ref`` or ``comment_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw Graph
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_MEDIA_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "media_ref": {"type": "string"},
        "caption": {"type": "string"},
        "media_type": {"type": "string"},
        "permalink": {"type": "string"},
        "posted_at": {"type": "string"},
        "like_count": {"type": "integer"},
        "comments_count": {"type": "integer"},
        "media_id": {"type": "string"},
    },
    "required": ["media_ref"],
}

_COMMENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "comment_ref": {"type": "string"},
        "author": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "like_count": {"type": "integer"},
        "comment_id": {"type": "string"},
    },
    "required": ["comment_ref"],
}


# MARK: - Tool output schemas

LIST_MEDIA_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "media": {"type": "array", "items": _MEDIA_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["media"],
}

LIST_COMMENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "comments": {"type": "array", "items": _COMMENT_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["comments"],
}


__all__ = [
    "LIST_COMMENTS_OUTPUT",
    "LIST_MEDIA_OUTPUT",
]
