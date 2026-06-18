# pyright: strict
"""First-class output schemas for the Salesforce toolset.

These document the connector-owned, normalized shapes that the read/write
tools build themselves -- not the raw Salesforce REST payloads. ``soql_query``
(``include_metadata=True``) returns the compact ``_summarize_query`` envelope
with a stable ``record_ref`` per row; ``update_record`` / ``delete_record``
return small connector-constructed acknowledgement dicts. Each schema mirrors
exactly what the connector's own code emits so the assignment planner can
resolve fields like ``record_ref`` or ``id`` without guessing.

When ``soql_query`` is called with ``include_metadata=False`` it returns the
raw provider response instead; this schema describes the default normalized
form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_summarize_query`` builder)

_RECORD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "record_ref": {"type": "string"},
        "object_type": {"type": "string"},
        "Name": {"type": ["string", "null"]},
        "Subject": {"type": ["string", "null"]},
        "Title": {"type": ["string", "null"]},
        "FirstName": {"type": ["string", "null"]},
        "LastName": {"type": ["string", "null"]},
        "Email": {"type": ["string", "null"]},
        "Phone": {"type": ["string", "null"]},
        "Status": {"type": ["string", "null"]},
        "StageName": {"type": ["string", "null"]},
        "Amount": {"type": ["number", "null"]},
        "CloseDate": {"type": ["string", "null"]},
        "Type": {"type": ["string", "null"]},
        "record_id": {"type": "string"},
    },
    "required": ["record_ref", "object_type"],
}


# MARK: - Tool output schemas

SOQL_QUERY_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "records": {"type": "array", "items": _RECORD_SUMMARY},
        "totalSize": {"type": "integer"},
        "done": {"type": "boolean"},
        "nextRecordsUrl": {"type": "string"},
    },
    "required": ["records", "totalSize", "done"],
}

UPDATE_RECORD_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "updated": {"type": "boolean"},
        "id": {"type": "string"},
        "status": {"type": "integer"},
    },
    "required": ["updated", "id"],
}

DELETE_RECORD_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean"},
        "id": {"type": "string"},
        "status": {"type": "integer"},
    },
    "required": ["deleted", "id"],
}


__all__ = [
    "DELETE_RECORD_OUTPUT",
    "SOQL_QUERY_OUTPUT",
    "UPDATE_RECORD_OUTPUT",
]
