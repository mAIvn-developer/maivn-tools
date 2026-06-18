# pyright: strict
"""First-class output schemas for the Mastodon toolset.

These document the connector-owned, normalized status summaries that the
timeline tools return by default (``include_metadata=True``). They are not the
raw Mastodon status payloads: each schema mirrors exactly the compact dict the
connector's ``_status_summary`` builder produces, so the assignment planner and
repair loop can resolve fields like ``status_ref`` or ``author`` without
guessing.

When a timeline tool is called with ``include_metadata=False`` it returns the
raw provider response instead; these schemas describe the default normalized
form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_status_summary`` builder)

_STATUS_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "status_ref": {"type": "string"},
        "author": {"type": "string"},
        "author_name": {"type": "string"},
        "content": {"type": "string"},
        "posted_at": {"type": "string"},
        "spoiler_text": {"type": "string"},
        "visibility": {"type": "string"},
        "favourites_count": {"type": "integer"},
        "reblogs_count": {"type": "integer"},
        "replies_count": {"type": "integer"},
        "url": {"type": "string"},
        "status_id": {"type": "string"},
    },
    "required": ["status_ref", "author"],
}


# MARK: - Tool output schemas

_STATUSES_LISTING: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "statuses": {"type": "array", "items": _STATUS_SUMMARY},
    },
    "required": ["statuses"],
}

HOME_TIMELINE_OUTPUT: dict[str, JsonValue] = _STATUSES_LISTING
PUBLIC_TIMELINE_OUTPUT: dict[str, JsonValue] = _STATUSES_LISTING
HASHTAG_TIMELINE_OUTPUT: dict[str, JsonValue] = _STATUSES_LISTING


__all__ = [
    "HASHTAG_TIMELINE_OUTPUT",
    "HOME_TIMELINE_OUTPUT",
    "PUBLIC_TIMELINE_OUTPUT",
]
