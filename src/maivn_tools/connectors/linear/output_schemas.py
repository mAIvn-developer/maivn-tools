# pyright: strict
"""First-class output schemas for the Linear toolset.

These document the connector-owned, normalized ``_issue_summary`` shape that
:meth:`LinearToolSet.list_issues` returns by default (``include_metadata=True``).
It is not the raw Linear GraphQL payload: the schema mirrors exactly the compact
dict the connector builds, so the assignment planner and repair loop can resolve
fields like ``identifier`` without guessing.

When ``list_issues`` is called with ``include_metadata=False`` it returns the raw
Linear GraphQL response instead; this schema describes the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors the connector's ``_issue_summary`` builder)

_ISSUE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issue_ref": {"type": "string"},
        "identifier": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "string"},
        "priority": {"type": "integer"},
        "assignee": {"type": "string"},
        "team": {"type": "string"},
        "updated_at": {"type": "string"},
        "url": {"type": "string"},
        "issue_id": {"type": "string"},
    },
    "required": ["issue_ref", "identifier", "title"],
}


# MARK: - Tool output schemas

LIST_ISSUES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": _ISSUE_SUMMARY},
        "pageInfo": {
            "type": "object",
            "properties": {
                "hasNextPage": {"type": "boolean"},
                "endCursor": {"type": ["string", "null"]},
            },
        },
    },
    "required": ["issues"],
}


__all__ = ["LIST_ISSUES_OUTPUT"]
