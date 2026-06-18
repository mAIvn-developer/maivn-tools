# pyright: strict
"""First-class output schemas for the Threads toolset.

These document the connector-owned, normalized summary shapes that the
``list_threads`` and ``list_replies`` tools return by default
(``include_metadata=True``). They are not the raw Threads Graph payloads:
each schema mirrors exactly the compact dict the connector builds via its
``_thread_summary`` / ``_reply_summary`` helpers, so the assignment planner
and repair loop can resolve fields like ``post_ref`` or ``reply_ref``
without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_THREAD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "post_ref": {"type": "string"},
        "author": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "media_type": {"type": "string"},
        "permalink": {"type": "string"},
        "post_id": {"type": "string"},
    },
    "required": ["post_ref"],
}

_REPLY_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "reply_ref": {"type": "string"},
        "author": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "permalink": {"type": "string"},
        "reply_id": {"type": "string"},
    },
    "required": ["reply_ref"],
}


# MARK: - Tool output schemas

LIST_THREADS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "posts": {"type": "array", "items": _THREAD_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["posts"],
}

LIST_REPLIES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "replies": {"type": "array", "items": _REPLY_SUMMARY},
        "paging": {"type": ["object", "null"]},
    },
    "required": ["replies"],
}


__all__ = [
    "LIST_REPLIES_OUTPUT",
    "LIST_THREADS_OUTPUT",
]
