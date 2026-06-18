# pyright: strict
"""First-class output schemas for the Sigma toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return when the raw Sigma payload carries an ``entries`` array. They
are not the raw Sigma REST payloads: each schema mirrors exactly the compact
dict the connector builds, so the assignment planner and repair loop can
resolve fields like ``workbook_ref`` or ``email`` without guessing.

Raw provider IDs (``workbook_id``/``dataset_id``/``member_id``) are only present
when the tool is called with ``include_ids=True``; they are therefore optional
properties, not required ones. When the Sigma payload lacks an ``entries``
array the tool returns the raw provider response instead.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_WORKBOOK_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "workbook_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "owner_email": {"type": "string"},
        "updated_at": {"type": "string"},
        "workbook_id": {"type": "string"},
    },
    "required": ["workbook_ref"],
}

_DATASET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "dataset_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "owner_email": {"type": "string"},
        "updated_at": {"type": "string"},
        "dataset_id": {"type": "string"},
    },
    "required": ["dataset_ref"],
}

_MEMBER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "member_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "member_type": {"type": "string"},
        "is_archived": {"type": "boolean"},
        "member_id": {"type": "string"},
    },
    "required": ["member_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], nextPage: str | null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "nextPage": {"type": ["string", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_WORKBOOKS_OUTPUT: dict[str, JsonValue] = _listing("workbooks", _WORKBOOK_SUMMARY)
LIST_DATASETS_OUTPUT: dict[str, JsonValue] = _listing("datasets", _DATASET_SUMMARY)
LIST_MEMBERS_OUTPUT: dict[str, JsonValue] = _listing("members", _MEMBER_SUMMARY)


__all__ = [
    "LIST_DATASETS_OUTPUT",
    "LIST_MEMBERS_OUTPUT",
    "LIST_WORKBOOKS_OUTPUT",
]
