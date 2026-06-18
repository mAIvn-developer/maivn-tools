"""First-class output schemas for the GitHub toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
read/list tools return by default (``include_metadata=True``). They are not the
raw GitHub REST payloads: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``full_name`` or ``issue_number`` without guessing.

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
        "name": {"type": "string"},
        "owner": {"type": "string"},
        "private": {"type": "boolean"},
        "fork": {"type": "boolean"},
        "default_branch": {"type": "string"},
        "description": {"type": "string"},
        "language": {"type": "string"},
        "stargazers_count": {"type": "integer"},
        "forks_count": {"type": "integer"},
        "open_issues_count": {"type": "integer"},
        "updated_at": {"type": "string"},
        "html_url": {"type": "string"},
        "repo_id": {"type": "integer"},
        "node_id": {"type": "string"},
    },
    "required": ["repo_ref", "full_name", "owner"],
}

_ISSUE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "issue_ref": {"type": "string"},
        "issue_number": {"type": "integer"},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "author": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "assignees": {"type": "array", "items": {"type": "string"}},
        "comments": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "html_url": {"type": "string"},
        "is_pull_request": {"type": "boolean"},
        "issue_id": {"type": "integer"},
        "node_id": {"type": "string"},
    },
    "required": ["issue_ref", "issue_number", "title", "state"],
}

_PR_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "pr_ref": {"type": "string"},
        "pr_number": {"type": "integer"},
        "title": {"type": "string"},
        "state": {"type": "string"},
        "draft": {"type": "boolean"},
        "author": {"type": "string"},
        "head": {"type": "string"},
        "base": {"type": "string"},
        "merged": {"type": "boolean"},
        "mergeable_state": {"type": ["string", "null"]},
        "comments": {"type": "integer"},
        "review_comments": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "html_url": {"type": "string"},
        "pr_id": {"type": "integer"},
        "node_id": {"type": "string"},
    },
    "required": ["pr_ref", "pr_number", "title", "state"],
}

_COMMIT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "commit_ref": {"type": "string"},
        "sha": {"type": "string"},
        "short_sha": {"type": "string"},
        "message": {"type": "string"},
        "author": {"type": "string"},
        "authored_at": {"type": "string"},
        "html_url": {"type": "string"},
        "node_id": {"type": "string"},
    },
    "required": ["commit_ref", "sha"],
}

_BRANCH_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "branch_ref": {"type": "string"},
        "name": {"type": "string"},
        "sha": {"type": "string"},
        "short_sha": {"type": "string"},
        "protected": {"type": "boolean"},
        "commit_node_id": {"type": "string"},
    },
    "required": ["branch_ref", "name"],
}

_WORKFLOW_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "workflow_ref": {"type": "string"},
        "workflow_id": {"type": "integer"},
        "name": {"type": "string"},
        "state": {"type": "string"},
        "path": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "html_url": {"type": "string"},
        "node_id": {"type": "string"},
    },
    "required": ["workflow_ref", "workflow_id"],
}

_RUN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "run_ref": {"type": "string"},
        "run_id": {"type": "integer"},
        "name": {"type": "string"},
        "display_title": {"type": "string"},
        "status": {"type": "string"},
        "conclusion": {"type": ["string", "null"]},
        "event": {"type": "string"},
        "branch": {"type": "string"},
        "short_sha": {"type": "string"},
        "run_number": {"type": ["integer", "null"]},
        "run_attempt": {"type": ["integer", "null"]},
        "actor": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "html_url": {"type": "string"},
        "node_id": {"type": "string"},
        "check_suite_id": {"type": "integer"},
    },
    "required": ["run_ref", "run_id"],
}

_RELEASE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "release_ref": {"type": "string"},
        "tag_name": {"type": "string"},
        "name": {"type": "string"},
        "draft": {"type": "boolean"},
        "prerelease": {"type": "boolean"},
        "author": {"type": "string"},
        "created_at": {"type": "string"},
        "published_at": {"type": "string"},
        "html_url": {"type": "string"},
        "release_id": {"type": "integer"},
        "node_id": {"type": "string"},
    },
    "required": ["release_ref", "tag_name"],
}


# MARK: - Wrapper helpers


def _listing(
    item_key: str, item_schema: dict[str, JsonValue], *, total_key: str
) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], <total_key>: int, page: int}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            total_key: {"type": "integer"},
            "page": {"type": "integer"},
            "state": {"type": "string"},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_REPOSITORIES_OUTPUT: dict[str, JsonValue] = _listing(
    "repositories", _REPO_SUMMARY, total_key="count"
)
SEARCH_REPOSITORIES_OUTPUT: dict[str, JsonValue] = _listing(
    "repositories", _REPO_SUMMARY, total_key="total_count"
)
LIST_ISSUES_OUTPUT: dict[str, JsonValue] = _listing("issues", _ISSUE_SUMMARY, total_key="count")
SEARCH_ISSUES_OUTPUT: dict[str, JsonValue] = _listing(
    "issues", _ISSUE_SUMMARY, total_key="total_count"
)
LIST_PULL_REQUESTS_OUTPUT: dict[str, JsonValue] = _listing(
    "pull_requests", _PR_SUMMARY, total_key="count"
)
LIST_BRANCHES_OUTPUT: dict[str, JsonValue] = _listing(
    "branches", _BRANCH_SUMMARY, total_key="count"
)
LIST_COMMITS_OUTPUT: dict[str, JsonValue] = _listing("commits", _COMMIT_SUMMARY, total_key="count")
LIST_RELEASES_OUTPUT: dict[str, JsonValue] = _listing(
    "releases", _RELEASE_SUMMARY, total_key="count"
)
LIST_WORKFLOWS_OUTPUT: dict[str, JsonValue] = _listing(
    "workflows", _WORKFLOW_SUMMARY, total_key="total_count"
)
LIST_WORKFLOW_RUNS_OUTPUT: dict[str, JsonValue] = _listing(
    "workflow_runs", _RUN_SUMMARY, total_key="total_count"
)


__all__ = [
    "LIST_BRANCHES_OUTPUT",
    "LIST_COMMITS_OUTPUT",
    "LIST_ISSUES_OUTPUT",
    "LIST_PULL_REQUESTS_OUTPUT",
    "LIST_RELEASES_OUTPUT",
    "LIST_REPOSITORIES_OUTPUT",
    "LIST_WORKFLOWS_OUTPUT",
    "LIST_WORKFLOW_RUNS_OUTPUT",
    "SEARCH_ISSUES_OUTPUT",
    "SEARCH_REPOSITORIES_OUTPUT",
]
