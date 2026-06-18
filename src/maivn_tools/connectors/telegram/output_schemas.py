# pyright: strict
"""First-class output schemas for the Telegram toolset.

These document the connector-owned, normalized shape that :meth:`get_updates`
returns by default (``include_metadata=True``). It is not the raw Telegram
``getUpdates`` payload: the schema mirrors exactly the compact dict the
connector's ``_update_summary`` builder produces, so the assignment planner and
repair loop can resolve fields like ``update_ref`` or ``chat_id`` without
guessing.

When the tool is called with ``include_metadata=False`` it returns the raw
provider response instead; this schema describes the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Update summary (mirrors the connector's ``_update_summary`` builder)

_UPDATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "update_ref": {"type": "string"},
        "type": {"type": "string"},
        "chat_title": {"type": "string"},
        "sender": {"type": "string"},
        "text": {"type": "string"},
        # Present only when ``include_ids=True``.
        "update_id": {"type": ["integer", "null"]},
        "message_id": {"type": "integer"},
        "callback_query_id": {"type": ["string", "integer"]},
        "chat_id": {"type": ["integer", "string"]},
    },
    "required": ["update_ref", "type"],
}


# MARK: - Tool output schemas

GET_UPDATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "updates": {"type": "array", "items": _UPDATE_SUMMARY},
    },
    "required": ["updates"],
}


__all__ = [
    "GET_UPDATES_OUTPUT",
]
