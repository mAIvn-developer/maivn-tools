# pyright: strict
"""First-class output schemas for the Mailgun toolset.

These document the connector-owned, normalized shapes that the list tools
return by default. They are not the raw Mailgun payloads: each schema mirrors
exactly the compact dict the connector builds via its ``_*_summary`` helpers, so
the assignment planner and repair loop can resolve fields like ``name`` or
``address`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_DOMAIN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "domain_ref": {"type": "string"},
        "name": {"type": "string"},
        "state": {"type": "string"},
        "type": {"type": "string"},
        "created_at": {"type": "string"},
        "id": {"type": "string"},
    },
    "required": ["domain_ref", "name"],
}

_LIST_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "list_ref": {"type": "string"},
        "address": {"type": "string"},
        "name": {"type": "string"},
        "members_count": {"type": "integer"},
        "description": {"type": "string"},
        "address_raw": {"type": "string"},
    },
    "required": ["list_ref", "address"],
}


# MARK: - Tool output schemas

LIST_DOMAINS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "domains": {"type": "array", "items": _DOMAIN_SUMMARY},
        "count": {"type": "integer"},
        "total_count": {"type": ["integer", "null"]},
    },
    "required": ["domains", "count"],
}

LIST_MAILING_LISTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "lists": {"type": "array", "items": _LIST_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["lists", "count"],
}


__all__ = [
    "LIST_DOMAINS_OUTPUT",
    "LIST_MAILING_LISTS_OUTPUT",
]
