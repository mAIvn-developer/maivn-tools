# pyright: strict
"""First-class output schemas for the Bitbucket toolset.

These document the connector-owned, normalized shapes that the list tools
return by default (``include_metadata=True``). They are not the raw Bitbucket
paged payloads: each schema mirrors exactly the compact dict the connector
builds via its ``_*_summary`` helpers, so the assignment planner and repair
loop can resolve fields like ``full_name`` or ``pr_id`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_REPO_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "repo_ref": {"type": "string"},
        "full_name": {"type": "string"},
        "slug": {"type": "string"},
        "workspace": {"type": "string"},
        "is_private": {"type": "boolean"},
        "fork_policy": {"type": "string"},
        "description": {"type": "string"},
        "language": {"type": "string"},
        "default_branch": {"type": "string"},
        "updated_on": {"type": "string"},
        "website": {"type": "string"},
        "uuid": {"type": ["string", "null"]},
    },
    "required": ["repo_ref", "full_name", "slug"],
}

_PR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pr_ref": {"type": "string"},
        "pr_id": {"type": ["integer", "null"]},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "author": {"type": "string"},
        "source_branch": {"type": "string"},
        "destination_branch": {"type": "string"},
        "comment_count": {"type": "integer"},
        "task_count": {"type": "integer"},
        "created_on": {"type": "string"},
        "updated_on": {"type": "string"},
        "html_url": {"type": "string"},
    },
    "required": ["pr_ref", "pr_id"],
}

_ISSUE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issue_ref": {"type": "string"},
        "issue_id": {"type": ["integer", "null"]},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "kind": {"type": "string"},
        "priority": {"type": "string"},
        "reporter": {"type": "string"},
        "assignee": {"type": "string"},
        "comment_count": {"type": "integer"},
        "created_on": {"type": "string"},
        "updated_on": {"type": "string"},
        "html_url": {"type": "string"},
    },
    "required": ["issue_ref", "issue_id"],
}

_PIPELINE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pipeline_ref": {"type": "string"},
        "build_number": {"type": ["integer", "null"]},
        "state": {"type": "string"},
        "result": {"type": "string"},
        "branch": {"type": "string"},
        "short_sha": {"type": "string"},
        "creator": {"type": "string"},
        "created_on": {"type": "string"},
        "completed_on": {"type": "string"},
        "uuid": {"type": ["string", "null"]},
    },
    "required": ["pipeline_ref", "build_number"],
}

_BRANCH_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "branch_ref": {"type": "string"},
        "name": {"type": "string"},
        "short_sha": {"type": "string"},
        "sha": {"type": "string"},
    },
    "required": ["branch_ref", "name"],
}


# MARK: - Wrapper helper


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], count: int, page: int, next: str|null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "count": {"type": "integer"},
            "page": {"type": "integer"},
            "next": {"type": ["string", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_REPOSITORIES_OUTPUT: dict[str, JsonValue] = _listing("repositories", _REPO_SUMMARY)
LIST_PULL_REQUESTS_OUTPUT: dict[str, JsonValue] = _listing("pull_requests", _PR_SUMMARY)
LIST_ISSUES_OUTPUT: dict[str, JsonValue] = _listing("issues", _ISSUE_SUMMARY)
LIST_PIPELINES_OUTPUT: dict[str, JsonValue] = _listing("pipelines", _PIPELINE_SUMMARY)
LIST_BRANCHES_OUTPUT: dict[str, JsonValue] = _listing("branches", _BRANCH_SUMMARY)

GET_FILE_CONTENTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "ref": {"type": "string"},
        "status": {"type": "integer"},
        "body": {"type": "string"},
    },
    "required": ["path", "ref", "status", "body"],
}


__all__ = [
    "GET_FILE_CONTENTS_OUTPUT",
    "LIST_BRANCHES_OUTPUT",
    "LIST_ISSUES_OUTPUT",
    "LIST_PIPELINES_OUTPUT",
    "LIST_PULL_REQUESTS_OUTPUT",
    "LIST_REPOSITORIES_OUTPUT",
]
