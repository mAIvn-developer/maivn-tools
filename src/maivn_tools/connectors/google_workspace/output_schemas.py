# pyright: strict
"""First-class output schemas for the Google Workspace toolsets.

These document the connector-owned, normalized summary shapes that the
search/list tools return by default (``include_metadata=True``). They are not
the raw Gmail/Calendar/Drive payloads: each schema mirrors exactly the compact
dict the connector builds (via ``_message_summary``, ``_event_summary``,
``_file_summary``, or the inline calendar summary), so the assignment planner
and repair loop can resolve fields like ``message_ref`` or ``event_ref``
without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connectors' summary builders)

# Gmail: GmailToolSet._message_summary
_MESSAGE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "sender": {"type": "string"},
        "to": {"type": "string"},
        "subject": {"type": "string"},
        "received_at": {"type": "string"},
        "snippet": {"type": "string"},
        "label_ids": {"type": "array", "items": {"type": "string"}},
        "message_id": {"type": "string"},
        "thread_id": {"type": "string"},
    },
    "required": ["message_ref"],
}

# Calendar: GoogleCalendarToolSet.list_calendars inline summary
_CALENDAR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "calendar_ref": {"type": "string"},
        "summary": {"type": "string"},
        "description": {"type": "string"},
        "time_zone": {"type": "string"},
        "access_role": {"type": "string"},
        "primary": {"type": "boolean"},
        "calendar_id": {"type": "string"},
    },
    "required": ["calendar_ref"],
}

# Calendar: google_workspace.calendar._event_summary
_EVENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "event_ref": {"type": "string"},
        "summary": {"type": "string"},
        "start_time": {"type": "string"},
        "end_time": {"type": "string"},
        "location": {"type": "string"},
        "organizer": {"type": "string"},
        "attendees": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string"},
        "html_link": {"type": "string"},
        "event_id": {"type": "string"},
        "i_cal_uid": {"type": "string"},
        "recurring_event_id": {"type": "string"},
    },
    "required": ["event_ref"],
}

# Drive: GoogleDriveToolSet._file_summary (ref key is file_ref or folder_ref)
_FILE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "file_ref": {"type": "string"},
        "folder_ref": {"type": "string"},
        "name": {"type": "string"},
        "mime_type": {"type": "string"},
        "modified_time": {"type": "string"},
        "size": {"type": "string"},
        "owner": {"type": "string"},
        "file_id": {"type": "string"},
        "parents": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
}


# MARK: - Tool output schemas

# GmailToolSet.search_messages
SEARCH_MESSAGES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _MESSAGE_SUMMARY},
        "nextPageToken": {"type": ["string", "null"]},
        "resultSizeEstimate": {"type": "integer"},
        "requestedMaxResults": {"type": "integer"},
        "summaryLimit": {"type": "integer"},
    },
    "required": ["messages"],
}

# GoogleCalendarToolSet.list_calendars
LIST_CALENDARS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "calendars": {"type": "array", "items": _CALENDAR_SUMMARY},
        "nextPageToken": {"type": ["string", "null"]},
    },
    "required": ["calendars"],
}

# GoogleCalendarToolSet.list_events and .list_event_instances (_summarize_event_list)
LIST_EVENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "events": {"type": "array", "items": _EVENT_SUMMARY},
        "nextPageToken": {"type": "string"},
        "nextSyncToken": {"type": "string"},
        "timeZone": {"type": "string"},
    },
    "required": ["events"],
}

# GoogleDriveToolSet.search_files
SEARCH_FILES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": _FILE_SUMMARY},
        "nextPageToken": {"type": ["string", "null"]},
    },
    "required": ["files"],
}


__all__ = [
    "LIST_CALENDARS_OUTPUT",
    "LIST_EVENTS_OUTPUT",
    "SEARCH_FILES_OUTPUT",
    "SEARCH_MESSAGES_OUTPUT",
]
