# pyright: strict
"""First-class output schemas for the Pinterest toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_metadata=True``). They are not the raw
Pinterest API payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``board_ref`` or ``pin_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
``board_id`` / ``pin_id`` are only present when ``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_BOARD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "board_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "privacy": {"type": "string"},
        "owner": {"type": "string"},
        "pin_count": {"type": "integer"},
        "follower_count": {"type": "integer"},
        "created_at": {"type": "string"},
        "board_id": {"type": "string"},
    },
    "required": ["board_ref", "name"],
}

_PIN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pin_ref": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "alt_text": {"type": "string"},
        "link": {"type": "string"},
        "created_at": {"type": "string"},
        "url": {"type": "string"},
        "pin_id": {"type": "string"},
        "board_id": {"type": "string"},
    },
    "required": ["pin_ref"],
}


# MARK: - Tool output schemas

LIST_BOARDS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "boards": {"type": "array", "items": _BOARD_SUMMARY},
        "bookmark": {"type": ["string", "null"]},
    },
    "required": ["boards"],
}

LIST_BOARD_PINS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pins": {"type": "array", "items": _PIN_SUMMARY},
        "bookmark": {"type": ["string", "null"]},
    },
    "required": ["pins"],
}

LIST_PINS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pins": {"type": "array", "items": _PIN_SUMMARY},
        "bookmark": {"type": ["string", "null"]},
    },
    "required": ["pins"],
}


__all__ = [
    "LIST_BOARDS_OUTPUT",
    "LIST_BOARD_PINS_OUTPUT",
    "LIST_PINS_OUTPUT",
]
