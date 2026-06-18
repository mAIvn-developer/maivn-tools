# pyright: strict
"""First-class output schemas for the Meta (Facebook) toolset.

These document the connector-owned, normalized shapes that the listing tools
return by default (``include_metadata=True``). They are not the raw Graph API
payloads: each schema mirrors exactly the compact dict the connector builds via
its ``_post_summary`` / ``_comment_summary`` helpers, so the assignment planner
and repair loop can resolve fields like ``post_ref`` or ``comment_ref`` without
guessing.

When a tool is called with ``include_metadata=False`` it returns the raw Graph
response instead; these schemas describe the default normalized form. The raw
``post_id`` / ``comment_id`` fields are only present when ``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_POST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "post_ref": {"type": "string"},
        "message": {"type": "string"},
        "posted_at": {"type": "string"},
        "permalink_url": {"type": "string"},
        "post_id": {"type": "string"},
    },
    "required": ["post_ref"],
}

_COMMENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "comment_ref": {"type": "string"},
        "author": {"type": "string"},
        "message": {"type": "string"},
        "posted_at": {"type": "string"},
        "like_count": {"type": "integer"},
        "comment_id": {"type": "string"},
    },
    "required": ["comment_ref"],
}


# MARK: - Tool output schemas

LIST_PAGE_POSTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "posts": {"type": "array", "items": _POST_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["posts"],
}

LIST_POST_COMMENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "comments": {"type": "array", "items": _COMMENT_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["comments"],
}


__all__ = [
    "LIST_PAGE_POSTS_OUTPUT",
    "LIST_POST_COMMENTS_OUTPUT",
]
