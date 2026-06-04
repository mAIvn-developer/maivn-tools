"""GitLab API v4 connector.

The connector authenticates with a personal access token, project access
token, or OAuth bearer and exposes the most useful project, issue, merge
request, pipeline, branch, and file endpoints.

Agent-ready behavior:

* Broad list tools default to small ``per_page`` (10) and return compact,
  human-readable summaries with stable refs (``project_ref``,
  ``issue_ref``, ``mr_ref``, ``pipeline_ref``, ``branch_ref``,
  ``commit_ref``).
* User-facing identifiers like ``iid`` (issue/MR number), ``branch``,
  ``ref``, and the namespaced ``path_with_namespace`` are always shown
  in summaries — they are stable refs.
* Opaque GitLab numeric IDs (``id``, ``project_id``, ``author.id``) are
  hidden by default; set ``include_ids=True`` only when a follow-up tool
  needs them.
* Write tools that take ``project`` accept the same shapes as the read
  tools: a numeric project ID, a ``group/repo`` path, or a project dict
  returned from list/get.
* ``update_issue`` accepts the issue dict (from list) directly in
  addition to ``(project, iid, fields)``.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_SHA_DISPLAY_LEN = 8


@toolset(prefix="gitlab")
class GitLabToolSet:
    """A connector for the GitLab API v4.

    Args:
        token: Personal access token, project access token, or OAuth bearer.
        base_url: GitLab base URL (``https://gitlab.com`` for SaaS).
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="gitlab",
        display_name="GitLab",
        version="0.1.0",
        description="Manage GitLab projects, issues, merge requests, pipelines, and files.",
        auth_modes=(AuthMode.BEARER, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "read_api": "Read-only API access.",
            "api": "Full API access.",
            "read_repository": "Read repository contents.",
            "write_repository": "Write repository contents.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.gitlab.com/ee/api/",
        homepage_url="https://about.gitlab.com/",
        tags=("source-control", "ci-cd"),
    )

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://gitlab.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tolerant input helpers

    @staticmethod
    def _encode_project(project: Any) -> str:
        """Normalize a project to a URL-encoded path or numeric ID.

        Accepts:
        - int (numeric project ID): returned as string.
        - str (``"group/repo"`` or just an ID): URL-encoded.
        - dict (project resource): pulls ``path_with_namespace`` or
          ``id``.
        """
        if isinstance(project, dict):
            project_dict = cast(dict[str, Any], project)
            ref: Any = (
                project_dict.get("path_with_namespace")
                or project_dict.get("full_path")
                or project_dict.get("id")
            )
            if ref is None:
                raise ValueError("project dict must expose path_with_namespace or id")
            project = ref
        if isinstance(project, int):
            return str(project)
        if isinstance(project, str):
            if not project:
                raise ValueError("project must be non-empty")
            from urllib.parse import quote

            return quote(project, safe="")
        raise ValueError("project must be an int, string, or project dict")

    @staticmethod
    def _resolve_iid(issue_or_iid: Any) -> int:
        """Accept an iid int or an issue dict with ``iid``."""
        if isinstance(issue_or_iid, int):
            return issue_or_iid
        if isinstance(issue_or_iid, dict):
            iid: Any = cast(dict[str, Any], issue_or_iid).get("iid")
            if isinstance(iid, int):
                return iid
        raise ValueError("expected an int iid or an issue dict with 'iid'")

    # MARK: - Summary helpers

    @staticmethod
    def _short_sha(sha: Any) -> str:
        if isinstance(sha, str) and sha:
            return sha[:_SHA_DISPLAY_LEN]
        return ""

    @staticmethod
    def _user_name(user: Any) -> str:
        if isinstance(user, dict):
            user_dict = cast(dict[str, Any], user)
            for key in ("username", "name", "login"):
                value: Any = user_dict.get(key)
                if isinstance(value, str):
                    return value
        return ""

    @classmethod
    def _project_summary(
        cls,
        project: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "project_ref": f"project_{index}",
            "path_with_namespace": project.get("path_with_namespace", ""),
            "name": project.get("name", ""),
            "namespace": (
                project.get("namespace", {}).get("full_path", "")
                if isinstance(project.get("namespace"), dict)
                else ""
            ),
            "visibility": project.get("visibility", ""),
            "default_branch": project.get("default_branch", ""),
            "description": project.get("description") or "",
            "star_count": project.get("star_count", 0),
            "forks_count": project.get("forks_count", 0),
            "open_issues_count": project.get("open_issues_count", 0),
            "last_activity_at": project.get("last_activity_at", ""),
            "web_url": project.get("web_url", ""),
        }
        if include_ids:
            summary["project_id"] = project.get("id")
        return summary

    @classmethod
    def _issue_summary(
        cls,
        issue: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "issue_ref": f"issue_{index}",
            "iid": issue.get("iid"),
            "title": issue.get("title", ""),
            "state": issue.get("state", ""),
            "author": cls._user_name(issue.get("author")),
            "assignees": [
                cls._user_name(a)
                for a in cast(list[Any], issue.get("assignees") or [])
                if isinstance(a, dict)
            ],
            "labels": list(issue.get("labels") or []),
            "user_notes_count": issue.get("user_notes_count", 0),
            "created_at": issue.get("created_at", ""),
            "updated_at": issue.get("updated_at", ""),
            "web_url": issue.get("web_url", ""),
        }
        if include_ids:
            summary["issue_id"] = issue.get("id")
            summary["project_id"] = issue.get("project_id")
        return summary

    @classmethod
    def _mr_summary(
        cls,
        mr: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "mr_ref": f"mr_{index}",
            "iid": mr.get("iid"),
            "title": mr.get("title", ""),
            "state": mr.get("state", ""),
            "draft": mr.get("draft", mr.get("work_in_progress", False)),
            "author": cls._user_name(mr.get("author")),
            "source_branch": mr.get("source_branch", ""),
            "target_branch": mr.get("target_branch", ""),
            "merge_status": mr.get("merge_status"),
            "user_notes_count": mr.get("user_notes_count", 0),
            "created_at": mr.get("created_at", ""),
            "updated_at": mr.get("updated_at", ""),
            "web_url": mr.get("web_url", ""),
        }
        if include_ids:
            summary["mr_id"] = mr.get("id")
            summary["project_id"] = mr.get("project_id")
        return summary

    @classmethod
    def _pipeline_summary(
        cls,
        pipeline: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        sha = pipeline.get("sha") or ""
        summary: dict[str, Any] = {
            "pipeline_ref": f"pipeline_{index}",
            "pipeline_id": pipeline.get("id"),
            "status": pipeline.get("status", ""),
            "source": pipeline.get("source", ""),
            "ref": pipeline.get("ref", ""),
            "short_sha": cls._short_sha(sha),
            "created_at": pipeline.get("created_at", ""),
            "updated_at": pipeline.get("updated_at", ""),
            "web_url": pipeline.get("web_url", ""),
        }
        if include_ids:
            summary["project_id"] = pipeline.get("project_id")
            summary["sha"] = sha
        return summary

    @classmethod
    def _branch_summary(
        cls,
        branch: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        commit: Any = branch.get("commit") or {}
        sha = cast(dict[str, Any], commit).get("id", "") if isinstance(commit, dict) else ""
        summary: dict[str, Any] = {
            "branch_ref": f"branch_{index}",
            "name": branch.get("name", ""),
            "default": branch.get("default", False),
            "protected": branch.get("protected", False),
            "merged": branch.get("merged", False),
            "short_sha": cls._short_sha(sha),
            "web_url": branch.get("web_url", ""),
        }
        if include_ids:
            summary["sha"] = sha
        return summary

    @classmethod
    def _commit_summary(
        cls,
        commit: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        sha = commit.get("id") or commit.get("sha") or ""
        message = commit.get("message") or commit.get("title") or ""
        summary: dict[str, Any] = {
            "commit_ref": f"commit_{index}",
            "short_sha": cls._short_sha(sha),
            "title": commit.get("title", "") or message.splitlines()[0] if message else "",
            "author": commit.get("author_name", ""),
            "authored_at": commit.get("authored_date", "") or commit.get("created_at", ""),
            "web_url": commit.get("web_url", ""),
        }
        if include_ids:
            summary["sha"] = sha
        return summary

    # MARK: - User

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the authenticated user.

        Returns the raw user resource — ``username`` is the stable
        identifier.
        """
        return self._client.get("/api/v4/user").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        search: str | None = None,
        username: str | None = None,
        active: bool | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List GitLab users.

        Returns the raw GitLab user list — ``username`` is the stable
        identifier you can pass to ``assignee_username`` filters.
        """
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if search is not None:
            params["search"] = search
        if username is not None:
            params["username"] = username
        if active is not None:
            params["active"] = str(active).lower()
        return self._client.get("/api/v4/users", params=params).json()

    # MARK: - Projects

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_projects(
        self,
        *,
        search: str | None = None,
        membership: bool | None = None,
        owned: bool | None = None,
        archived: bool | None = None,
        order_by: str = "last_activity_at",
        sort: str = "desc",
        page: int = 1,
        per_page: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List accessible projects.

        Best first tool when the user asks "what projects do I have
        access to?". Returns compact summaries: ``project_ref``,
        ``path_with_namespace`` (the stable namespaced path you pass to
        other tools), ``name``, ``namespace``, ``visibility``,
        ``default_branch``, ``description``, ``star_count``,
        ``last_activity_at``, ``web_url``.

        Set ``include_metadata=False`` to return the raw provider list.
        Set ``include_ids=True`` to include the opaque numeric
        ``project_id`` — that's an internal handle and should not be
        shown in final answers.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "order_by": order_by,
            "sort": sort,
        }
        if search is not None:
            params["search"] = search
        if membership is not None:
            params["membership"] = str(membership).lower()
        if owned is not None:
            params["owned"] = str(owned).lower()
        if archived is not None:
            params["archived"] = str(archived).lower()
        raw: Any = self._client.get("/api/v4/projects", params=params).json()
        if not include_metadata or not isinstance(raw, list):
            return cast("dict[str, Any] | list[dict[str, Any]]", raw)
        items = cast(list[Any], raw)
        summaries = [
            self._project_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"projects": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(self, project: str | int | dict[str, Any]) -> dict[str, Any]:
        """Return a project by ID, namespaced path, or project dict.

        Returns the raw GitLab project resource.
        """
        return self._client.get(f"/api/v4/projects/{self._encode_project(project)}").json()

    # MARK: - Issues

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_issues(
        self,
        project: str | int | dict[str, Any],
        *,
        state: str | None = None,
        labels: list[str] | None = None,
        assignee_username: str | None = None,
        author_username: str | None = None,
        page: int = 1,
        per_page: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List issues in a project.

        Best first tool for issue triage. Returns compact summaries:
        ``issue_ref``, ``iid`` (the stable user-facing issue number),
        ``title``, ``state``, ``author``, ``assignees``, ``labels``,
        timestamps, and ``web_url``.

        Set ``include_metadata=False`` for the raw list. Set
        ``include_ids=True`` to expose the opaque GitLab ``issue_id`` /
        ``project_id`` (internal handles).
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if state is not None:
            if state not in {"opened", "closed", "all"}:
                raise ValueError("state must be opened/closed/all")
            params["state"] = state
        if labels is not None:
            params["labels"] = ",".join(labels)
        if assignee_username is not None:
            params["assignee_username"] = assignee_username
        if author_username is not None:
            params["author_username"] = author_username
        raw: Any = self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/issues",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return cast("dict[str, Any] | list[dict[str, Any]]", raw)
        items = cast(list[Any], raw)
        summaries = [
            self._issue_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"issues": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_issue(self, project: str | int | dict[str, Any], iid: int) -> dict[str, Any]:
        """Return one issue by ``iid`` (the project-scoped issue number).

        Returns the raw issue resource.
        """
        return self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/issues/{iid}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_issue(
        self,
        project: str | int | dict[str, Any],
        *,
        title: str,
        description: str | None = None,
        labels: list[str] | None = None,
        assignee_ids: list[int] | None = None,
        milestone_id: int | None = None,
    ) -> dict[str, Any]:
        """Create an issue.

        Returns the new issue resource — ``iid`` is the project-scoped
        user-facing identifier.
        """
        if not title:
            raise ValueError("title must be a non-empty string")
        payload: dict[str, Any] = {"title": title}
        if description is not None:
            payload["description"] = description
        if labels is not None:
            payload["labels"] = ",".join(labels)
        if assignee_ids is not None:
            payload["assignee_ids"] = assignee_ids
        if milestone_id is not None:
            payload["milestone_id"] = milestone_id
        return self._client.post(
            f"/api/v4/projects/{self._encode_project(project)}/issues",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_issue(
        self,
        project: Any,
        iid: Any = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch an issue.

        Tolerant inputs:
        - ``update_issue("group/repo", 42, {"state_event": "close"})``
        - ``update_issue(issue_dict, {"state_event": "close"})``

        The issue dict shape comes from :meth:`list_issues` (with
        ``include_ids=True`` or in raw mode so ``project_id`` is
        available).
        """
        # Issue-dict shorthand: update_issue(issue_dict, fields)
        if isinstance(project, dict) and isinstance(iid, dict) and fields is None:
            issue_dict = cast(dict[str, Any], project)
            fields = cast(dict[str, Any], iid)
            iid_value = self._resolve_iid(issue_dict)
            project_ref: Any = issue_dict.get("project_id") or issue_dict.get("project")
            if project_ref is None:
                # try web_url to derive the path
                raise ValueError(
                    "issue dict must expose project_id or project (call list_issues "
                    "with include_ids=True)"
                )
            project = project_ref
            iid = iid_value
        if not isinstance(fields, dict) or not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._client.put(
            f"/api/v4/projects/{self._encode_project(project)}/issues/{iid}",
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_issue(
        self,
        project: str | int | dict[str, Any],
        iid: int,
    ) -> dict[str, Any]:
        """Delete an issue. Destructive — confirm with the user.

        Returns ``{"iid": ..., "deleted": True}``.
        """
        self._client.delete(
            f"/api/v4/projects/{self._encode_project(project)}/issues/{iid}",
        )
        return {"iid": iid, "deleted": True}

    # MARK: - Merge requests

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_merge_requests(
        self,
        project: str | int | dict[str, Any],
        *,
        state: str | None = None,
        page: int = 1,
        per_page: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List merge requests.

        Best first tool for MR triage. Returns compact summaries:
        ``mr_ref``, ``iid`` (the stable user-facing MR number),
        ``title``, ``state``, ``draft``, ``author``, ``source_branch``,
        ``target_branch``, ``merge_status``, timestamps, ``web_url``.

        Set ``include_metadata=False`` for the raw list. Set
        ``include_ids=True`` to expose internal ``mr_id`` /
        ``project_id``.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if state is not None:
            if state not in {"opened", "closed", "merged", "all"}:
                raise ValueError("state must be opened/closed/merged/all")
            params["state"] = state
        raw: Any = self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/merge_requests",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return cast("dict[str, Any] | list[dict[str, Any]]", raw)
        items = cast(list[Any], raw)
        summaries = [
            self._mr_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"merge_requests": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_merge_request(
        self,
        project: str | int | dict[str, Any],
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str | None = None,
        assignee_ids: list[int] | None = None,
        reviewer_ids: list[int] | None = None,
        remove_source_branch: bool | None = None,
    ) -> dict[str, Any]:
        """Open a merge request.

        Returns the new merge request resource — ``iid`` is the
        project-scoped user-facing identifier.
        """
        if not source_branch or not target_branch or not title:
            raise ValueError("source_branch, target_branch, and title are required")
        payload: dict[str, Any] = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
        }
        if description is not None:
            payload["description"] = description
        if assignee_ids is not None:
            payload["assignee_ids"] = assignee_ids
        if reviewer_ids is not None:
            payload["reviewer_ids"] = reviewer_ids
        if remove_source_branch is not None:
            payload["remove_source_branch"] = remove_source_branch
        return self._client.post(
            f"/api/v4/projects/{self._encode_project(project)}/merge_requests",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def merge_merge_request(
        self,
        project: str | int | dict[str, Any],
        iid: int,
        *,
        merge_commit_message: str | None = None,
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
    ) -> dict[str, Any]:
        """Merge a merge request. Destructive in effect — confirm with the user.

        Returns the updated merge request resource.
        """
        payload: dict[str, Any] = {}
        if merge_commit_message is not None:
            payload["merge_commit_message"] = merge_commit_message
        if squash is not None:
            payload["squash"] = squash
        if should_remove_source_branch is not None:
            payload["should_remove_source_branch"] = should_remove_source_branch
        return self._client.put(
            f"/api/v4/projects/{self._encode_project(project)}/merge_requests/{iid}/merge",
            json=payload or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_merge_request(
        self,
        project: str | int | dict[str, Any],
        iid: int,
    ) -> dict[str, Any]:
        """Return one merge request by ``iid``.

        Returns the raw merge request resource.
        """
        return self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/merge_requests/{iid}",
        ).json()

    # MARK: - Pipelines

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pipelines(
        self,
        project: str | int | dict[str, Any],
        *,
        status: str | None = None,
        ref: str | None = None,
        page: int = 1,
        per_page: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List pipelines on a project.

        Returns compact summaries: ``pipeline_ref``, ``pipeline_id``
        (numeric ID needed by :meth:`get_pipeline`), ``status``,
        ``source``, ``ref``, ``short_sha``, timestamps, ``web_url``.
        Set ``include_metadata=False`` for the raw list.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if status is not None:
            params["status"] = status
        if ref is not None:
            params["ref"] = ref
        raw: Any = self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/pipelines",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return cast("dict[str, Any] | list[dict[str, Any]]", raw)
        items = cast(list[Any], raw)
        summaries = [
            self._pipeline_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"pipelines": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_pipeline(
        self,
        project: str | int | dict[str, Any],
        *,
        ref: str,
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Trigger a pipeline on a ref.

        ``ref`` is a branch name, tag, or SHA. Returns the new pipeline
        resource.
        """
        if not ref:
            raise ValueError("ref must be a non-empty string")
        payload: dict[str, Any] = {"ref": ref}
        if variables is not None:
            payload["variables"] = [{"key": k, "value": v} for k, v in variables.items()]
        return self._client.post(
            f"/api/v4/projects/{self._encode_project(project)}/pipeline",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pipeline(
        self,
        project: str | int | dict[str, Any],
        pipeline_id: int,
    ) -> dict[str, Any]:
        """Return one pipeline by ID.

        Returns the raw pipeline resource.
        """
        return self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/pipelines/{pipeline_id}",
        ).json()

    # MARK: - Repository files

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file(
        self,
        project: str | int | dict[str, Any],
        *,
        file_path: str,
        ref: str,
    ) -> dict[str, Any]:
        """Get a file from the repository.

        ``ref`` is a branch name, tag, or SHA. Returns the GitLab file
        resource (``content`` is base64-encoded).
        """
        from urllib.parse import quote

        if not file_path or not ref:
            raise ValueError("file_path and ref must be non-empty")
        encoded_project = self._encode_project(project)
        encoded_path = quote(file_path, safe="")
        return self._client.get(
            f"/api/v4/projects/{encoded_project}/repository/files/{encoded_path}",
            params={"ref": ref},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_branches(
        self,
        project: str | int | dict[str, Any],
        *,
        search: str | None = None,
        per_page: int = 25,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List branches.

        Returns compact summaries: ``branch_ref``, ``name`` (the
        user-facing branch identifier), ``default``, ``protected``,
        ``merged``, ``short_sha``, ``web_url``. Set
        ``include_metadata=False`` for the raw list.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page}
        if search is not None:
            params["search"] = search
        raw: Any = self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/repository/branches",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return cast("dict[str, Any] | list[dict[str, Any]]", raw)
        items = cast(list[Any], raw)
        summaries = [
            self._branch_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"branches": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_commits(
        self,
        project: str | int | dict[str, Any],
        *,
        ref_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
        per_page: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List commits.

        Returns compact summaries: ``commit_ref``, ``short_sha``,
        ``title``, ``author``, ``authored_at``, ``web_url``. Set
        ``include_metadata=False`` for the raw list. Set
        ``include_ids=True`` to expose the full ``sha``.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page}
        if ref_name is not None:
            params["ref_name"] = ref_name
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        raw: Any = self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/repository/commits",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return cast("dict[str, Any] | list[dict[str, Any]]", raw)
        items = cast(list[Any], raw)
        summaries = [
            self._commit_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"commits": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_blobs(
        self,
        project: str | int | dict[str, Any],
        *,
        search: str,
        ref: str | None = None,
    ) -> dict[str, Any]:
        """Search file contents (blob search).

        Returns the raw GitLab search envelope.
        """
        if not search:
            raise ValueError("search must be a non-empty string")
        params: dict[str, Any] = {"scope": "blobs", "search": search}
        if ref is not None:
            params["ref"] = ref
        return self._client.get(
            f"/api/v4/projects/{self._encode_project(project)}/search",
            params=params,
        ).json()
