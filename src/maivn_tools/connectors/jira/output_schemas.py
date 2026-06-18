# pyright: strict
"""First-class output schemas for the Jira toolset.

These document the connector-owned, normalized shapes that the ``search_issues``
and ``list_projects`` tools return by default (``include_metadata=True``). They
are not the raw Jira REST payloads: each schema mirrors exactly the compact dict
the connector builds (via ``_issue_summary`` and the inline project summary), so
the assignment planner and repair loop can resolve fields like ``key`` or
``issue_ref`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's summary builders)

_ISSUE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issue_ref": {"type": "string"},
        "key": {"type": "string"},
        "summary": {"type": "string"},
        "status": {"type": "string"},
        "assignee": {"type": "string"},
        "priority": {"type": "string"},
        "issue_type": {"type": "string"},
        "updated": {"type": "string"},
        "issue_id": {"type": "string"},
    },
    "required": ["issue_ref", "key"],
}

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "key": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "lead": {"type": "string"},
        "project_id": {"type": "string"},
    },
    "required": ["project_ref", "key"],
}


# MARK: - Tool output schemas

SEARCH_ISSUES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": _ISSUE_SUMMARY},
        "nextPageToken": {"type": ["string", "null"]},
        "isLast": {"type": ["boolean", "null"]},
    },
    "required": ["issues"],
}

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "projects": {"type": "array", "items": _PROJECT_SUMMARY},
        "startAt": {"type": "integer"},
        "maxResults": {"type": "integer"},
        "total": {"type": "integer"},
        "isLast": {"type": ["boolean", "null"]},
    },
    "required": ["projects"],
}


__all__ = [
    "LIST_PROJECTS_OUTPUT",
    "SEARCH_ISSUES_OUTPUT",
]
