# pyright: strict
"""First-class output schemas for the Supabase toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_metadata=True``). They are not the raw
Supabase/GoTrue payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``user_ref`` or ``bucket_id`` without guessing.

When a list tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "user_id": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "role": {"type": "string"},
        "created_at": {"type": "string"},
        "last_sign_in_at": {"type": "string"},
        "confirmed_at": {"type": "string"},
    },
    "required": ["user_ref"],
}

_BUCKET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "bucket_ref": {"type": "string"},
        "bucket_id": {"type": "string"},
        "name": {"type": "string"},
        "public": {"type": "boolean"},
        "file_size_limit": {"type": ["integer", "null"]},
        "allowed_mime_types": {"type": "array", "items": {"type": "string"}},
        "created_at": {"type": "string"},
    },
    "required": ["bucket_ref", "bucket_id", "name"],
}

_OBJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "object_ref": {"type": "string"},
        "name": {"type": "string"},
        "size": {"type": ["integer", "null"]},
        "content_type": {"type": "string"},
        "updated_at": {"type": "string"},
        "created_at": {"type": "string"},
    },
    "required": ["object_ref", "name"],
}


# MARK: - Tool output schemas

LIST_USERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
        "page": {"type": "integer"},
        "per_page": {"type": "integer"},
        "total": {"type": "integer"},
        "next_page": {"type": ["integer", "null"]},
        "last_page": {"type": ["integer", "null"]},
    },
    "required": ["users"],
}

LIST_BUCKETS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "buckets": {"type": "array", "items": _BUCKET_SUMMARY},
    },
    "required": ["buckets"],
}

LIST_OBJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "objects": {"type": "array", "items": _OBJECT_SUMMARY},
        "bucket_id": {"type": "string"},
    },
    "required": ["objects"],
}


__all__ = [
    "LIST_BUCKETS_OUTPUT",
    "LIST_OBJECTS_OUTPUT",
    "LIST_USERS_OUTPUT",
]
