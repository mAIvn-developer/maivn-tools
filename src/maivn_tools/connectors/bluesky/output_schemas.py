# pyright: strict
"""First-class output schemas for the Bluesky toolset.

These document the connector-owned, normalized ``_post_summary`` /
``_actor_summary`` shapes that the read/list tools return by default
(``include_metadata=True``). They are not the raw XRPC payloads: each schema
mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``post_ref`` or ``handle``
without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
The ``uri`` / ``cid`` / ``rkey`` (post) and ``did`` (actor) fields are only
present when the tool is called with ``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_POST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "post_ref": {"type": "string"},
        "author": {"type": "string"},
        "author_name": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "like_count": {"type": "integer"},
        "repost_count": {"type": "integer"},
        "reply_count": {"type": "integer"},
        "url": {"type": "string"},
        "uri": {"type": "string"},
        "cid": {"type": "string"},
        "rkey": {"type": "string"},
    },
    "required": ["post_ref", "author"],
}

_ACTOR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "handle": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "url": {"type": "string"},
        "did": {"type": "string"},
    },
    "required": ["user_ref", "handle"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], cursor: str | null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "cursor": {"type": ["string", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

GET_TIMELINE_OUTPUT: dict[str, JsonValue] = _listing("posts", _POST_SUMMARY)
GET_AUTHOR_FEED_OUTPUT: dict[str, JsonValue] = _listing("posts", _POST_SUMMARY)
SEARCH_POSTS_OUTPUT: dict[str, JsonValue] = _listing("posts", _POST_SUMMARY)
GET_FOLLOWERS_OUTPUT: dict[str, JsonValue] = _listing("users", _ACTOR_SUMMARY)
GET_FOLLOWS_OUTPUT: dict[str, JsonValue] = _listing("users", _ACTOR_SUMMARY)


__all__ = [
    "GET_AUTHOR_FEED_OUTPUT",
    "GET_FOLLOWERS_OUTPUT",
    "GET_FOLLOWS_OUTPUT",
    "GET_TIMELINE_OUTPUT",
    "SEARCH_POSTS_OUTPUT",
]
