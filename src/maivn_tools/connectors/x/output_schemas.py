# pyright: strict
"""First-class output schemas for the X (Twitter) toolset.

These document the connector-owned, normalized summary shapes that the
read/list tools return by default (``include_metadata=True``). They are not
the raw X v2 API payloads: each schema mirrors exactly the compact dict the
connector builds via ``_tweet_summary`` / ``_user_summary``, so the assignment
planner and repair loop can resolve fields like ``tweet_ref`` or ``handle``
without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_TWEET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "tweet_ref": {"type": "string"},
        "author": {"type": "string"},
        "text": {"type": "string"},
        "posted_at": {"type": "string"},
        "like_count": {"type": "integer"},
        "repost_count": {"type": "integer"},
        "reply_count": {"type": "integer"},
        "url": {"type": "string"},
        "tweet_id": {"type": "string"},
        "author_id": {"type": "string"},
    },
    "required": ["tweet_ref"],
}

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "handle": {"type": "string"},
        "name": {"type": "string"},
        "follower_count": {"type": "integer"},
        "following_count": {"type": "integer"},
        "url": {"type": "string"},
        "user_id": {"type": "string"},
    },
    "required": ["user_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], next_token: str|null, result_count: int}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "next_token": {"type": ["string", "null"]},
            "result_count": {"type": "integer"},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

SEARCH_RECENT_TWEETS_OUTPUT: dict[str, JsonValue] = _listing("tweets", _TWEET_SUMMARY)
GET_USER_TWEETS_OUTPUT: dict[str, JsonValue] = _listing("tweets", _TWEET_SUMMARY)
GET_USER_MENTIONS_OUTPUT: dict[str, JsonValue] = _listing("tweets", _TWEET_SUMMARY)
GET_FOLLOWERS_OUTPUT: dict[str, JsonValue] = _listing("users", _USER_SUMMARY)
GET_FOLLOWING_OUTPUT: dict[str, JsonValue] = _listing("users", _USER_SUMMARY)


__all__ = [
    "GET_FOLLOWERS_OUTPUT",
    "GET_FOLLOWING_OUTPUT",
    "GET_USER_MENTIONS_OUTPUT",
    "GET_USER_TWEETS_OUTPUT",
    "SEARCH_RECENT_TWEETS_OUTPUT",
]
