# pyright: strict
"""First-class output schemas for the Mailchimp toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_raw=False``). They are not the raw
Mailchimp Marketing API payloads: each schema mirrors exactly the compact dict
the connector builds, so the assignment planner and repair loop can resolve
fields like ``list_ref`` or ``campaign_ref`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_LIST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "list_ref": {"type": "string"},
        "name": {"type": "string"},
        "member_count": {"type": "integer"},
        "unsubscribe_count": {"type": "integer"},
        "date_created": {"type": "string"},
        "list_id": {"type": "string"},
    },
    "required": ["list_ref", "name"],
}

_MEMBER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "subscriber_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "status": {"type": "string"},
        "timestamp_signup": {"type": "string"},
        "last_changed": {"type": "string"},
        "subscriber_id": {"type": "string"},
        "unique_email_id": {"type": "string"},
    },
    "required": ["subscriber_ref", "email"],
}

_CAMPAIGN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "campaign_ref": {"type": "string"},
        "title": {"type": "string"},
        "subject_line": {"type": "string"},
        "type": {"type": "string"},
        "status": {"type": "string"},
        "send_time": {"type": "string"},
        "emails_sent": {"type": "integer"},
        "campaign_id": {"type": "string"},
    },
    "required": ["campaign_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], count: int, total_items: int | null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "count": {"type": "integer"},
            "total_items": {"type": ["integer", "null"]},
        },
        "required": [item_key, "count"],
    }


# MARK: - Tool output schemas

LIST_LISTS_OUTPUT: dict[str, JsonValue] = _listing("lists", _LIST_SUMMARY)
LIST_MEMBERS_OUTPUT: dict[str, JsonValue] = _listing("subscribers", _MEMBER_SUMMARY)
LIST_CAMPAIGNS_OUTPUT: dict[str, JsonValue] = _listing("campaigns", _CAMPAIGN_SUMMARY)


__all__ = [
    "LIST_CAMPAIGNS_OUTPUT",
    "LIST_LISTS_OUTPUT",
    "LIST_MEMBERS_OUTPUT",
]
