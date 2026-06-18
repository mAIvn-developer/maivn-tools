# pyright: strict
"""First-class output schemas for the TikTok toolset.

These document the connector-owned, normalized ``_video_summary`` shape that
``list_videos`` returns by default (``include_metadata=True``). It is not the
raw TikTok video-list payload: the schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``video_ref`` or ``url`` without guessing.

When ``list_videos`` is called with ``include_metadata=False`` it returns the
raw provider response instead; this schema describes the default normalized
form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors the connector's ``_video_summary`` builder)

_VIDEO_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "video_ref": {"type": "string"},
        "title": {"type": "string"},
        "author": {"type": "string"},
        "posted_at": {"type": ["string", "integer"]},
        "view_count": {"type": "integer"},
        "like_count": {"type": "integer"},
        "comment_count": {"type": "integer"},
        "share_count": {"type": "integer"},
        "duration": {"type": "integer"},
        "url": {"type": "string"},
        "video_id": {"type": "string"},
    },
    "required": ["video_ref"],
}


# MARK: - Tool output schemas

LIST_VIDEOS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "videos": {"type": "array", "items": _VIDEO_SUMMARY},
        "cursor": {"type": ["integer", "null"]},
        "has_more": {"type": ["boolean", "null"]},
    },
    "required": ["videos"],
}


__all__ = ["LIST_VIDEOS_OUTPUT"]
