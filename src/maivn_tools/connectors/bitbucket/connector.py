"""Bitbucket Cloud REST API v2 connector.

The connector authenticates with either a bearer token (OAuth / access
token) or HTTP Basic auth (Atlassian account email + scoped API token)
and exposes the most useful workspace, repo, pull request, issue,
pipeline, and file endpoints.

Note: Bitbucket Cloud app passwords are deprecated (new ones cannot be
created since 2025-09-09; existing ones are disabled at the 2026-06-09
brownout and fully removed 2026-07-28). The Basic-auth path now expects
an Atlassian account email as the user and a scoped API token as the
secret — the same HTTP Basic scheme, repurposed credentials.

Agent-ready behavior:

* Broad list tools default to small ``pagelen`` (10) and return compact,
  human-readable summaries with stable refs (``repo_ref``, ``pr_ref``,
  ``issue_ref``, ``pipeline_ref``, ``branch_ref``).
* User-facing identifiers like ``pr_id``, ``issue_id``, ``slug``, and
  branch ``name`` are always shown — they are the stable refs used by
  every other tool.
* Opaque Bitbucket UUIDs are hidden by default; set ``include_ids=True``
  only when a follow-up tool needs them.
* Write tools that take ``(workspace, repo_slug)`` accept either the two
  strings, a ``workspace/repo_slug`` shorthand, or a repository dict
  returned from list/get.
* ``merge_pull_request`` accepts the PR dict (from list) directly.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy
from ...auth.basic import BasicAuth
from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_SHA_DISPLAY_LEN = 7


@toolset(prefix="bitbucket")
class BitbucketToolSet:
    """A connector for Bitbucket Cloud REST API v2.

    Supply either ``token`` (OAuth bearer / access token) or both
    ``email`` (your Atlassian account email) and ``api_token`` (a scoped
    Atlassian API token) for HTTP Basic auth. App passwords are
    deprecated; use an API token instead.
    """

    metadata = ProviderMetadata(
        name="bitbucket",
        display_name="Bitbucket Cloud",
        version="0.1.0",
        description="Manage Bitbucket repos, pull requests, issues, and pipelines.",
        auth_modes=(AuthMode.BASIC, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "repository": "Read repos.",
            "repository:write": "Write to repos.",
            "pullrequest": "Read PRs.",
            "pullrequest:write": "Write PRs.",
            "issue:write": "Manage issues.",
            "pipeline:write": "Manage pipelines.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developer.atlassian.com/cloud/bitbucket/rest/intro/",
        homepage_url="https://bitbucket.org/",
        tags=("source-control",),
    )

    def __init__(
        self,
        *,
        token: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        base_url: str = "https://api.bitbucket.org",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if token is None and not (email and api_token):
            raise ValueError("provide either token or email+api_token")
        self.connection = connection
        auth: AuthStrategy
        if token is not None:
            auth = BearerTokenAuth(token)
        else:
            assert email is not None
            assert api_token is not None
            auth = BasicAuth(email, api_token)
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=auth,
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tolerant input helpers

    @staticmethod
    def _resolve_workspace_repo(
        workspace: Any,
        repo_slug: Any = None,
    ) -> tuple[str, str]:
        """Normalize ``(workspace, repo_slug)`` from various shapes.

        Accepts:
        - two strings
        - a single ``"workspace/repo_slug"`` string
        - a repository dict (``full_name`` or ``workspace`` + ``slug``)
        - a PR dict (``destination.repository.full_name``)
        """
        if isinstance(workspace, dict) and repo_slug is None:
            workspace_dict = cast(dict[str, Any], workspace)
            full_name: Any = workspace_dict.get("full_name")
            if isinstance(full_name, str) and "/" in full_name:
                ws, slug = full_name.split("/", 1)
                return ws, slug
            # PR dict: destination.repository.full_name
            destination: Any = workspace_dict.get("destination")
            if isinstance(destination, dict):
                dest_repo: Any = cast(dict[str, Any], destination).get("repository")
                if isinstance(dest_repo, dict):
                    dest_full: Any = cast(dict[str, Any], dest_repo).get("full_name")
                    if isinstance(dest_full, str) and "/" in dest_full:
                        ws, slug = dest_full.split("/", 1)
                        return ws, slug
            ws_obj: Any = workspace_dict.get("workspace")
            ws_value: Any
            if isinstance(ws_obj, dict):
                ws_obj_dict = cast(dict[str, Any], ws_obj)
                ws_value = ws_obj_dict.get("slug") or ws_obj_dict.get("name")
            else:
                ws_value = ws_obj
            slug_value: Any = workspace_dict.get("slug") or workspace_dict.get("name")
            if isinstance(ws_value, str) and isinstance(slug_value, str):
                return ws_value, slug_value
            raise ValueError("repo dict must expose full_name or workspace+slug")
        if isinstance(workspace, str) and repo_slug is None:
            if "/" not in workspace:
                raise ValueError("workspace string without repo_slug must be 'workspace/repo_slug'")
            ws, slug = workspace.split("/", 1)
            return ws, slug
        if isinstance(workspace, str) and isinstance(repo_slug, str) and workspace and repo_slug:
            return workspace, repo_slug
        raise ValueError("provide (workspace, repo_slug), 'workspace/repo_slug', or a repo dict")

    @staticmethod
    def _resolve_pr_id(pr_or_id: Any) -> int:
        """Accept a PR id int or a PR dict with ``id``."""
        if isinstance(pr_or_id, int):
            return pr_or_id
        if isinstance(pr_or_id, dict):
            pr_dict = cast(dict[str, Any], pr_or_id)
            value: Any = pr_dict.get("id") or pr_dict.get("pr_id")
            if isinstance(value, int):
                return value
        raise ValueError("expected an int pr_id or a pull request dict with 'id'")

    # MARK: - Summary helpers

    @staticmethod
    def _short_sha(sha: Any) -> str:
        if isinstance(sha, str) and sha:
            return sha[:_SHA_DISPLAY_LEN]
        return ""

    @staticmethod
    def _user_display(user: Any) -> str:
        if isinstance(user, dict):
            user_dict = cast(dict[str, Any], user)
            for key in ("display_name", "nickname", "username"):
                value: Any = user_dict.get(key)
                if isinstance(value, str):
                    return value
        return ""

    @classmethod
    def _repo_summary(
        cls,
        repo: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        owner: Any = repo.get("workspace") or {}
        main_branch: Any = repo.get("mainbranch") or {}
        summary: dict[str, Any] = {
            "repo_ref": f"repo_{index}",
            "full_name": repo.get("full_name", ""),
            "slug": repo.get("slug", repo.get("name", "")),
            "workspace": (
                cast(dict[str, Any], owner).get("slug", "") if isinstance(owner, dict) else ""
            ),
            "is_private": repo.get("is_private", False),
            "fork_policy": repo.get("fork_policy", ""),
            "description": repo.get("description", "") or "",
            "language": repo.get("language", ""),
            "default_branch": (
                cast(dict[str, Any], main_branch).get("name", "")
                if isinstance(main_branch, dict)
                else ""
            ),
            "updated_on": repo.get("updated_on", ""),
            "website": repo.get("website", ""),
        }
        if include_ids:
            summary["uuid"] = repo.get("uuid")
        return summary

    @classmethod
    def _pr_summary(
        cls,
        pr: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        source: Any = pr.get("source") or {}
        destination: Any = pr.get("destination") or {}
        source_branch: Any = (
            cast(dict[str, Any], source).get("branch", {}).get("name", "")
            if isinstance(source, dict)
            else ""
        )
        dest_branch: Any = (
            cast(dict[str, Any], destination).get("branch", {}).get("name", "")
            if isinstance(destination, dict)
            else ""
        )
        summary: dict[str, Any] = {
            "pr_ref": f"pr_{index}",
            "pr_id": pr.get("id"),
            "title": pr.get("title", ""),
            "state": pr.get("state", ""),
            "author": cls._user_display(pr.get("author")),
            "source_branch": source_branch,
            "destination_branch": dest_branch,
            "comment_count": pr.get("comment_count", 0),
            "task_count": pr.get("task_count", 0),
            "created_on": pr.get("created_on", ""),
            "updated_on": pr.get("updated_on", ""),
        }
        links: Any = pr.get("links")
        if isinstance(links, dict):
            html: Any = cast(dict[str, Any], links).get("html")
            if isinstance(html, dict):
                summary["html_url"] = cast(dict[str, Any], html).get("href", "")
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
            "issue_id": issue.get("id"),
            "title": issue.get("title", ""),
            "state": issue.get("state", ""),
            "kind": issue.get("kind", ""),
            "priority": issue.get("priority", ""),
            "reporter": cls._user_display(issue.get("reporter")),
            "assignee": cls._user_display(issue.get("assignee")),
            "comment_count": issue.get("comment_count", 0),
            "created_on": issue.get("created_on", ""),
            "updated_on": issue.get("updated_on", ""),
        }
        links: Any = issue.get("links")
        if isinstance(links, dict):
            html: Any = cast(dict[str, Any], links).get("html")
            if isinstance(html, dict):
                summary["html_url"] = cast(dict[str, Any], html).get("href", "")
        return summary

    @classmethod
    def _pipeline_summary(
        cls,
        pipeline: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        target: Any = pipeline.get("target") or {}
        state: Any = pipeline.get("state") or {}
        commit: Any = (
            cast(dict[str, Any], target).get("commit") if isinstance(target, dict) else None
        )
        sha: Any = cast(dict[str, Any], commit).get("hash", "") if isinstance(commit, dict) else ""
        summary: dict[str, Any] = {
            "pipeline_ref": f"pipeline_{index}",
            "build_number": pipeline.get("build_number"),
            "state": cast(dict[str, Any], state).get("name", "") if isinstance(state, dict) else "",
            "result": (
                cast(dict[str, Any], state).get("result", {}).get("name", "")
                if isinstance(state, dict)
                and isinstance(cast(dict[str, Any], state).get("result"), dict)
                else ""
            ),
            "branch": (
                cast(dict[str, Any], target).get("ref_name", "") if isinstance(target, dict) else ""
            ),
            "short_sha": cls._short_sha(sha),
            "creator": cls._user_display(pipeline.get("creator")),
            "created_on": pipeline.get("created_on", ""),
            "completed_on": pipeline.get("completed_on", ""),
        }
        if include_ids:
            summary["uuid"] = pipeline.get("uuid")
        return summary

    @classmethod
    def _branch_summary(
        cls,
        branch: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        target: Any = branch.get("target") or {}
        sha: Any = cast(dict[str, Any], target).get("hash", "") if isinstance(target, dict) else ""
        summary: dict[str, Any] = {
            "branch_ref": f"branch_{index}",
            "name": branch.get("name", ""),
            "short_sha": cls._short_sha(sha),
        }
        if include_ids and sha:
            summary["sha"] = sha
        return summary

    # MARK: - User

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the authenticated user.

        Returns the raw user resource — ``username`` is the stable
        identifier.
        """
        return self._client.get("/2.0/user").json()

    # MARK: - Workspaces and repositories

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workspaces(self, *, page: int = 1, pagelen: int = 10) -> dict[str, Any]:
        """List workspaces the user is a member of.

        Returns the raw Bitbucket paged response. Each ``values[*].slug``
        is what you pass as ``workspace`` to other tools.
        """
        return self._client.get(
            "/2.0/workspaces",
            params={"page": page, "pagelen": pagelen},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_repositories(
        self,
        workspace: str,
        *,
        role: str | None = None,
        q: str | None = None,
        sort: str | None = None,
        page: int = 1,
        pagelen: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List repositories in a workspace.

        Best first tool when the user asks "what repos do I have access
        to?". Returns compact summaries: ``repo_ref``, ``full_name``,
        ``slug``, ``workspace``, ``is_private``, ``default_branch``,
        ``description``, ``language``, ``updated_on``.

        Set ``include_metadata=False`` for the raw paged response. Set
        ``include_ids=True`` to expose the opaque Bitbucket ``uuid``
        (internal handle).
        """
        if not workspace:
            raise ValueError("workspace must be a non-empty string")
        params: dict[str, Any] = {"page": page, "pagelen": pagelen}
        if role is not None:
            params["role"] = role
        if q is not None:
            params["q"] = q
        if sort is not None:
            params["sort"] = sort
        raw: Any = self._client.get(
            f"/2.0/repositories/{workspace}",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        raw_dict = cast(dict[str, Any], raw)
        values: list[Any] = raw_dict.get("values", [])
        summaries = [
            self._repo_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return {
            "repositories": summaries,
            "count": len(summaries),
            "page": page,
            "next": raw_dict.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_repository(
        self,
        workspace: str | Mapping[str, Any],
        repo_slug: str | None = None,
    ) -> dict[str, Any]:
        """Return one repository.

        ``workspace`` may also be ``"workspace/repo_slug"`` shorthand or
        a repo dict; in those cases leave ``repo_slug`` unset. Returns
        the raw repository resource.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        return self._client.get(f"/2.0/repositories/{ws}/{slug}").json()

    # MARK: - Pull requests

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pull_requests(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        state: str | None = None,
        q: str | None = None,
        page: int = 1,
        pagelen: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List pull requests.

        Best first tool for PR triage. Returns compact summaries:
        ``pr_ref``, ``pr_id`` (the user-facing PR number used by every
        other PR tool), ``title``, ``state``, ``author``, source/
        destination branches, ``comment_count``, timestamps,
        ``html_url``.

        ``workspace`` accepts the same shapes as :meth:`get_repository`.
        Set ``include_metadata=False`` for the raw paged response.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        params: dict[str, Any] = {"page": page, "pagelen": pagelen}
        if state is not None:
            if state not in {"OPEN", "MERGED", "DECLINED", "SUPERSEDED"}:
                raise ValueError("state must be OPEN/MERGED/DECLINED/SUPERSEDED")
            params["state"] = state
        if q is not None:
            params["q"] = q
        raw: Any = self._client.get(
            f"/2.0/repositories/{ws}/{slug}/pullrequests",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        raw_dict = cast(dict[str, Any], raw)
        values: list[Any] = raw_dict.get("values", [])
        summaries = [
            self._pr_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return {
            "pull_requests": summaries,
            "count": len(summaries),
            "page": page,
            "next": raw_dict.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pull_request(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
    ) -> dict[str, Any]:
        """Return one pull request by ID.

        Returns the raw pull request resource.
        """
        return self._client.get(
            f"/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_pull_request(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        title: str,
        source_branch: str,
        destination_branch: str,
        description: str | None = None,
        close_source_branch: bool | None = None,
        reviewers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Open a pull request.

        ``workspace`` accepts the same shapes as :meth:`get_repository`.
        ``reviewers`` is a list of user UUIDs (the opaque Bitbucket
        identifier). Returns the new pull request resource.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        if not title:
            raise ValueError("workspace, repo_slug, and title must be non-empty")
        payload: dict[str, Any] = {
            "title": title,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": destination_branch}},
        }
        if description is not None:
            payload["description"] = description
        if close_source_branch is not None:
            payload["close_source_branch"] = close_source_branch
        if reviewers is not None:
            payload["reviewers"] = [{"uuid": r} for r in reviewers]
        return self._client.post(
            f"/2.0/repositories/{ws}/{slug}/pullrequests",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def merge_pull_request(
        self,
        workspace: Any,
        repo_slug: Any = None,
        pr_id: Any = None,
        *,
        merge_strategy: str | None = None,
        message: str | None = None,
        close_source_branch: bool | None = None,
    ) -> dict[str, Any]:
        """Merge a pull request. Destructive in effect — confirm with the user.

        Tolerant inputs:
        - ``merge_pull_request("acme", "repo", 1)``
        - ``merge_pull_request("acme/repo", 1)``
        - ``merge_pull_request(pr_dict)`` — pulls workspace, slug, and
          ``id`` from the PR (requires PR objects from
          :meth:`list_pull_requests`/:meth:`get_pull_request`).

        ``merge_strategy`` must be ``merge_commit``, ``squash``, or
        ``fast_forward``.
        """
        ws, slug, pid = self._resolve_workspace_repo_pr(workspace, repo_slug, pr_id)
        payload: dict[str, Any] = {}
        if merge_strategy is not None:
            if merge_strategy not in {"merge_commit", "squash", "fast_forward"}:
                raise ValueError("merge_strategy must be merge_commit/squash/fast_forward")
            payload["merge_strategy"] = merge_strategy
        if message is not None:
            payload["message"] = message
        if close_source_branch is not None:
            payload["close_source_branch"] = close_source_branch
        return self._client.post(
            f"/2.0/repositories/{ws}/{slug}/pullrequests/{pid}/merge",
            json=payload or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def decline_pull_request(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
    ) -> dict[str, Any]:
        """Decline a pull request.

        Returns the updated pull request resource (``state=DECLINED``).
        """
        return self._client.post(
            f"/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/decline",
        ).json()

    # MARK: - Issues

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_issues(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        q: str | None = None,
        page: int = 1,
        pagelen: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List issues.

        Best first tool for issue triage. Returns compact summaries:
        ``issue_ref``, ``issue_id`` (the user-facing issue number),
        ``title``, ``state``, ``kind``, ``priority``, ``reporter``,
        ``assignee``, ``comment_count``, timestamps, ``html_url``.

        ``workspace`` accepts the same shapes as :meth:`get_repository`.
        Set ``include_metadata=False`` for the raw paged response.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        params: dict[str, Any] = {"page": page, "pagelen": pagelen}
        if q is not None:
            params["q"] = q
        raw: Any = self._client.get(
            f"/2.0/repositories/{ws}/{slug}/issues",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        raw_dict = cast(dict[str, Any], raw)
        values: list[Any] = raw_dict.get("values", [])
        summaries = [
            self._issue_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return {
            "issues": summaries,
            "count": len(summaries),
            "page": page,
            "next": raw_dict.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_issue(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        title: str,
        content: str | None = None,
        kind: str = "bug",
        priority: str | None = None,
    ) -> dict[str, Any]:
        """Create an issue.

        ``workspace`` accepts the same shapes as :meth:`get_repository`.
        ``kind`` must be one of ``bug``, ``enhancement``, ``proposal``,
        ``task``. Returns the new issue resource — ``id`` is the
        user-facing identifier.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        if not title:
            raise ValueError("title must be a non-empty string")
        if kind not in {"bug", "enhancement", "proposal", "task"}:
            raise ValueError("kind must be bug/enhancement/proposal/task")
        payload: dict[str, Any] = {"title": title, "kind": kind}
        if content is not None:
            payload["content"] = {"raw": content}
        if priority is not None:
            payload["priority"] = priority
        return self._client.post(
            f"/2.0/repositories/{ws}/{slug}/issues",
            json=payload,
        ).json()

    # MARK: - Pipelines

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pipelines(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        page: int = 1,
        pagelen: int = 10,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List recent pipelines.

        Returns compact summaries: ``pipeline_ref``, ``build_number``
        (the user-facing pipeline number), ``state``, ``result``,
        ``branch``, ``short_sha``, ``creator``, timestamps.

        ``workspace`` accepts the same shapes as :meth:`get_repository`.
        Set ``include_metadata=False`` for the raw paged response.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        raw: Any = self._client.get(
            f"/2.0/repositories/{ws}/{slug}/pipelines",
            params={"page": page, "pagelen": pagelen},
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        raw_dict = cast(dict[str, Any], raw)
        values: list[Any] = raw_dict.get("values", [])
        summaries = [
            self._pipeline_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return {
            "pipelines": summaries,
            "count": len(summaries),
            "page": page,
            "next": raw_dict.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def run_pipeline(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        branch: str | None = None,
        commit: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a pipeline by branch or commit.

        ``workspace`` accepts the same shapes as :meth:`get_repository`.
        Exactly one of ``branch`` or ``commit`` must be provided.
        Returns the new pipeline resource.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        target: dict[str, Any]
        if branch is not None:
            target = {"ref_type": "branch", "type": "pipeline_ref_target", "ref_name": branch}
        elif commit is not None:
            target = {"type": "pipeline_commit_target", "commit": {"hash": commit}}
        else:
            raise ValueError("provide either branch or commit")
        return self._client.post(
            f"/2.0/repositories/{ws}/{slug}/pipelines",
            json={"target": target},
        ).json()

    # MARK: - Repository contents

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_branches(
        self,
        workspace: str,
        repo_slug: str | None = None,
        *,
        q: str | None = None,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List branches.

        Returns compact summaries: ``branch_ref``, ``name`` (the
        user-facing branch identifier), ``short_sha``. Set
        ``include_metadata=False`` for the raw paged response.
        """
        ws, slug = self._resolve_workspace_repo(workspace, repo_slug)
        params: dict[str, Any] = {"page": page}
        if q is not None:
            params["q"] = q
        raw: Any = self._client.get(
            f"/2.0/repositories/{ws}/{slug}/refs/branches",
            params=params,
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        raw_dict = cast(dict[str, Any], raw)
        values: list[Any] = raw_dict.get("values", [])
        summaries = [
            self._branch_summary(cast(dict[str, Any], item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return {
            "branches": summaries,
            "count": len(summaries),
            "page": page,
            "next": raw_dict.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file_contents(
        self,
        workspace: str,
        repo_slug: str,
        *,
        commit_or_branch: str,
        path: str,
    ) -> dict[str, Any]:
        """Return raw file content.

        Bitbucket returns the raw file body; this wraps it as
        ``{"path", "ref", "status", "body"}`` for predictable downstream
        consumption.
        """
        if not workspace or not repo_slug or not commit_or_branch or not path:
            raise ValueError("workspace, repo_slug, commit_or_branch, and path are required")
        response = self._client.get(
            f"/2.0/repositories/{workspace}/{repo_slug}/src/{commit_or_branch}/{path}",
        )
        return {
            "path": path,
            "ref": commit_or_branch,
            "status": response.status,
            "body": response.text(),
        }

    # MARK: - Internal helpers

    def _resolve_workspace_repo_pr(
        self,
        workspace: Any,
        repo_slug: Any,
        pr_id: Any,
    ) -> tuple[str, str, int]:
        """Resolve ``(workspace, repo_slug, pr_id)`` from tolerant inputs."""
        # PR dict alone (workspace) carrying everything
        if (
            isinstance(workspace, dict)
            and repo_slug is None
            and pr_id is None
            and ("id" in workspace or "pr_id" in workspace)
        ):
            pid = self._resolve_pr_id(workspace)
            ws, slug = self._resolve_workspace_repo(workspace)
            return ws, slug, pid
        # full_name shorthand + pr_id
        if (
            isinstance(workspace, str)
            and "/" in workspace
            and isinstance(repo_slug, int)
            and pr_id is None
        ):
            ws, slug = self._resolve_workspace_repo(workspace)
            return ws, slug, repo_slug
        # standard (ws, slug, id)
        if isinstance(workspace, str) and isinstance(repo_slug, str) and isinstance(pr_id, int):
            return workspace, repo_slug, pr_id
        raise ValueError(
            "provide (workspace, repo_slug, pr_id), ('workspace/repo_slug', pr_id), or a PR dict"
        )
