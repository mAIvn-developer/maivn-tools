# pyright: strict

"""First-class output schemas for the PostHog toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw PostHog payloads: each
schema mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``event_ref`` or ``person_ref``
without guessing.

Raw provider IDs (``event_id``, ``insight_id``, ``person_id``) only appear when
a tool is called with ``include_ids=True``; the schemas list them as optional
properties. The ``next`` pagination cursor mirrors the provider value verbatim.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_EVENT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "event_ref": {"type": "string"},
        "event": {"type": "string"},
        "distinct_id": {"type": "string"},
        "timestamp": {"type": "string"},
        "person_name": {"type": "string"},
        "event_id": {"type": "string"},
    },
    "required": ["event_ref", "event", "distinct_id"],
}

_INSIGHT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "insight_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "created_by": {"type": "string"},
        "updated_at": {"type": "string"},
        "insight_id": {"type": "integer"},
        "short_id": {"type": "string"},
    },
    "required": ["insight_ref", "name"],
}

_PERSON_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "person_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "distinct_id": {"type": "string"},
        "created_at": {"type": "string"},
        "person_id": {"type": "string"},
        "distinct_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["person_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], next: str | null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "next": {"type": ["string", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_EVENTS_OUTPUT: dict[str, JsonValue] = _listing("events", _EVENT_SUMMARY)
LIST_INSIGHTS_OUTPUT: dict[str, JsonValue] = _listing("insights", _INSIGHT_SUMMARY)
LIST_PERSONS_OUTPUT: dict[str, JsonValue] = _listing("persons", _PERSON_SUMMARY)


__all__ = [
    "LIST_EVENTS_OUTPUT",
    "LIST_INSIGHTS_OUTPUT",
    "LIST_PERSONS_OUTPUT",
]
