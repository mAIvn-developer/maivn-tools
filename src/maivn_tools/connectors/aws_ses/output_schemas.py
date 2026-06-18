# pyright: strict
"""First-class output schemas for the Amazon SES toolset.

These document the connector-owned, normalized shapes that the list tools
return by default (``include_raw=False``). They are not the raw SES v2
payloads: each schema mirrors exactly the compact dict the connector builds
via ``_identity_summary`` / ``_template_summary``, so the assignment planner
and repair loop can resolve fields like ``identity_name`` or ``template_name``
without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_IDENTITY_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "identity_ref": {"type": "string"},
        "identity_name": {"type": "string"},
        "identity_type": {"type": "string"},
        "sending_enabled": {"type": ["boolean", "null"]},
        "verification_status": {"type": "string"},
        "identity_arn": {"type": "string"},
    },
    "required": ["identity_ref", "identity_name"],
}

_TEMPLATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "template_ref": {"type": "string"},
        "template_name": {"type": "string"},
        "created_timestamp": {"type": "string"},
    },
    "required": ["template_ref", "template_name"],
}


# MARK: - Tool output schemas

LIST_IDENTITIES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "identities": {"type": "array", "items": _IDENTITY_SUMMARY},
        "count": {"type": "integer"},
        "next_token": {"type": ["string", "null"]},
    },
    "required": ["identities"],
}

LIST_TEMPLATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "templates": {"type": "array", "items": _TEMPLATE_SUMMARY},
        "count": {"type": "integer"},
        "next_token": {"type": ["string", "null"]},
    },
    "required": ["templates"],
}


__all__ = [
    "LIST_IDENTITIES_OUTPUT",
    "LIST_TEMPLATES_OUTPUT",
]
