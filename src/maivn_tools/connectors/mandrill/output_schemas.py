# pyright: strict
"""First-class output schemas for the Mandrill toolset.

These document the connector-owned, normalized shape that ``list_templates``
returns by default. The schema mirrors exactly the compact dict the connector
builds via ``_template_summary``; it is not the raw Mandrill payload. When
``list_templates`` is called with ``include_raw=True`` it returns the raw
provider response instead, which these schemas do not describe.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_template_summary`` builder)

_TEMPLATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "template_ref": {"type": "string"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "subject": {"type": "string"},
        "from_email": {"type": "string"},
        "publish_name": {"type": "string"},
        "published_at": {"type": "string"},
    },
    "required": ["template_ref", "name"],
}


# MARK: - Tool output schemas

LIST_TEMPLATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "templates": {"type": "array", "items": _TEMPLATE_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["templates"],
}


__all__ = [
    "LIST_TEMPLATES_OUTPUT",
]
