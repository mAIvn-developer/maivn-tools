# pyright: strict
"""First-class output schemas for the Amplitude toolset.

These document the connector-owned, normalized shapes that the user-search,
cohort-listing, and export tools build from the raw Amplitude responses. They
are not the raw Dashboard / Cohort REST payloads: each schema mirrors exactly
the compact dict the connector constructs (via ``_user_summary`` /
``_cohort_summary`` or a directly-built ``{"status": ...}`` payload), so the
assignment planner and repair loop can resolve fields like ``user_ref`` or
``cohort_ref`` without guessing.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "user_id": {"type": "string"},
        "last_seen": {"type": "string"},
        "amplitude_id": {"type": "string"},
        "device_id": {"type": "string"},
    },
    "required": ["user_ref", "user_id"],
}

_COHORT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "cohort_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "size": {"type": "integer"},
        "owner": {"type": "string"},
        "last_modified": {"type": "string"},
        "cohort_id": {"type": "string"},
    },
    "required": ["cohort_ref", "name"],
}


# MARK: - Tool output schemas

GET_USER_SEARCH_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "users": {"type": "array", "items": _USER_SUMMARY},
        "type": {"type": "string"},
    },
    "required": ["users"],
}

LIST_COHORTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "cohorts": {"type": "array", "items": _COHORT_SUMMARY},
        "totalAvailable": {"type": "integer"},
    },
    "required": ["cohorts"],
}

EXPORT_RAW_EVENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
    },
    "required": ["status"],
}


__all__ = [
    "EXPORT_RAW_EVENTS_OUTPUT",
    "GET_USER_SEARCH_OUTPUT",
    "LIST_COHORTS_OUTPUT",
]
