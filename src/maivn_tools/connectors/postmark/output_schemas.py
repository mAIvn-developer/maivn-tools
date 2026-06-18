# pyright: strict
"""First-class output schemas for the Postmark toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Postmark API payloads: each
schema mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``template_ref`` or
``message_ref`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_TEMPLATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "template_ref": {"type": "string"},
        "name": {"type": "string"},
        "alias": {"type": "string"},
        "template_type": {"type": "string"},
        "active": {"type": "boolean"},
        "template_id": {"type": ["integer", "null"]},
    },
    "required": ["template_ref"],
}

_MESSAGE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "from_address": {"type": "string"},
        "to": {"type": "array", "items": {"type": "string"}},
        "subject": {"type": "string"},
        "status": {"type": "string"},
        "received_at": {"type": "string"},
        "message_id": {"type": "string"},
    },
    "required": ["message_ref"],
}


# MARK: - Tool output schemas

LIST_TEMPLATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "templates": {"type": "array", "items": _TEMPLATE_SUMMARY},
        "count": {"type": "integer"},
        "total_count": {"type": ["integer", "null"]},
    },
    "required": ["templates", "count"],
}

LIST_OUTBOUND_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
        "count": {"type": "integer"},
        "total_count": {"type": ["integer", "null"]},
    },
    "required": ["messages", "count"],
}


__all__ = [
    "LIST_OUTBOUND_MESSAGES_OUTPUT",
    "LIST_TEMPLATES_OUTPUT",
]
