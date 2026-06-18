# pyright: strict
"""First-class output schemas for the Azure DevOps toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_metadata=True``). They are not the raw
Azure DevOps REST payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``project_ref`` or ``pull_request_id`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider envelope instead; these schemas describe the default normalized form.
The ``*_id`` / ``url`` / ``sha`` properties only appear when ``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "state": {"type": "string"},
        "visibility": {"type": "string"},
        "last_updated": {"type": "string"},
        "project_id": {"type": ["string", "null"]},
        "url": {"type": "string"},
    },
    "required": ["project_ref", "name"],
}

_REPO_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "repo_ref": {"type": "string"},
        "name": {"type": "string"},
        "project": {"type": "string"},
        "default_branch": {"type": "string"},
        "size": {"type": "integer"},
        "is_disabled": {"type": "boolean"},
        "web_url": {"type": "string"},
        "repo_id": {"type": ["string", "null"]},
        "project_id": {"type": ["string", "null"]},
    },
    "required": ["repo_ref", "name"],
}

_PR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pr_ref": {"type": "string"},
        "pull_request_id": {"type": ["integer", "null"]},
        "title": {"type": "string"},
        "status": {"type": "string"},
        "is_draft": {"type": "boolean"},
        "author": {"type": "string"},
        "source_ref": {"type": "string"},
        "target_ref": {"type": "string"},
        "merge_status": {"type": "string"},
        "repository": {"type": "string"},
        "creation_date": {"type": "string"},
        "repo_id": {"type": ["string", "null"]},
        "code_review_id": {"type": ["integer", "null"]},
    },
    "required": ["pr_ref", "pull_request_id"],
}

_BRANCH_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "branch_ref": {"type": "string"},
        "name": {"type": "string"},
        "short_sha": {"type": "string"},
        "creator": {"type": "string"},
        "sha": {"type": "string"},
    },
    "required": ["branch_ref", "name"],
}

_PIPELINE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pipeline_ref": {"type": "string"},
        "pipeline_id": {"type": ["integer", "null"]},
        "name": {"type": "string"},
        "folder": {"type": "string"},
        "revision": {"type": ["integer", "null"]},
        "web_url": {"type": "string"},
        "url": {"type": "string"},
    },
    "required": ["pipeline_ref", "pipeline_id"],
}

_BUILD_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "build_ref": {"type": "string"},
        "build_id": {"type": ["integer", "null"]},
        "build_number": {"type": "string"},
        "status": {"type": "string"},
        "result": {"type": ["string", "null"]},
        "source_branch": {"type": "string"},
        "short_sha": {"type": "string"},
        "definition": {"type": "string"},
        "queue_time": {"type": "string"},
        "start_time": {"type": "string"},
        "finish_time": {"type": "string"},
        "requested_by": {"type": "string"},
        "definition_id": {"type": ["integer", "null"]},
        "url": {"type": "string"},
    },
    "required": ["build_ref", "build_id"],
}


# MARK: - Wrapper helper


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], count: int, continuation_token?: str}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "count": {"type": "integer"},
            "continuation_token": {"type": "string"},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = _listing("projects", _PROJECT_SUMMARY)
LIST_REPOSITORIES_OUTPUT: dict[str, JsonValue] = _listing("repositories", _REPO_SUMMARY)
LIST_PULL_REQUESTS_OUTPUT: dict[str, JsonValue] = _listing("pull_requests", _PR_SUMMARY)
LIST_BRANCHES_OUTPUT: dict[str, JsonValue] = _listing("branches", _BRANCH_SUMMARY)
LIST_PIPELINES_OUTPUT: dict[str, JsonValue] = _listing("pipelines", _PIPELINE_SUMMARY)
LIST_BUILDS_OUTPUT: dict[str, JsonValue] = _listing("builds", _BUILD_SUMMARY)


__all__ = [
    "LIST_BRANCHES_OUTPUT",
    "LIST_BUILDS_OUTPUT",
    "LIST_PIPELINES_OUTPUT",
    "LIST_PROJECTS_OUTPUT",
    "LIST_PULL_REQUESTS_OUTPUT",
    "LIST_REPOSITORIES_OUTPUT",
]
