# pyright: strict
"""First-class output schemas for the Microsoft Graph toolsets.

These document the connector-owned, normalized shapes that the Outlook Mail,
Outlook Calendar, and OneDrive/SharePoint list/search tools return by default
(``include_metadata=True``). They are not the raw Graph payloads: each schema
mirrors exactly the compact dict the connector builds via its ``_*_summary``
helpers, so the assignment planner and repair loop can resolve fields like
``message_ref`` or ``event_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connectors' ``_*_summary`` builders)

_FOLDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "folder_ref": {"type": "string"},
        "display_name": {"type": "string"},
        "total_item_count": {"type": "integer"},
        "unread_item_count": {"type": "integer"},
        "folder_id": {"type": "string"},
        "parent_folder_id": {"type": "string"},
    },
    "required": ["folder_ref"],
}

_MESSAGE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "sender": {"type": "string"},
        "to": {"type": "array", "items": {"type": "string"}},
        "subject": {"type": "string"},
        "received_at": {"type": "string"},
        "preview": {"type": "string"},
        "is_read": {"type": "boolean"},
        "message_id": {"type": "string"},
        "conversation_id": {"type": "string"},
    },
    "required": ["message_ref"],
}

_CALENDAR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "calendar_ref": {"type": "string"},
        "name": {"type": "string"},
        "color": {"type": "string"},
        "is_default": {"type": "boolean"},
        "can_edit": {"type": "boolean"},
        "calendar_id": {"type": "string"},
    },
    "required": ["calendar_ref"],
}

_EVENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "event_ref": {"type": "string"},
        "subject": {"type": "string"},
        "start_time": {"type": "string"},
        "end_time": {"type": "string"},
        "location": {"type": "string"},
        "organizer": {"type": "string"},
        "attendees": {"type": "array", "items": {"type": "string"}},
        "is_online_meeting": {"type": "boolean"},
        "is_all_day": {"type": "boolean"},
        "event_id": {"type": "string"},
        "i_cal_uid": {"type": "string"},
    },
    "required": ["event_ref"],
}

# ``_item_summary`` emits ``item_ref`` for files and ``folder_ref`` for folders;
# both keys are documented as optional so either shape validates.
_DRIVE_ITEM_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "item_ref": {"type": "string"},
        "folder_ref": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string"},
        "size": {"type": "integer"},
        "modified_time": {"type": "string"},
        "owner": {"type": "string"},
        "web_url": {"type": "string"},
        "mime_type": {"type": "string"},
        "item_id": {"type": "string"},
        "parent_id": {"type": "string"},
    },
    "required": ["name", "kind"],
}


# MARK: - Tool output schemas

LIST_FOLDERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "folders": {"type": "array", "items": _FOLDER_SUMMARY},
        "nextLink": {"type": ["string", "null"]},
    },
    "required": ["folders"],
}

LIST_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
        "nextLink": {"type": "string"},
    },
    "required": ["messages"],
}

LIST_CALENDARS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "calendars": {"type": "array", "items": _CALENDAR_SUMMARY},
        "nextLink": {"type": ["string", "null"]},
    },
    "required": ["calendars"],
}

LIST_EVENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "events": {"type": "array", "items": _EVENT_SUMMARY},
        "nextLink": {"type": "string"},
    },
    "required": ["events"],
}

LIST_DRIVE_ITEMS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _DRIVE_ITEM_SUMMARY},
        "next_link": {"type": "string"},
    },
    "required": ["items"],
}


__all__ = [
    "LIST_CALENDARS_OUTPUT",
    "LIST_DRIVE_ITEMS_OUTPUT",
    "LIST_EVENTS_OUTPUT",
    "LIST_FOLDERS_OUTPUT",
    "LIST_MESSAGES_OUTPUT",
]
