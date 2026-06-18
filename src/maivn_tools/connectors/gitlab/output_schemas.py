# pyright: strict
"""First-class output schemas for the GitLab toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default (``include_metadata=True``). They are not the raw
GitLab API payloads: each schema mirrors exactly the compact dict the connector
builds, so the assignment planner and repair loop can resolve fields like
``path_with_namespace`` or ``iid`` without guessing.

When a tool is called with ``include_metadata=False`` it returns the raw
provider response instead; these schemas describe the default normalized form.
The ``include_ids=True`` properties (``project_id``, ``issue_id``, ``mr_id``,
``sha``) are optional and only present when explicitly requested.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PROJECT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "project_ref": {"type": "string"},
        "path_with_namespace": {"type": "string"},
        "name": {"type": "string"},
        "namespace": {"type": "string"},
        "visibility": {"type": "string"},
        "default_branch": {"type": "string"},
        "description": {"type": "string"},
        "star_count": {"type": "integer"},
        "forks_count": {"type": "integer"},
        "open_issues_count": {"type": "integer"},
        "last_activity_at": {"type": "string"},
        "web_url": {"type": "string"},
        "project_id": {"type": "integer"},
    },
    "required": ["project_ref", "path_with_namespace"],
}

_ISSUE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issue_ref": {"type": "string"},
        "iid": {"type": ["integer", "null"]},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "author": {"type": "string"},
        "assignees": {"type": "array", "items": {"type": "string"}},
        "labels": {"type": "array", "items": {"type": "string"}},
        "user_notes_count": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "web_url": {"type": "string"},
        "issue_id": {"type": "integer"},
        "project_id": {"type": "integer"},
    },
    "required": ["issue_ref", "iid", "title", "state"],
}

_MR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "mr_ref": {"type": "string"},
        "iid": {"type": ["integer", "null"]},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "draft": {"type": "boolean"},
        "author": {"type": "string"},
        "source_branch": {"type": "string"},
        "target_branch": {"type": "string"},
        "merge_status": {"type": ["string", "null"]},
        "user_notes_count": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "web_url": {"type": "string"},
        "mr_id": {"type": "integer"},
        "project_id": {"type": "integer"},
    },
    "required": ["mr_ref", "iid", "title", "state"],
}

_PIPELINE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pipeline_ref": {"type": "string"},
        "pipeline_id": {"type": ["integer", "null"]},
        "status": {"type": "string"},
        "source": {"type": "string"},
        "ref": {"type": "string"},
        "short_sha": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "web_url": {"type": "string"},
        "project_id": {"type": "integer"},
        "sha": {"type": "string"},
    },
    "required": ["pipeline_ref", "pipeline_id"],
}

_BRANCH_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "branch_ref": {"type": "string"},
        "name": {"type": "string"},
        "default": {"type": "boolean"},
        "protected": {"type": "boolean"},
        "merged": {"type": "boolean"},
        "short_sha": {"type": "string"},
        "web_url": {"type": "string"},
        "sha": {"type": "string"},
    },
    "required": ["branch_ref", "name"],
}

_COMMIT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "commit_ref": {"type": "string"},
        "short_sha": {"type": "string"},
        "title": {"type": "string"},
        "author": {"type": "string"},
        "authored_at": {"type": "string"},
        "web_url": {"type": "string"},
        "sha": {"type": "string"},
    },
    "required": ["commit_ref", "short_sha"],
}


# MARK: - Wrapper helpers


def _listing(
    item_key: str, item_schema: dict[str, JsonValue], *, with_page: bool
) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], count: int[, page: int]}`` schema."""
    properties: dict[str, JsonValue] = {
        item_key: {"type": "array", "items": item_schema},
        "count": {"type": "integer"},
    }
    if with_page:
        properties["page"] = {"type": "integer"}
    return {
        "type": "object",
        "properties": properties,
        "required": [item_key, "count"],
    }


# MARK: - Tool output schemas

LIST_PROJECTS_OUTPUT: dict[str, JsonValue] = _listing("projects", _PROJECT_SUMMARY, with_page=True)
LIST_ISSUES_OUTPUT: dict[str, JsonValue] = _listing("issues", _ISSUE_SUMMARY, with_page=True)
LIST_MERGE_REQUESTS_OUTPUT: dict[str, JsonValue] = _listing(
    "merge_requests", _MR_SUMMARY, with_page=True
)
LIST_PIPELINES_OUTPUT: dict[str, JsonValue] = _listing(
    "pipelines", _PIPELINE_SUMMARY, with_page=True
)
LIST_BRANCHES_OUTPUT: dict[str, JsonValue] = _listing("branches", _BRANCH_SUMMARY, with_page=False)
LIST_COMMITS_OUTPUT: dict[str, JsonValue] = _listing("commits", _COMMIT_SUMMARY, with_page=False)


__all__ = [
    "LIST_BRANCHES_OUTPUT",
    "LIST_COMMITS_OUTPUT",
    "LIST_ISSUES_OUTPUT",
    "LIST_MERGE_REQUESTS_OUTPUT",
    "LIST_PIPELINES_OUTPUT",
    "LIST_PROJECTS_OUTPUT",
]
