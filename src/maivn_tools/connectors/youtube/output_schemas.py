# pyright: strict
"""First-class output schemas for the YouTube toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
read/search tools return by default (``include_metadata=True``). They are not
the raw YouTube Data API payloads: each schema mirrors exactly the compact dict
the connector builds, so the assignment planner and repair loop can resolve
fields like ``video_ref`` or ``comment_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_VIDEO_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "video_ref": {"type": "string"},
        "title": {"type": "string"},
        "channel": {"type": "string"},
        "posted_at": {"type": "string"},
        "description": {"type": "string"},
        "view_count": {"type": "integer"},
        "like_count": {"type": "integer"},
        "comment_count": {"type": "integer"},
        "duration": {"type": "string"},
        "url": {"type": "string"},
        "video_id": {"type": "string"},
        "channel_id": {"type": "string"},
    },
    "required": ["video_ref"],
}

_COMMENT_THREAD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "comment_ref": {"type": "string"},
        "author": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "like_count": {"type": "integer"},
        "reply_count": {"type": "integer"},
        "thread_id": {"type": "string"},
        "comment_id": {"type": "string"},
    },
    "required": ["comment_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], next_page_token, page_info}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "next_page_token": {"type": ["string", "null"]},
            "page_info": {"type": ["object", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_VIDEOS_OUTPUT: dict[str, JsonValue] = _listing("videos", _VIDEO_SUMMARY)
SEARCH_OUTPUT: dict[str, JsonValue] = _listing("videos", _VIDEO_SUMMARY)
LIST_COMMENT_THREADS_OUTPUT: dict[str, JsonValue] = _listing("comments", _COMMENT_THREAD_SUMMARY)


__all__ = [
    "LIST_COMMENT_THREADS_OUTPUT",
    "LIST_VIDEOS_OUTPUT",
    "SEARCH_OUTPUT",
]
