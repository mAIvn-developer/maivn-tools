# pyright: strict
"""First-class output schemas for the Microsoft Teams toolset.

These document the connector-owned, normalized summary shapes that the list
tools return by default (``include_metadata=True``). They are not the raw
Microsoft Graph payloads: each schema mirrors exactly the compact dict the
connector builds (the ``_message_summary`` helper and the inline ``team`` /
``channel`` / ``chat`` summaries), so the assignment planner and repair loop
can resolve fields like ``team_ref`` or ``channel_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's summary builders)

_TEAM_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "team_ref": {"type": "string"},
        "display_name": {"type": "string"},
        "description": {"type": "string"},
        "team_id": {"type": "string"},
    },
    "required": ["team_ref", "display_name"],
}

_CHANNEL_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "channel_ref": {"type": "string"},
        "display_name": {"type": "string"},
        "description": {"type": "string"},
        "membership_type": {"type": "string"},
        "channel_id": {"type": "string"},
        "team_id": {"type": "string"},
    },
    "required": ["channel_ref", "display_name"],
}

_MESSAGE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "sender": {"type": "string"},
        "content_preview": {"type": "string"},
        "created_at": {"type": "string"},
        "message_id": {"type": "string"},
    },
    "required": ["message_ref"],
}

_CHAT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "chat_ref": {"type": "string"},
        "topic": {"type": "string"},
        "chat_type": {"type": "string"},
        "last_updated": {"type": "string"},
        "chat_id": {"type": "string"},
    },
    "required": ["chat_ref"],
}


# MARK: - Tool output schemas

LIST_JOINED_TEAMS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "teams": {"type": "array", "items": _TEAM_SUMMARY},
    },
    "required": ["teams"],
}

LIST_CHANNELS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "channels": {"type": "array", "items": _CHANNEL_SUMMARY},
    },
    "required": ["channels"],
}

LIST_CHANNEL_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
        "next_link": {"type": "string"},
    },
    "required": ["messages"],
}

LIST_CHATS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "chats": {"type": "array", "items": _CHAT_SUMMARY},
        "next_link": {"type": "string"},
    },
    "required": ["chats"],
}

LIST_CHAT_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
    },
    "required": ["messages"],
}


__all__ = [
    "LIST_CHANNELS_OUTPUT",
    "LIST_CHANNEL_MESSAGES_OUTPUT",
    "LIST_CHATS_OUTPUT",
    "LIST_CHAT_MESSAGES_OUTPUT",
    "LIST_JOINED_TEAMS_OUTPUT",
]
