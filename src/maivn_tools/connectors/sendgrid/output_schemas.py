# pyright: strict
"""First-class output schemas for the SendGrid toolset.

These document the connector-owned, normalized summary shapes that the list
tools return by default. They are not the raw SendGrid payloads: each schema
mirrors exactly the compact dict the connector builds (via ``_template_summary``
/ ``_list_summary``), so the assignment planner and repair loop can resolve
fields like ``template_ref`` or ``list_ref`` without guessing.

When a list tool is called with ``include_raw=True`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_TEMPLATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "template_ref": {"type": "string"},
        "name": {"type": "string"},
        "generation": {"type": "string"},
        "updated_at": {"type": "string"},
        "template_id": {"type": "string"},
    },
    "required": ["template_ref"],
}

_LIST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "list_ref": {"type": "string"},
        "name": {"type": "string"},
        "contact_count": {"type": "integer"},
        "list_id": {"type": "string"},
    },
    "required": ["list_ref"],
}


# MARK: - Tool output schemas

LIST_TEMPLATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "templates": {"type": "array", "items": _TEMPLATE_SUMMARY},
        "count": {"type": "integer"},
        "next_page_token": {"type": ["string", "null"]},
    },
    "required": ["templates", "count"],
}

LIST_LISTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "lists": {"type": "array", "items": _LIST_SUMMARY},
        "count": {"type": "integer"},
        "next_page_token": {"type": ["string", "null"]},
    },
    "required": ["lists", "count"],
}


__all__ = [
    "LIST_LISTS_OUTPUT",
    "LIST_TEMPLATES_OUTPUT",
]
