# pyright: strict
"""First-class output schemas for the email (IMAP) toolset.

These document the connector-owned, normalized shape that
:meth:`IMAPToolSet.search_messages` returns by default
(``include_metadata=True``). The schema mirrors exactly the compact dict the
connector builds from each fetched envelope -- it is not the raw IMAP wire
format -- so the assignment planner and repair loop can resolve fields like
``message_ref`` or ``uid`` without guessing.

When ``search_messages`` is called with ``include_metadata=False`` it returns a
bare ``{"mailbox": ..., "uids": [...]}`` list instead; this schema describes the
default summarized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_envelope_summary`` builder)

_MESSAGE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "uid": {"type": "integer"},
        "sender": {"type": "string"},
        "subject": {"type": "string"},
        "received_at": {"type": "string"},
        "flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["message_ref", "uid"],
}


# MARK: - Tool output schemas

SEARCH_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "mailbox": {"type": "string"},
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
        "totalMatched": {"type": "integer"},
        "requestedLimit": {"type": "integer"},
        "summaryLimit": {"type": "integer"},
    },
    "required": ["mailbox", "messages"],
}


__all__ = [
    "SEARCH_MESSAGES_OUTPUT",
]
