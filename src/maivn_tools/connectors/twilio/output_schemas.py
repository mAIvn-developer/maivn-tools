# pyright: strict
"""First-class output schemas for the Twilio toolset.

These document the connector-owned, normalized ``_message_summary`` shape that
``list_messages`` returns. They are not the raw Twilio REST payloads: the schema
mirrors exactly the compact dict the connector builds, so the assignment planner
and repair loop can resolve fields like ``message_ref`` or ``status`` without
guessing. The raw ``message_sid`` only appears when called with ``include_ids``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_message_summary`` builder)

_MESSAGE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "from": {"type": "string"},
        "to": {"type": "string"},
        "status": {"type": "string"},
        "direction": {"type": "string"},
        "body": {"type": "string"},
        "date_sent": {"type": "string"},
        "price": {"type": ["string", "null"]},
        "message_sid": {"type": "string"},
    },
    "required": ["message_ref", "from", "to", "status"],
}


# MARK: - Tool output schemas

LIST_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
        "next_page_uri": {"type": ["string", "null"]},
        "previous_page_uri": {"type": ["string", "null"]},
        "page": {"type": "integer"},
    },
    "required": ["messages"],
}


__all__ = [
    "LIST_MESSAGES_OUTPUT",
]
