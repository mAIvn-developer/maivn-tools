# pyright: strict
"""First-class output schemas for the Customer.io toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_raw=False``). They are not the raw
Customer.io App API payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``segment_ref`` or ``broadcast_ref`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_SEGMENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "segment_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "type": {"type": "string"},
        "state": {"type": "string"},
        "segment_id": {"type": ["integer", "string", "null"]},
    },
    "required": ["segment_ref"],
}

_BROADCAST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "broadcast_ref": {"type": "string"},
        "name": {"type": "string"},
        "state": {"type": "string"},
        "type": {"type": "string"},
        "created": {"type": ["integer", "string", "null"]},
        "broadcast_id": {"type": ["integer", "string", "null"]},
    },
    "required": ["broadcast_ref"],
}

_CAMPAIGN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "campaign_ref": {"type": "string"},
        "name": {"type": "string"},
        "state": {"type": "string"},
        "type": {"type": "string"},
        "created": {"type": ["integer", "string", "null"]},
        "campaign_id": {"type": ["integer", "string", "null"]},
    },
    "required": ["campaign_ref"],
}


# MARK: - Tool output schemas

LIST_SEGMENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "segments": {"type": "array", "items": _SEGMENT_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["segments", "count"],
}

LIST_BROADCASTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "broadcasts": {"type": "array", "items": _BROADCAST_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["broadcasts", "count"],
}

LIST_CAMPAIGNS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "campaigns": {"type": "array", "items": _CAMPAIGN_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["campaigns", "count"],
}


__all__ = [
    "LIST_BROADCASTS_OUTPUT",
    "LIST_CAMPAIGNS_OUTPUT",
    "LIST_SEGMENTS_OUTPUT",
]
