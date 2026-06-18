# pyright: strict
"""First-class output schemas for the Klaviyo toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_raw=False``). They are not the raw
Klaviyo JSON:API payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``profile_ref`` or ``campaign_ref`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
payload instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PROFILE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "profile_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "phone_number": {"type": "string"},
        "subscriptions": {"type": "object"},
        "profile_id": {"type": "string"},
    },
    "required": ["profile_ref"],
}

_LIST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "list_ref": {"type": "string"},
        "name": {"type": "string"},
        "created": {"type": "string"},
        "list_id": {"type": "string"},
    },
    "required": ["list_ref"],
}

_CAMPAIGN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "campaign_ref": {"type": "string"},
        "name": {"type": "string"},
        "status": {"type": "string"},
        "created_at": {"type": "string"},
        "send_time": {"type": "string"},
        "campaign_id": {"type": "string"},
    },
    "required": ["campaign_ref"],
}

_FLOW_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "flow_ref": {"type": "string"},
        "name": {"type": "string"},
        "status": {"type": "string"},
        "trigger_type": {"type": "string"},
        "flow_id": {"type": "string"},
    },
    "required": ["flow_ref"],
}


# MARK: - Tool output schemas

LIST_PROFILES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "profiles": {"type": "array", "items": _PROFILE_SUMMARY},
        "count": {"type": "integer"},
        "next_cursor": {"type": ["string", "null"]},
    },
    "required": ["profiles", "count"],
}

LIST_LISTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "lists": {"type": "array", "items": _LIST_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["lists", "count"],
}

LIST_CAMPAIGNS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "campaigns": {"type": "array", "items": _CAMPAIGN_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["campaigns", "count"],
}

LIST_FLOWS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "flows": {"type": "array", "items": _FLOW_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["flows", "count"],
}


__all__ = [
    "LIST_CAMPAIGNS_OUTPUT",
    "LIST_FLOWS_OUTPUT",
    "LIST_LISTS_OUTPUT",
    "LIST_PROFILES_OUTPUT",
]
