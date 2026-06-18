# pyright: strict
"""First-class output schemas for the Metabase toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Metabase payloads: each
schema mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``card_ref`` or
``dashboard_ref`` without guessing.

Raw card/dashboard IDs are omitted unless ``include_ids=True``; the schemas
list them as optional (not in ``required``) since they are only present on
demand.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_CARD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "card_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "display": {"type": "string"},
        "creator_email": {"type": "string"},
        "updated_at": {"type": "string"},
        "card_id": {"type": ["integer", "string"]},
    },
    "required": ["card_ref"],
}

_DASHBOARD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "dashboard_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "creator_email": {"type": "string"},
        "updated_at": {"type": "string"},
        "dashboard_id": {"type": ["integer", "string"]},
    },
    "required": ["dashboard_ref"],
}


# MARK: - Tool output schemas

LIST_CARDS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "cards": {"type": "array", "items": _CARD_SUMMARY},
        "totalAvailable": {"type": "integer"},
    },
    "required": ["cards"],
}

LIST_DASHBOARDS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "dashboards": {"type": "array", "items": _DASHBOARD_SUMMARY},
        "totalAvailable": {"type": "integer"},
    },
    "required": ["dashboards"],
}


__all__ = [
    "LIST_CARDS_OUTPUT",
    "LIST_DASHBOARDS_OUTPUT",
]
