# pyright: strict
"""First-class output schemas for the Brevo toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Brevo payloads: each schema
mirrors exactly the compact dict the connector builds, so the assignment planner
and repair loop can resolve fields like ``contact_ref`` or ``list_ref`` without
guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_CONTACT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "contact_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "email_blacklisted": {"type": "boolean"},
        "sms_blacklisted": {"type": "boolean"},
        "list_ids": {"type": "array", "items": {"type": "integer"}},
        "contact_id": {"type": ["integer", "null"]},
    },
    "required": ["contact_ref", "name", "email"],
}

_LIST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "list_ref": {"type": "string"},
        "name": {"type": "string"},
        "total_subscribers": {"type": "integer"},
        "total_blacklisted": {"type": "integer"},
        "folder_id": {"type": ["integer", "null"]},
        "list_id": {"type": ["integer", "null"]},
    },
    "required": ["list_ref", "name"],
}

_CAMPAIGN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "campaign_ref": {"type": "string"},
        "name": {"type": "string"},
        "subject": {"type": "string"},
        "type": {"type": "string"},
        "status": {"type": "string"},
        "scheduled_at": {"type": "string"},
        "campaign_id": {"type": ["integer", "null"]},
    },
    "required": ["campaign_ref", "name"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], count: int, total: int|null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "count": {"type": "integer"},
            "total": {"type": ["integer", "null"]},
        },
        "required": [item_key, "count"],
    }


# MARK: - Tool output schemas

LIST_CONTACTS_OUTPUT: dict[str, JsonValue] = _listing("contacts", _CONTACT_SUMMARY)
LIST_LISTS_OUTPUT: dict[str, JsonValue] = _listing("lists", _LIST_SUMMARY)
LIST_EMAIL_CAMPAIGNS_OUTPUT: dict[str, JsonValue] = _listing("campaigns", _CAMPAIGN_SUMMARY)


__all__ = [
    "LIST_CONTACTS_OUTPUT",
    "LIST_EMAIL_CAMPAIGNS_OUTPUT",
    "LIST_LISTS_OUTPUT",
]
