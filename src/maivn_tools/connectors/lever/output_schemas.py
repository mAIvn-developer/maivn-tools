# pyright: strict
"""First-class output schemas for the Lever toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Lever payloads: each schema
mirrors exactly the compact dict the connector builds, so the assignment planner
and repair loop can resolve fields like ``candidate_ref`` or ``job_ref`` without
guessing. Raw provider IDs appear only when a tool is called with
``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_OPPORTUNITY_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "candidate_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "headline": {"type": "string"},
        "stage": {"type": "string"},
        "archived": {"type": "boolean"},
        "created_at": {"type": ["integer", "string"]},
        "opportunity_id": {"type": "string"},
    },
    "required": ["candidate_ref", "name"],
}

_POSTING_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "job_ref": {"type": "string"},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "team": {"type": "string"},
        "department": {"type": "string"},
        "location": {"type": "string"},
        "commitment": {"type": "string"},
        "created_at": {"type": ["integer", "string"]},
        "posting_id": {"type": "string"},
    },
    "required": ["job_ref", "title"],
}

_USER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "user_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "access_role": {"type": "string"},
        "deactivated_at": {"type": ["integer", "string"]},
        "user_id": {"type": "string"},
    },
    "required": ["user_ref", "name"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], next: str|null, hasNext: bool}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "next": {"type": ["string", "null"]},
            "hasNext": {"type": "boolean"},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_OPPORTUNITIES_OUTPUT: dict[str, JsonValue] = _listing("candidates", _OPPORTUNITY_SUMMARY)
LIST_POSTINGS_OUTPUT: dict[str, JsonValue] = _listing("jobs", _POSTING_SUMMARY)
LIST_USERS_OUTPUT: dict[str, JsonValue] = _listing("users", _USER_SUMMARY)


__all__ = [
    "LIST_OPPORTUNITIES_OUTPUT",
    "LIST_POSTINGS_OUTPUT",
    "LIST_USERS_OUTPUT",
]
