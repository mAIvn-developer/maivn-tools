"""Jira Cloud REST API v3 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_PROJECTS_OUTPUT, SEARCH_ISSUES_OUTPUT


@toolset(prefix="jira")
class JiraToolSet:
    """A connector for Atlassian Jira Cloud REST API v3.

    Args:
        base_url: Jira Cloud site URL, e.g. ``https://acme.atlassian.net``.
        email: Atlassian account email (used as the basic-auth username).
        api_token: Atlassian API token. Never logged.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="jira",
        display_name="Jira",
        version="0.1.0",
        description="Search and manage Jira issues, comments, and transitions.",
        auth_modes=(AuthMode.BASIC,),
        scopes={
            "read:jira-work": "Read issues and projects.",
            "write:jira-work": "Create and edit issues.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
        homepage_url="https://www.atlassian.com/software/jira",
        tags=("ticketing", "atlassian"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not email:
            raise ValueError("email is required")
        if not api_token:
            raise ValueError("api_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BasicAuth(email, api_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def myself(self) -> dict[str, Any]:
        """Return the authenticated Jira account.

        Returns the user resource (``accountId``, ``emailAddress``,
        ``displayName``). Use once at startup to confirm the token works.
        """
        return self._client.get("/rest/api/3/myself").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_ISSUES_OUTPUT)
    def search_issues(
        self,
        jql: str,
        *,
        next_page_token: str | None = None,
        max_results: int = 25,
        fields: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search Jira issues with JQL.

        Best first tool for issue triage. By default returns compact
        summaries with a stable ``issue_ref`` (``issue_1``, ``issue_2``, ...)
        plus the issue key, summary, status, assignee, priority, and
        updated timestamp. The Jira issue key (e.g. ``ENG-123``) is the
        canonical identifier users recognise and is safe to show in final
        answers. Raw Jira numeric ``id`` values are internal handles and
        are omitted unless ``include_ids=True``.

        Set ``include_metadata=False`` to receive the raw Jira search
        response. Pagination is token-based: pass the returned
        ``nextPageToken`` back in via ``next_page_token`` to fetch the next
        page; ``isLast`` reports whether more pages remain. (Total counts
        are not returned by this endpoint; use the separate
        ``/rest/api/3/search/approximate-count`` endpoint if required.)
        """
        if not jql:
            raise ValueError("jql must be a non-empty string")
        if max_results < 1 or max_results > 100:
            raise ValueError("max_results must be between 1 and 100")
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
        }
        if next_page_token is not None:
            payload["nextPageToken"] = next_page_token
        if fields is not None:
            payload["fields"] = fields
        response: dict[str, Any] = self._client.post("/rest/api/3/search/jql", json=payload).json()
        if not include_metadata:
            return response
        summaries: list[dict[str, Any]] = []
        issues: Any = response.get("issues", []) or []
        for index, issue in enumerate(issues, start=1):
            if not isinstance(issue, dict):
                continue
            issue_dict = cast("dict[str, Any]", issue)
            summaries.append(self._issue_summary(issue_dict, index=index, include_ids=include_ids))
        return {
            "issues": summaries,
            "nextPageToken": response.get("nextPageToken"),
            "isLast": response.get("isLast"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_issue(
        self,
        issue_key: Any,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a single issue by key (e.g. ``ENG-123``).

        Returns the raw Jira issue resource. ``issue_key`` accepts the issue
        key string, a dict returned by :meth:`search_issues`, or a list of
        such dicts.
        """
        resolved = self._extract_issue_key(issue_key)
        params: dict[str, Any] | None = None
        if fields is not None:
            params = {"fields": ",".join(fields)}
        return self._client.get(f"/rest/api/3/issue/{resolved}", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_issue(
        self,
        project_key: str,
        summary: str,
        issue_type: str,
        *,
        description: str | None = None,
        assignee_account_id: str | None = None,
        labels: list[str] | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Jira issue.

        Returns the new issue resource (``id``, ``key``, ``self``). The
        ``key`` is what users see (e.g. ``ENG-123``); the numeric ``id`` is
        an internal handle.
        """
        if not project_key:
            raise ValueError("project_key must be a non-empty string")
        if not summary:
            raise ValueError("summary must be a non-empty string")
        if not issue_type:
            raise ValueError("issue_type must be a non-empty string")
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description is not None:
            fields["description"] = description
        if assignee_account_id is not None:
            fields["assignee"] = {"accountId": assignee_account_id}
        if labels is not None:
            fields["labels"] = labels
        if extra_fields is not None:
            fields.update(extra_fields)
        return self._client.post("/rest/api/3/issue", json={"fields": fields}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_issue(self, issue_key: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch an issue's fields.

        ``issue_key`` accepts the key string, a dict returned by
        :meth:`search_issues`/:meth:`get_issue`, or a list of such dicts.
        """
        resolved = self._extract_issue_key(issue_key)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        response = self._client.put(f"/rest/api/3/issue/{resolved}", json={"fields": fields})
        return {"updated": True, "key": resolved, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_comment(self, issue_key: Any, body: str) -> dict[str, Any]:
        """Add a comment to an issue.

        ``issue_key`` accepts the key string or a dict/list from
        :meth:`search_issues`.
        """
        resolved = self._extract_issue_key(issue_key)
        if not body:
            raise ValueError("body must be a non-empty string")
        return self._client.post(
            f"/rest/api/3/issue/{resolved}/comment",
            json={"body": body},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def transition_issue(self, issue_key: Any, transition_id: str) -> dict[str, Any]:
        """Apply a workflow transition to an issue.

        Use :meth:`list_transitions` first to find the valid
        ``transition_id`` for the issue's current status. ``issue_key``
        accepts the key string or a dict/list from :meth:`search_issues`.
        """
        resolved = self._extract_issue_key(issue_key)
        if not transition_id:
            raise ValueError("transition_id must be a non-empty string")
        response = self._client.post(
            f"/rest/api/3/issue/{resolved}/transitions",
            json={"transition": {"id": transition_id}},
        )
        return {"transitioned": True, "key": resolved, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_transitions(self, issue_key: Any) -> dict[str, Any]:
        """Return available workflow transitions for an issue.

        Returns ``{"transitions": [{"id": ..., "name": ..., "to": {...}}]}``.
        Use the ``id`` with :meth:`transition_issue`. ``issue_key`` accepts
        the key string or a dict/list from :meth:`search_issues`.
        """
        resolved = self._extract_issue_key(issue_key)
        return self._client.get(f"/rest/api/3/issue/{resolved}/transitions").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_issue(self, issue_key: Any, *, delete_subtasks: bool = False) -> dict[str, Any]:
        """Permanently delete an issue.

        Destructive and not recoverable. Confirm with the user first.
        ``issue_key`` accepts the key string or a dict/list from
        :meth:`search_issues`.
        """
        resolved = self._extract_issue_key(issue_key)
        self._client.delete(
            f"/rest/api/3/issue/{resolved}",
            params={"deleteSubtasks": str(delete_subtasks).lower()},
        )
        return {"key": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def assign_issue(
        self,
        issue_key: Any,
        *,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign an issue. Pass ``account_id=None`` to clear the assignee.

        ``issue_key`` accepts the key string or a dict/list from
        :meth:`search_issues`.
        """
        resolved = self._extract_issue_key(issue_key)
        response = self._client.put(
            f"/rest/api/3/issue/{resolved}/assignee",
            json={"accountId": account_id},
        )
        return {"assigned": True, "key": resolved, "status": response.status}

    # MARK: - Comments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(
        self,
        issue_key: Any,
        *,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """List comments on an issue.

        ``issue_key`` accepts the key string or a dict/list from
        :meth:`search_issues`.
        """
        resolved = self._extract_issue_key(issue_key)
        return self._client.get(
            f"/rest/api/3/issue/{resolved}/comment",
            params={"startAt": start_at, "maxResults": max_results},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_comment(
        self,
        issue_key: Any,
        comment_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Update the body of a comment."""
        resolved = self._extract_issue_key(issue_key)
        if not comment_id or not body:
            raise ValueError("comment_id and body must be non-empty")
        return self._client.put(
            f"/rest/api/3/issue/{resolved}/comment/{comment_id}",
            json={"body": body},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_comment(self, issue_key: Any, comment_id: str) -> dict[str, Any]:
        """Delete a comment.

        Destructive: the comment cannot be recovered.
        """
        resolved = self._extract_issue_key(issue_key)
        if not comment_id:
            raise ValueError("comment_id must be a non-empty string")
        self._client.delete(f"/rest/api/3/issue/{resolved}/comment/{comment_id}")
        return {"id": comment_id, "deleted": True}

    # MARK: - Worklog

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_worklogs(
        self,
        issue_key: Any,
        *,
        start_at: int = 0,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """List worklog entries for an issue."""
        resolved = self._extract_issue_key(issue_key)
        return self._client.get(
            f"/rest/api/3/issue/{resolved}/worklog",
            params={"startAt": start_at, "maxResults": max_results},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_worklog(
        self,
        issue_key: Any,
        *,
        time_spent: str,
        comment: str | None = None,
        started: str | None = None,
    ) -> dict[str, Any]:
        """Add a worklog entry (``time_spent`` like ``"30m"`` or ``"2h"``)."""
        resolved = self._extract_issue_key(issue_key)
        if not time_spent:
            raise ValueError("time_spent must be a non-empty string")
        payload: dict[str, Any] = {"timeSpent": time_spent}
        if comment is not None:
            payload["comment"] = comment
        if started is not None:
            payload["started"] = started
        return self._client.post(
            f"/rest/api/3/issue/{resolved}/worklog",
            json=payload,
        ).json()

    # MARK: - Issue links & attachments

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def link_issues(
        self,
        *,
        inward_issue: str,
        outward_issue: str,
        link_type: str,
    ) -> dict[str, Any]:
        """Create an issue link (e.g. ``"Blocks"``, ``"Relates"``)."""
        if not inward_issue or not outward_issue or not link_type:
            raise ValueError("inward_issue, outward_issue, and link_type must be non-empty")
        response = self._client.post(
            "/rest/api/3/issueLink",
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward_issue},
                "outwardIssue": {"key": outward_issue},
            },
        )
        return {"linked": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_issue_link(self, link_id: str) -> dict[str, Any]:
        """Delete an issue link.

        Destructive: cannot be undone.
        """
        if not link_id:
            raise ValueError("link_id must be a non-empty string")
        self._client.delete(f"/rest/api/3/issueLink/{link_id}")
        return {"id": link_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_attachments(self, issue_key: Any) -> dict[str, Any]:
        """Return attachments on an issue."""
        resolved = self._extract_issue_key(issue_key)
        issue = self.get_issue(resolved, fields=["attachment"])
        fields_raw: Any = issue.get("fields") or {}
        fields: dict[str, Any] = (
            cast("dict[str, Any]", fields_raw) if isinstance(fields_raw, dict) else {}
        )
        attachments: Any = fields.get("attachment") or []
        return {"key": resolved, "attachments": attachments}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_attachment(self, attachment_id: str) -> dict[str, Any]:
        """Delete an attachment by ID.

        Destructive: cannot be undone.
        """
        if not attachment_id:
            raise ValueError("attachment_id must be a non-empty string")
        self._client.delete(f"/rest/api/3/attachment/{attachment_id}")
        return {"id": attachment_id, "deleted": True}

    # MARK: - Projects, users, statuses

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PROJECTS_OUTPUT)
    def list_projects(
        self,
        *,
        start_at: int = 0,
        max_results: int = 25,
        expand: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Jira projects accessible to the authenticated user.

        By default returns compact summaries with a stable ``project_ref``
        (``project_1``, ``project_2``, ...) plus the project ``key``
        (canonical user-facing handle, e.g. ``ENG``), name, and lead.
        Numeric project IDs are internal handles and are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` to receive the
        raw Jira response.
        """
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if expand is not None:
            params["expand"] = expand
        response: dict[str, Any] = self._client.get(
            "/rest/api/3/project/search", params=params
        ).json()
        if not include_metadata:
            return response
        summaries: list[dict[str, Any]] = []
        values: Any = response.get("values", []) or []
        for index, project in enumerate(values, start=1):
            if not isinstance(project, dict):
                continue
            project_dict = cast("dict[str, Any]", project)
            lead_raw: Any = project_dict.get("lead") or {}
            lead: dict[str, Any] = (
                cast("dict[str, Any]", lead_raw) if isinstance(lead_raw, dict) else {}
            )
            lead_name: Any = lead.get("displayName", "")
            summary: dict[str, Any] = {
                "project_ref": f"project_{index}",
                "key": project_dict.get("key", ""),
                "name": project_dict.get("name", ""),
                "type": project_dict.get("projectTypeKey", ""),
                "lead": lead_name,
            }
            if include_ids:
                summary["project_id"] = project_dict.get("id", "")
            summaries.append(summary)
        return {
            "projects": summaries,
            "startAt": response.get("startAt", start_at),
            "maxResults": response.get("maxResults", max_results),
            "total": response.get("total", len(summaries)),
            "isLast": response.get("isLast"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(self, project_key: str) -> dict[str, Any]:
        """Return a project by key."""
        if not project_key:
            raise ValueError("project_key must be a non-empty string")
        return self._client.get(f"/rest/api/3/project/{project_key}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_issue_types(self, project_key: str) -> dict[str, Any]:
        """List issue types available for a project.

        Returns the project's create-metadata issue types as a paginated
        page object (``values`` holds the issue-type definitions). Uses the
        ``createmeta`` issuetypes sub-resource; the older
        ``/project/{key}/statuses`` endpoint returns valid statuses grouped
        per issue type, not the issue-type definitions themselves.
        """
        if not project_key:
            raise ValueError("project_key must be a non-empty string")
        return self._client.get(f"/rest/api/3/issue/createmeta/{project_key}/issuetypes").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, account_id: str) -> dict[str, Any]:
        """Return a user by accountId."""
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        return self._client.get(
            "/rest/api/3/user",
            params={"accountId": account_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_users(
        self,
        query: str,
        *,
        start_at: int = 0,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Search users by name or email substring.

        Returns the raw list of Jira user resources.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        return self._client.get(
            "/rest/api/3/user/search",
            params={"query": query, "startAt": start_at, "maxResults": max_results},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_statuses(self) -> list[dict[str, Any]]:
        """Return all workflow statuses defined in the instance."""
        return self._client.get("/rest/api/3/status").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_priorities(self) -> list[dict[str, Any]]:
        """Return all priority values defined in the instance."""
        return self._client.get("/rest/api/3/priority").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_resolutions(self) -> list[dict[str, Any]]:
        """Return all resolution values."""
        return self._client.get("/rest/api/3/resolution").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_fields(self) -> list[dict[str, Any]]:
        """Return all fields (system + custom) available in the instance."""
        return self._client.get("/rest/api/3/field").json()

    # MARK: - Agile / boards / sprints

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_boards(
        self,
        *,
        type: str | None = None,
        project_key: str | None = None,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """List boards (Jira Agile API)."""
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if type is not None:
            params["type"] = type
        if project_key is not None:
            params["projectKeyOrId"] = project_key
        return self._client.get("/rest/agile/1.0/board", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sprints(
        self,
        board_id: int,
        *,
        state: str | None = None,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """List sprints on a board."""
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if state is not None:
            params["state"] = state
        return self._client.get(
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_sprint(self, sprint_id: int) -> dict[str, Any]:
        """Return one sprint by ID."""
        return self._client.get(f"/rest/agile/1.0/sprint/{sprint_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_versions(self, project_key: str) -> list[dict[str, Any]]:
        """List versions defined on a project."""
        if not project_key:
            raise ValueError("project_key must be a non-empty string")
        return self._client.get(f"/rest/api/3/project/{project_key}/versions").json()

    # MARK: - Internal

    @staticmethod
    def _issue_summary(
        issue: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        fields_raw: Any = issue.get("fields") or {}
        fields: dict[str, Any] = (
            cast("dict[str, Any]", fields_raw) if isinstance(fields_raw, dict) else {}
        )
        status_field: Any = fields.get("status") or {}
        assignee_field: Any = fields.get("assignee") or {}
        priority_field: Any = fields.get("priority") or {}
        issuetype_field: Any = fields.get("issuetype") or {}
        status_name: Any = (
            cast("dict[str, Any]", status_field).get("name", "")
            if isinstance(status_field, dict)
            else ""
        )
        assignee_name: Any = (
            cast("dict[str, Any]", assignee_field).get("displayName", "")
            if isinstance(assignee_field, dict)
            else ""
        )
        priority_name: Any = (
            cast("dict[str, Any]", priority_field).get("name", "")
            if isinstance(priority_field, dict)
            else ""
        )
        issuetype_name: Any = (
            cast("dict[str, Any]", issuetype_field).get("name", "")
            if isinstance(issuetype_field, dict)
            else ""
        )
        summary: dict[str, Any] = {
            "issue_ref": f"issue_{index}",
            "key": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "status": status_name,
            "assignee": assignee_name,
            "priority": priority_name,
            "issue_type": issuetype_name,
            "updated": fields.get("updated", ""),
        }
        if include_ids:
            summary["issue_id"] = issue.get("id", "")
        return summary

    @staticmethod
    def _extract_issue_key(candidate: Any) -> str:
        """Pull a Jira issue key (e.g. ``ENG-123``) from an arbitrary value.

        Accepts the raw key string, a dict returned by :meth:`search_issues`
        or :meth:`get_issue` (looking up ``key`` or ``issue_key``), or a list
        containing such dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("issue_key must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[str, Any]", candidate)
            for key in ("key", "issue_key", "issueKey"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, (list, tuple)):
            items = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in items:
                try:
                    return JiraToolSet._extract_issue_key(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Jira issue key from: {candidate!r}")
