# pyright: strict
"""First-class output schemas for the LinkedIn toolset.

These document the connector-owned, normalized shapes that the list tools
return by default (``include_metadata=True``). They are not the raw LinkedIn
REST payloads: each schema mirrors exactly the compact dict the connector
builds via ``_post_summary`` / ``_comment_summary``, so the assignment planner
and repair loop can resolve fields like ``post_ref`` or ``comment_ref`` without
guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_POST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "post_ref": {"type": "string"},
        "author": {"type": "string"},
        "commentary": {"type": "string"},
        "posted_at": {"type": "string"},
        "visibility": {"type": "string"},
        "lifecycle_state": {"type": "string"},
        "post_urn": {"type": "string"},
    },
    "required": ["post_ref"],
}

_COMMENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "comment_ref": {"type": "string"},
        "actor": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "comment_id": {"type": "string"},
    },
    "required": ["comment_ref"],
}


# MARK: - Tool output schemas

LIST_POSTS_FOR_AUTHOR_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "posts": {"type": "array", "items": _POST_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["posts"],
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
    "LIST_POSTS_FOR_AUTHOR_OUTPUT",
]
