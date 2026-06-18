# pyright: strict
"""First-class output schemas for the Reddit toolset.

These document the connector-owned, normalized ``_post_summary`` shapes that the
listing tools return by default (``include_metadata=True``). They are not the raw
Reddit listing payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``post_ref`` or ``url`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw Reddit
listing instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_post_summary`` builder)

_POST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "post_ref": {"type": "string"},
        "title": {"type": "string"},
        "author": {"type": "string"},
        "subreddit": {"type": "string"},
        "posted_at": {"type": "number"},
        "score": {"type": "integer"},
        "num_comments": {"type": "integer"},
        "url": {"type": "string"},
        "selftext": {"type": "string"},
        "thing_id": {"type": "string"},
        "post_id": {"type": "string"},
    },
    "required": ["post_ref", "title"],
}


# MARK: - Tool output schemas

_POSTS_LISTING: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "posts": {"type": "array", "items": _POST_SUMMARY},
        "after": {"type": ["string", "null"]},
        "before": {"type": ["string", "null"]},
    },
    "required": ["posts"],
}

LIST_SUBREDDIT_POSTS_OUTPUT: dict[str, JsonValue] = _POSTS_LISTING
SEARCH_OUTPUT: dict[str, JsonValue] = _POSTS_LISTING


__all__ = [
    "LIST_SUBREDDIT_POSTS_OUTPUT",
    "SEARCH_OUTPUT",
]
