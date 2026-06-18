# pyright: strict
"""First-class output schemas for the Snyk toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return: each schema mirrors exactly the compact dict the connector
builds (not the raw Snyk REST resource), so the assignment planner and repair
loop can resolve fields like ``org_ref`` or ``vuln_ref`` without guessing.

Raw-identifier fields (``org_id``, ``project_id``, ``vuln_id``, ``key``) are
only present when a tool is called with ``include_ids=True``; the schemas list
them as optional properties.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_ORG_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "org_ref": {"type": "string"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "org_id": {"type": "string"},
    },
    "required": ["org_ref"],
}

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "name": {"type": "string"},
        "origin": {"type": "string"},
        "type": {"type": "string"},
        "target_reference": {"type": "string"},
        "status": {"type": "string"},
        "project_id": {"type": "string"},
    },
    "required": ["project_ref"],
}

_ISSUE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "vuln_ref": {"type": "string"},
        "title": {"type": "string"},
        "severity": {"type": "string"},
        "type": {"type": "string"},
        "status": {"type": "string"},
        "ignored": {"type": "boolean"},
        "created_at": {"type": "string"},
        "vuln_id": {"type": "string"},
        "key": {"type": "string"},
    },
    "required": ["vuln_ref"],
}


# MARK: - Tool output schemas

LIST_ORGANIZATIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "organizations": {"type": "array", "items": _ORG_SUMMARY},
        "links": {"type": "object"},
    },
    "required": ["organizations"],
}

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "projects": {"type": "array", "items": _PROJECT_SUMMARY},
        "links": {"type": "object"},
    },
    "required": ["projects"],
}

LIST_ISSUES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "vulns": {"type": "array", "items": _ISSUE_SUMMARY},
        "links": {"type": "object"},
    },
    "required": ["vulns"],
}


__all__ = [
    "LIST_ISSUES_OUTPUT",
    "LIST_ORGANIZATIONS_OUTPUT",
    "LIST_PROJECTS_OUTPUT",
]
