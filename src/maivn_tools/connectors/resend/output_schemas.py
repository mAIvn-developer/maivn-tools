# pyright: strict
"""First-class output schemas for the Resend toolset.

These document the connector-owned, normalized shapes that the read/list tools
return by default. They are not the raw Resend payloads: each schema mirrors
exactly the compact dict the connector builds (via ``_contact_summary``), so
the assignment planner and repair loop can resolve fields like ``contact_ref``
or ``email`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_contact_summary`` builder)

_CONTACT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "contact_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "unsubscribed": {"type": "boolean"},
        "created_at": {"type": "string"},
        "contact_id": {"type": "string"},
    },
    "required": ["contact_ref", "email"],
}


# MARK: - Tool output schemas

LIST_CONTACTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "contacts": {"type": "array", "items": _CONTACT_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["contacts"],
}


__all__ = [
    "LIST_CONTACTS_OUTPUT",
]
