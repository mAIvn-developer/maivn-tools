"""GitHub REST API v3 connector.

The connector authenticates with a personal access token (classic or
fine-grained) or any GitHub-issued bearer token and exposes the most useful
issue, pull-request, repository, code-search, and file-content endpoints.

Auth scopes are advertised through :attr:`metadata.scopes` but enforced by
GitHub itself. Each ``@toolify``-marked method declares the appropriate
:class:`PermissionFlag` so hosts can gate them.

Agent-ready behavior:

* Broad list/search tools default to small ``per_page`` (10) and return
  compact, human-readable summaries with stable refs like ``issue_ref``,
  ``pr_ref``, ``repo_ref``, ``branch_ref``, ``commit_ref``, ``run_ref``,
  ``workflow_ref``, ``release_ref``. Raw GitHub IDs (``id``, ``node_id``)
  are hidden by default. Set ``include_ids=True`` only when a follow-up
  tool needs them.
* User-facing identifiers like ``issue_number``, ``pr_number``, ``sha``,
  ``branch``, ``tag_name``, and ``full_name`` are always shown — they are
  stable, human-readable refs (not opaque internal handles).
* Write tools that take ``(owner, repo)`` accept either two strings, a
  ``full_name`` like ``"octocat/Hello-World"``, or a repo dict returned
  by list/search. ``update_issue`` / ``merge_pull_request`` /
  ``delete_branch`` also accept the issue/PR dict directly.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

GITHUB_API_URL = "https://api.github.com"
GITHUB_ACCEPT_HEADER = "application/vnd.github+json"
GITHUB_API_VERSION = "2022-11-28"

_SHA_DISPLAY_LEN = 7

# A decoded GitHub JSON response is either an object or an array of objects.
_JsonObject = dict[str, Any]
_JsonResponse = _JsonObject | list[Any]


@toolset(prefix="github")
class GitHubToolSet:
    """A connector for GitHub REST API v3.

    Args:
        token: Personal access token, fine-grained PAT, or installation
            token. Never logged or surfaced through :meth:`describe`.
        base_url: Override for self-hosted GitHub Enterprise installations.
            Defaults to ``https://api.github.com``.
        transport: Optional :class:`HttpTransport` override, primarily for
            tests.
        user_agent: GitHub requires a non-empty user agent. Defaults to a
            descriptive ``maivn-tools/...`` string.
    """

    metadata = ProviderMetadata(
        name="github",
        display_name="GitHub",
        version="0.1.0",
        description="Read and write GitHub repositories, issues, and pull requests.",
        auth_modes=(AuthMode.BEARER,),
        scopes={
            "repo": "Full control of private repositories.",
            "public_repo": "Access to public repositories.",
            "read:org": "Read-only access to organization membership.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.github.com/en/rest",
        homepage_url="https://github.com",
        tags=("developer", "code", "git"),
    )

    def __init__(
        self,
        token: str,
        *,
        base_url: str = GITHUB_API_URL,
        transport: HttpTransport | None = None,
        user_agent: str = "maivn-tools-github/0.1",
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        if not user_agent:
            raise ValueError("user_agent must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url,
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={
                "Accept": GITHUB_ACCEPT_HEADER,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": user_agent,
            },
        )

    @property
    def client(self) -> HttpClient:
        """Return the underlying :class:`HttpClient`."""
        return self._client

    # MARK: - Tolerant input helpers

    @staticmethod
    def _resolve_repo(
        owner: Any,
        repo: Any = None,
    ) -> tuple[str, str]:
        """Normalize ``(owner, repo)`` from a variety of shapes.

        Accepts:
        - two strings: ``("octocat", "Hello-World")``
        - a single ``"owner/repo"`` string in ``owner``
        - a repo dict (as returned by list/search) in ``owner``
        """
        # Case 1: dict (repo object from list/search)
        if isinstance(owner, dict) and repo is None:
            owner_dict = GitHubToolSet._as_dict(owner)
            full_name = owner_dict.get("full_name")
            if isinstance(full_name, str) and "/" in full_name:
                owner_part, repo_part = full_name.split("/", 1)
                return owner_part, repo_part
            owner_obj: Any = owner_dict.get("owner")
            owner_candidate: Any
            if isinstance(owner_obj, dict):
                owner_obj_dict = GitHubToolSet._as_dict(owner_obj)
                owner_candidate = owner_obj_dict.get("login") or owner_obj_dict.get("name")
            else:
                owner_candidate = owner_obj
            repo_candidate: Any = owner_dict.get("name")
            if isinstance(owner_candidate, str) and isinstance(repo_candidate, str):
                return owner_candidate, repo_candidate
            raise ValueError("repo dict must expose full_name or owner+name")
        # Case 2: full_name string in owner, repo omitted
        if isinstance(owner, str) and repo is None:
            if "/" not in owner:
                raise ValueError("owner string without repo must be 'owner/repo'")
            owner_part, repo_part = owner.split("/", 1)
            return owner_part, repo_part
        # Case 3: two strings
        if isinstance(owner, str) and isinstance(repo, str) and owner and repo:
            return owner, repo
        raise ValueError("provide (owner, repo) strings, 'owner/repo', or a repo dict")

    @staticmethod
    def _resolve_issue_number(issue_or_number: Any) -> int:
        """Accept an issue/PR number, or an issue/PR dict with ``number``."""
        if isinstance(issue_or_number, int):
            return issue_or_number
        if isinstance(issue_or_number, dict):
            issue_dict = GitHubToolSet._as_dict(issue_or_number)
            number = issue_dict.get("number") or issue_dict.get("issue_number")
            if isinstance(number, int):
                return number
        raise ValueError("expected an int or an issue/PR dict with a 'number' field")

    @staticmethod
    def _resolve_branch_name(branch_or_dict: Any) -> str:
        """Accept a branch name string or a branch dict with ``name`` field."""
        if isinstance(branch_or_dict, str) and branch_or_dict:
            return branch_or_dict
        if isinstance(branch_or_dict, dict):
            branch_dict = GitHubToolSet._as_dict(branch_or_dict)
            name = branch_dict.get("name") or branch_dict.get("branch")
            if isinstance(name, str) and name:
                return name
        raise ValueError("expected a branch name string or a branch dict with 'name'")

    # MARK: - Summary helpers

    @staticmethod
    def _short_sha(sha: Any) -> str:
        if isinstance(sha, str) and sha:
            return sha[:_SHA_DISPLAY_LEN]
        return ""

    @staticmethod
    def _user_login(user: Any) -> str:
        if isinstance(user, dict):
            user_dict = GitHubToolSet._as_dict(user)
            login = user_dict.get("login")
            if isinstance(login, str):
                return login
        return ""

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        """Return ``value`` as a typed dict, or an empty dict when it is not one.

        ``isinstance`` narrows a dynamic value to ``dict[Unknown, Unknown]``;
        the cast restores the first-party ``dict[str, Any]`` shape used here.
        """
        if isinstance(value, dict):
            return cast("dict[str, Any]", value)
        return {}

    @staticmethod
    def _label_name(label: Any) -> Any:
        if isinstance(label, dict):
            return cast("dict[str, Any]", label).get("name", "")
        return str(label)

    @classmethod
    def _repo_summary(
        cls,
        repo: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "repo_ref": f"repo_{index}",
            "full_name": repo.get("full_name", ""),
            "name": repo.get("name", ""),
            "owner": cls._user_login(repo.get("owner")),
            "private": repo.get("private", False),
            "fork": repo.get("fork", False),
            "default_branch": repo.get("default_branch", ""),
            "description": repo.get("description") or "",
            "language": repo.get("language") or "",
            "stargazers_count": repo.get("stargazers_count", 0),
            "forks_count": repo.get("forks_count", 0),
            "open_issues_count": repo.get("open_issues_count", 0),
            "updated_at": repo.get("updated_at", ""),
            "html_url": repo.get("html_url", ""),
        }
        if include_ids:
            summary["repo_id"] = repo.get("id")
            summary["node_id"] = repo.get("node_id")
        return summary

    @classmethod
    def _issue_summary(
        cls,
        issue: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        labels_raw: list[Any] = issue.get("labels") or []
        assignees_raw: list[Any] = issue.get("assignees") or []
        labels: list[Any] = [cls._label_name(label) for label in labels_raw]
        assignees: list[str] = [cls._user_login(a) for a in assignees_raw if isinstance(a, dict)]
        summary: dict[str, Any] = {
            "issue_ref": f"issue_{index}",
            "issue_number": issue.get("number"),
            "title": issue.get("title", ""),
            "state": issue.get("state", ""),
            "author": cls._user_login(issue.get("user")),
            "labels": labels,
            "assignees": assignees,
            "comments": issue.get("comments", 0),
            "created_at": issue.get("created_at", ""),
            "updated_at": issue.get("updated_at", ""),
            "html_url": issue.get("html_url", ""),
            "is_pull_request": "pull_request" in issue,
        }
        if include_ids:
            summary["issue_id"] = issue.get("id")
            summary["node_id"] = issue.get("node_id")
        return summary

    @classmethod
    def _pr_summary(
        cls,
        pr: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        head = cls._as_dict(pr.get("head"))
        base = cls._as_dict(pr.get("base"))
        head_ref = head.get("ref", "")
        base_ref = base.get("ref", "")
        summary: dict[str, Any] = {
            "pr_ref": f"pr_{index}",
            "pr_number": pr.get("number"),
            "title": pr.get("title", ""),
            "state": pr.get("state", ""),
            "draft": pr.get("draft", False),
            "author": cls._user_login(pr.get("user")),
            "head": head_ref,
            "base": base_ref,
            "merged": pr.get("merged", False),
            "mergeable_state": pr.get("mergeable_state"),
            "comments": pr.get("comments", 0),
            "review_comments": pr.get("review_comments", 0),
            "created_at": pr.get("created_at", ""),
            "updated_at": pr.get("updated_at", ""),
            "html_url": pr.get("html_url", ""),
        }
        if include_ids:
            summary["pr_id"] = pr.get("id")
            summary["node_id"] = pr.get("node_id")
        return summary

    @classmethod
    def _commit_summary(
        cls,
        commit: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        commit_obj = cls._as_dict(commit.get("commit"))
        author: Any = commit_obj.get("author")
        message: Any = commit_obj.get("message", "")
        sha: Any = commit.get("sha") or ""
        author_dict = cls._as_dict(author)
        summary: dict[str, Any] = {
            "commit_ref": f"commit_{index}",
            "sha": sha,
            "short_sha": cls._short_sha(sha),
            "message": (message or "").splitlines()[0] if message else "",
            "author": author_dict.get("name", "") if isinstance(author, dict) else "",
            "authored_at": author_dict.get("date", "") if isinstance(author, dict) else "",
            "html_url": commit.get("html_url", ""),
        }
        if include_ids:
            summary["node_id"] = commit.get("node_id")
        return summary

    @classmethod
    def _branch_summary(
        cls,
        branch: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        commit = cls._as_dict(branch.get("commit"))
        sha = commit.get("sha", "")
        summary: dict[str, Any] = {
            "branch_ref": f"branch_{index}",
            "name": branch.get("name", ""),
            "sha": sha,
            "short_sha": cls._short_sha(sha),
            "protected": branch.get("protected", False),
        }
        if include_ids:
            summary["commit_node_id"] = commit.get("node_id")
        return summary

    @classmethod
    def _workflow_summary(
        cls,
        workflow: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "workflow_ref": f"workflow_{index}",
            "workflow_id": workflow.get("id"),
            "name": workflow.get("name", ""),
            "state": workflow.get("state", ""),
            "path": workflow.get("path", ""),
            "created_at": workflow.get("created_at", ""),
            "updated_at": workflow.get("updated_at", ""),
            "html_url": workflow.get("html_url", ""),
        }
        if include_ids:
            summary["node_id"] = workflow.get("node_id")
        return summary

    @classmethod
    def _run_summary(
        cls,
        run: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        sha = run.get("head_sha") or ""
        summary: dict[str, Any] = {
            "run_ref": f"run_{index}",
            "run_id": run.get("id"),
            "name": run.get("name", ""),
            "display_title": run.get("display_title", ""),
            "status": run.get("status", ""),
            "conclusion": run.get("conclusion"),
            "event": run.get("event", ""),
            "branch": run.get("head_branch", ""),
            "short_sha": cls._short_sha(sha),
            "run_number": run.get("run_number"),
            "run_attempt": run.get("run_attempt"),
            "actor": cls._user_login(run.get("actor")),
            "created_at": run.get("created_at", ""),
            "updated_at": run.get("updated_at", ""),
            "html_url": run.get("html_url", ""),
        }
        if include_ids:
            summary["node_id"] = run.get("node_id")
            summary["check_suite_id"] = run.get("check_suite_id")
        return summary

    @classmethod
    def _release_summary(
        cls,
        release: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "release_ref": f"release_{index}",
            "tag_name": release.get("tag_name", ""),
            "name": release.get("name", ""),
            "draft": release.get("draft", False),
            "prerelease": release.get("prerelease", False),
            "author": cls._user_login(release.get("author")),
            "created_at": release.get("created_at", ""),
            "published_at": release.get("published_at", ""),
            "html_url": release.get("html_url", ""),
        }
        if include_ids:
            summary["release_id"] = release.get("id")
            summary["node_id"] = release.get("node_id")
        return summary

    # MARK: - User

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_authenticated_user(self) -> dict[str, Any]:
        """Return the user the supplied token belongs to.

        Best first call to confirm the token works and to discover the
        authenticated ``login``. Returns the raw GitHub user resource.
        """
        return self._client.get("/user").json()

    # MARK: - Repositories

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_repositories(
        self,
        type: str = "owner",
        sort: str = "updated",
        per_page: int = 10,
        page: int = 1,
        *,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List repositories accessible to the authenticated user.

        Best first tool when the user asks "what repos do I have access
        to?". Returns compact summaries (``repo_ref``, ``full_name``,
        ``owner``, ``private``, ``default_branch``, ``description``,
        ``language``, ``stargazers_count``, ``updated_at``, ``html_url``).
        Use ``full_name`` from a summary as the input to other tools.

        Set ``include_metadata=False`` to return the raw provider list
        unchanged. Set ``include_ids=True`` to include the opaque GitHub
        repo ``id`` / ``node_id`` — they are internal handles and should
        not be shown in final answers.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        raw: _JsonResponse = self._client.get(
            "/user/repos",
            params={"type": type, "sort": sort, "per_page": per_page, "page": page},
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._repo_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {"repositories": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_repository(
        self,
        owner: str | Mapping[str, Any],
        repo: str | None = None,
    ) -> dict[str, Any]:
        """Return metadata for a single repository.

        ``owner`` may also be a ``"owner/repo"`` string or a repo dict from
        a list/search response — in those cases leave ``repo`` unset.
        Returns the raw GitHub repository resource.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        return self._client.get(f"/repos/{owner_name}/{repo_name}").json()

    # MARK: - Issues

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_issues(
        self,
        owner: str,
        repo: str | None = None,
        *,
        state: str = "open",
        labels: str | None = None,
        assignee: str | None = None,
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List issues in a repository.

        Best first tool for issue triage. ``owner`` accepts the same
        shapes as :meth:`get_repository`. Returns compact summaries:
        ``issue_ref``, ``issue_number`` (the stable user-facing number
        used by every other issue tool), ``title``, ``state``, ``author``,
        ``labels``, ``assignees``, ``comments``, timestamps, and
        ``html_url``. Note GitHub conflates issues and PRs here —
        ``is_pull_request=True`` flags the PR rows.

        ``per_page`` defaults to 10. Set ``include_metadata=False`` to
        return the raw provider list. Set ``include_ids=True`` to include
        the opaque ``issue_id`` / ``node_id`` (internal handles).
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "state": state,
            "per_page": per_page,
            "page": page,
        }
        if labels is not None:
            params["labels"] = labels
        if assignee is not None:
            params["assignee"] = assignee
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}/issues", params=params
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._issue_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {
            "issues": summaries,
            "count": len(summaries),
            "page": page,
            "state": state,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_issue(
        self,
        owner: str,
        repo: str | int | None = None,
        issue_number: int | None = None,
    ) -> dict[str, Any]:
        """Return one issue by number.

        ``owner`` accepts the same shapes as :meth:`get_repository`. When
        ``owner`` is a string, pass ``repo`` and ``issue_number``
        positionally. Returns the raw issue resource.
        """
        owner_name, repo_name, number = self._resolve_owner_repo_issue(owner, repo, issue_number)
        return self._client.get(f"/repos/{owner_name}/{repo_name}/issues/{number}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_issue(
        self,
        owner: str,
        repo: str | None = None,
        *,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an issue.

        ``owner`` accepts the same shapes as :meth:`get_repository`.
        Returns the new issue resource — ``number`` is the user-facing
        identifier used by other issue tools.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if not title:
            raise ValueError("title must be a non-empty string")
        payload: dict[str, Any] = {"title": title}
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = list(labels)
        if assignees is not None:
            payload["assignees"] = list(assignees)
        return self._client.post(f"/repos/{owner_name}/{repo_name}/issues", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a comment on an existing issue or PR.

        Returns the new comment resource (``id``, ``body``, ``user``,
        ``created_at``).
        """
        if not body:
            raise ValueError("body must be a non-empty string")
        return self._client.post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        ).json()

    # MARK: - Pull requests

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pull_requests(
        self,
        owner: str,
        repo: str | None = None,
        *,
        state: str = "open",
        base: str | None = None,
        head: str | None = None,
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List pull requests in a repository.

        Best first tool for PR triage. ``owner`` accepts the same shapes
        as :meth:`get_repository`. Returns compact summaries: ``pr_ref``,
        ``pr_number`` (the stable user-facing number), ``title``,
        ``state``, ``draft``, ``author``, ``head``/``base`` branches,
        ``merged``, ``mergeable_state``, ``comments``, timestamps, and
        ``html_url``.

        ``per_page`` defaults to 10. Set ``include_metadata=False`` to
        return the raw provider list. Set ``include_ids=True`` to expose
        the opaque ``pr_id`` / ``node_id`` (internal handles).
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
        if base is not None:
            params["base"] = base
        if head is not None:
            params["head"] = head
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}/pulls", params=params
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._pr_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {
            "pull_requests": summaries,
            "count": len(summaries),
            "page": page,
            "state": state,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pull_request(
        self,
        owner: str,
        repo: str | int | None = None,
        pull_number: int | None = None,
    ) -> dict[str, Any]:
        """Return one pull request by number.

        ``owner`` accepts the same shapes as :meth:`get_repository`.
        Returns the raw pull request resource.
        """
        owner_name, repo_name, number = self._resolve_owner_repo_issue(owner, repo, pull_number)
        return self._client.get(f"/repos/{owner_name}/{repo_name}/pulls/{number}").json()

    # MARK: - Files and search

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> dict[str, Any]:
        """Return file metadata and base64-encoded contents.

        ``ref`` is a branch name, tag, or SHA — defaults to the default
        branch. Returns the GitHub contents resource; ``content`` is
        base64-encoded.
        """
        params = {"ref": ref} if ref else None
        return self._client.get(f"/repos/{owner}/{repo}/contents/{path}", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_code(
        self,
        query: str,
        *,
        sort: str | None = None,
        order: str = "desc",
        per_page: int = 10,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search code across repositories the token can see.

        Use GitHub code search syntax (``repo:owner/name`` qualifiers,
        ``language:`` filters, etc.). Returns the raw GitHub search
        envelope ``{"total_count", "incomplete_results", "items"}``.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "q": query,
            "order": order,
            "per_page": per_page,
            "page": page,
        }
        if sort is not None:
            params["sort"] = sort
        return self._client.get("/search/code", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_issues(
        self,
        query: str,
        *,
        sort: str | None = None,
        order: str = "desc",
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Search issues and pull requests across visible repositories.

        Use qualifiers like ``type:pr``, ``is:open``, ``author:me``,
        ``repo:owner/name``. Returns compact summaries with ``issue_ref``,
        ``issue_number``, ``title``, ``state``, ``author``, ``labels``,
        and ``is_pull_request``. Set ``include_metadata=False`` for the
        raw search envelope. Set ``include_ids=True`` to expose internal
        ``issue_id`` / ``node_id``.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "q": query,
            "order": order,
            "per_page": per_page,
            "page": page,
        }
        if sort is not None:
            params["sort"] = sort
        raw: _JsonResponse = self._client.get("/search/issues", params=params).json()
        if not include_metadata:
            return cast("dict[str, Any]", raw)
        items: list[Any] = raw.get("items", []) if isinstance(raw, dict) else []
        summaries = [
            self._issue_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {
            "issues": summaries,
            "total_count": raw.get("total_count", len(summaries))
            if isinstance(raw, dict)
            else len(summaries),
            "incomplete_results": raw.get("incomplete_results", False)
            if isinstance(raw, dict)
            else False,
            "page": page,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_repositories(
        self,
        query: str,
        *,
        sort: str | None = None,
        order: str = "desc",
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Search repositories by name, description, or topic.

        Returns compact summaries with ``repo_ref``, ``full_name``,
        ``owner``, ``description``, ``language``, ``stargazers_count``,
        and ``html_url``. Use ``full_name`` as input to other tools.
        Set ``include_metadata=False`` for the raw search envelope.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "q": query,
            "order": order,
            "per_page": per_page,
            "page": page,
        }
        if sort is not None:
            params["sort"] = sort
        raw: _JsonResponse = self._client.get("/search/repositories", params=params).json()
        if not include_metadata:
            return cast("dict[str, Any]", raw)
        items: list[Any] = raw.get("items", []) if isinstance(raw, dict) else []
        summaries = [
            self._repo_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {
            "repositories": summaries,
            "total_count": raw.get("total_count", len(summaries))
            if isinstance(raw, dict)
            else len(summaries),
            "incomplete_results": raw.get("incomplete_results", False)
            if isinstance(raw, dict)
            else False,
            "page": page,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_users(
        self,
        query: str,
        *,
        sort: str | None = None,
        order: str = "desc",
        per_page: int = 10,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search GitHub users.

        Returns the raw GitHub search envelope ``{"total_count",
        "incomplete_results", "items"}`` — user logins in ``items[*].login``
        are stable and safe to show in final answers.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "q": query,
            "order": order,
            "per_page": per_page,
            "page": page,
        }
        if sort is not None:
            params["sort"] = sort
        return self._client.get("/search/users", params=params).json()

    # MARK: - Issue mutations

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_issue(
        self,
        owner: Any,
        repo: Any = None,
        issue_number: Any = None,
        patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch an issue (title/body/state/labels/assignees).

        Tolerant inputs: pass either ``(owner, repo, issue_number, patch)``
        or pass an issue dict (from :meth:`list_issues`) as the first
        argument with ``patch`` as the second positional. Examples::

            update_issue("octocat", "Hello", 42, {"state": "closed"})
            update_issue(issue_dict, {"state": "closed"})

        Returns the updated issue resource.
        """
        # Pattern: update_issue(issue_dict, patch_dict)
        if isinstance(owner, dict) and isinstance(repo, dict) and issue_number is None:
            patch = self._as_dict(repo)
            number = self._resolve_issue_number(owner)
            owner_name, repo_name = self._resolve_repo(owner)
            owner = owner_name
            repo = repo_name
            issue_number = number
        else:
            owner_name, repo_name, number = self._resolve_owner_repo_issue(
                owner, repo, issue_number
            )
            owner = owner_name
            repo = repo_name
            issue_number = number
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def close_issue(
        self,
        owner: Any,
        repo: Any = None,
        issue_number: Any = None,
    ) -> dict[str, Any]:
        """Close an issue (sets ``state=closed``).

        Accepts ``(owner, repo, issue_number)`` or a single issue dict.
        """
        owner_name, repo_name, number = self._resolve_owner_repo_issue(owner, repo, issue_number)
        return self._client.patch(
            f"/repos/{owner_name}/{repo_name}/issues/{number}",
            json={"state": "closed"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reopen_issue(
        self,
        owner: Any,
        repo: Any = None,
        issue_number: Any = None,
    ) -> dict[str, Any]:
        """Reopen a closed issue.

        Accepts ``(owner, repo, issue_number)`` or a single issue dict.
        """
        owner_name, repo_name, number = self._resolve_owner_repo_issue(owner, repo, issue_number)
        return self._client.patch(
            f"/repos/{owner_name}/{repo_name}/issues/{number}",
            json={"state": "open"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_issue_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        labels: list[str],
    ) -> dict[str, Any]:
        """Add labels to an issue or pull request.

        Returns the list of labels now on the issue.
        """
        if not labels:
            raise ValueError("labels must contain at least one label")
        return self._client.post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json={"labels": list(labels)},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def remove_issue_label(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        label: str,
    ) -> dict[str, Any]:
        """Remove a label from an issue or pull request.

        Returns ``{"removed": <label>}`` on success.
        """
        if not label:
            raise ValueError("label must be a non-empty string")
        self._client.delete(
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}",
        )
        return {"removed": label}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List comments on an issue or pull request.

        Returns the raw list of comment resources — ``user.login``,
        ``body``, and timestamps are the most useful fields.
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_issue_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
    ) -> dict[str, Any]:
        """Update the body of an existing issue/PR comment.

        ``comment_id`` is the numeric ID returned by
        :meth:`list_issue_comments`.
        """
        if not body:
            raise ValueError("body must be a non-empty string")
        return self._client.patch(
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
            json={"body": body},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_issue_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
    ) -> dict[str, Any]:
        """Delete an issue/PR comment. Destructive — confirm with the user.

        Returns ``{"id": ..., "deleted": True}``.
        """
        self._client.delete(f"/repos/{owner}/{repo}/issues/comments/{comment_id}")
        return {"id": comment_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def lock_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        lock_reason: str | None = None,
    ) -> dict[str, Any]:
        """Lock conversation on an issue or PR.

        ``lock_reason`` must be one of ``off-topic``, ``too heated``,
        ``resolved``, ``spam``.
        """
        valid_reasons = {"off-topic", "too heated", "resolved", "spam"}
        if lock_reason is not None and lock_reason not in valid_reasons:
            raise ValueError("lock_reason must be off-topic, too heated, resolved, or spam")
        payload: dict[str, Any] = {}
        if lock_reason is not None:
            payload["lock_reason"] = lock_reason
        response = self._client.put(
            f"/repos/{owner}/{repo}/issues/{issue_number}/lock",
            json=payload or None,
        )
        return {"locked": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unlock_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        """Unlock conversation on an issue or PR."""
        response = self._client.delete(f"/repos/{owner}/{repo}/issues/{issue_number}/lock")
        return {"unlocked": True, "status": response.status}

    # MARK: - Pull request mutations & reviews

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_pull_request(
        self,
        owner: str,
        repo: str | None = None,
        *,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
        draft: bool = False,
        maintainer_can_modify: bool = True,
    ) -> dict[str, Any]:
        """Open a new pull request.

        ``owner`` accepts the same shapes as :meth:`get_repository`.
        ``head`` and ``base`` are branch names. Returns the new PR
        resource — ``number`` is the user-facing identifier.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if not title or not head or not base:
            raise ValueError("title, head, and base must be non-empty")
        payload: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
            "maintainer_can_modify": maintainer_can_modify,
        }
        if body is not None:
            payload["body"] = body
        return self._client.post(f"/repos/{owner_name}/{repo_name}/pulls", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch an existing pull request (title/body/state/base).

        Returns the updated PR resource.
        """
        if not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def merge_pull_request(
        self,
        owner: Any,
        repo: Any = None,
        pull_number: Any = None,
        *,
        commit_title: str | None = None,
        commit_message: str | None = None,
        merge_method: str = "merge",
    ) -> dict[str, Any]:
        """Merge a pull request. Destructive in effect — confirm with the user.

        Tolerant inputs: pass either ``(owner, repo, pull_number)`` or a
        single PR dict (from :meth:`list_pull_requests`) as the first
        argument. ``merge_method`` must be ``merge``, ``squash``, or
        ``rebase``.
        """
        owner_name, repo_name, number = self._resolve_owner_repo_issue(owner, repo, pull_number)
        if merge_method not in {"merge", "squash", "rebase"}:
            raise ValueError("merge_method must be merge, squash, or rebase")
        payload: dict[str, Any] = {"merge_method": merge_method}
        if commit_title is not None:
            payload["commit_title"] = commit_title
        if commit_message is not None:
            payload["commit_message"] = commit_message
        return self._client.put(
            f"/repos/{owner_name}/{repo_name}/pulls/{number}/merge",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pull_request_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List files changed by a pull request.

        Returns the raw GitHub file list — each entry exposes
        ``filename``, ``status``, ``additions``, ``deletions``,
        ``changes``, and ``patch`` (for small files).
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pull_request_commits(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List commits in a pull request.

        Returns the raw GitHub commit list — each entry exposes ``sha``,
        ``commit.message``, ``commit.author``, etc.
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/commits",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pull_request_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List reviews on a pull request.

        Returns review resources with ``state`` (APPROVED, CHANGES_REQUESTED,
        COMMENTED), ``user.login``, ``body``, and ``submitted_at``.
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        body: str | None = None,
        event: str | None = None,
        comments: list[dict[str, Any]] | None = None,
        commit_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a review on a pull request.

        ``event`` must be ``APPROVE``, ``REQUEST_CHANGES``, ``COMMENT``,
        or ``PENDING`` (or omitted to leave the review pending).
        """
        if event is not None and event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT", "PENDING"}:
            raise ValueError("event must be APPROVE, REQUEST_CHANGES, COMMENT, or PENDING")
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if event is not None:
            payload["event"] = event
        if comments is not None:
            payload["comments"] = comments
        if commit_id is not None:
            payload["commit_id"] = commit_id
        return self._client.post(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def request_pull_request_reviewers(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Request reviewers for a pull request.

        Pass user logins via ``reviewers`` and team slugs via
        ``team_reviewers``. At least one of the two is required.
        """
        if not reviewers and not team_reviewers:
            raise ValueError("Provide at least one of reviewers or team_reviewers")
        payload: dict[str, Any] = {}
        if reviewers:
            payload["reviewers"] = list(reviewers)
        if team_reviewers:
            payload["team_reviewers"] = list(team_reviewers)
        return self._client.post(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers",
            json=payload,
        ).json()

    # MARK: - Branches, commits, refs

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_branches(
        self,
        owner: str,
        repo: str | None = None,
        *,
        protected: bool | None = None,
        per_page: int = 25,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List branches in a repository.

        ``owner`` accepts the same shapes as :meth:`get_repository`.
        Returns compact summaries: ``branch_ref``, ``name`` (the
        user-facing branch identifier), ``sha``, ``short_sha``, and
        ``protected``. Set ``include_metadata=False`` for the raw list.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if protected is not None:
            params["protected"] = str(protected).lower()
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}/branches", params=params
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._branch_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {"branches": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_branch(self, owner: str, repo: str, branch: str) -> dict[str, Any]:
        """Return a single branch.

        Returns the raw branch resource with ``commit`` and ``protected``.
        """
        if not branch:
            raise ValueError("branch must be a non-empty string")
        return self._client.get(f"/repos/{owner}/{repo}/branches/{branch}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_branch(
        self,
        owner: str,
        repo: str,
        *,
        branch: str,
        sha: str,
    ) -> dict[str, Any]:
        """Create a branch ref pointing at ``sha``.

        Returns the new git ref resource.
        """
        if not branch or not sha:
            raise ValueError("branch and sha must be non-empty")
        return self._client.post(
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_branch(
        self,
        owner: Any,
        repo: Any = None,
        branch: Any = None,
    ) -> dict[str, Any]:
        """Delete a branch ref. Destructive — confirm with the user.

        Tolerant inputs:
        - ``delete_branch("octocat", "Hello", "feature/x")``
        - ``delete_branch("octocat/Hello", "feature/x")``
        - ``delete_branch(repo_dict, "feature/x")``
        - ``delete_branch(repo_dict, branch_dict)``  (branch from list_branches)
        """
        # If repo looks like a branch name/dict and branch is None
        if branch is None:
            # delete_branch(owner_or_repo, branch)
            owner_name, repo_name = self._resolve_repo(owner)
            branch_name = self._resolve_branch_name(repo)
        else:
            owner_name, repo_name = self._resolve_repo(owner, repo)
            branch_name = self._resolve_branch_name(branch)
        self._client.delete(f"/repos/{owner_name}/{repo_name}/git/refs/heads/{branch_name}")
        return {"branch": branch_name, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_commits(
        self,
        owner: str,
        repo: str | None = None,
        *,
        sha: str | None = None,
        path: str | None = None,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List commits in a repository with optional filters.

        ``owner`` accepts the same shapes as :meth:`get_repository`.
        Returns compact summaries: ``commit_ref``, ``sha``, ``short_sha``,
        first-line ``message``, ``author``, ``authored_at``, ``html_url``.
        ``per_page`` defaults to 10. Set ``include_metadata=False`` for
        raw commit objects.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        for name, value in (
            ("sha", sha),
            ("path", path),
            ("author", author),
            ("since", since),
            ("until", until),
        ):
            if value is not None:
                params[name] = value
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}/commits", params=params
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._commit_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {"commits": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        """Return one commit by SHA or ref.

        Returns the raw commit resource with ``files`` and ``stats``.
        """
        if not ref:
            raise ValueError("ref must be a non-empty string")
        return self._client.get(f"/repos/{owner}/{repo}/commits/{ref}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def compare_commits(
        self,
        owner: str,
        repo: str,
        base: str,
        head: str,
    ) -> dict[str, Any]:
        """Compare two commit-ish refs.

        Returns the raw compare envelope: ``ahead_by``, ``behind_by``,
        ``status``, ``commits``, ``files``.
        """
        if not base or not head:
            raise ValueError("base and head must be non-empty")
        return self._client.get(f"/repos/{owner}/{repo}/compare/{base}...{head}").json()

    # MARK: - Repository contents

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        message: str,
        content_base64: str,
        branch: str | None = None,
        sha: str | None = None,
        committer: dict[str, Any] | None = None,
        author: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a file. Supply ``sha`` for updates.

        ``content_base64`` is the file's full new bytes encoded as
        base64. The ``sha`` field is required for updates and is the
        blob SHA returned by :meth:`get_file_contents`.
        """
        if not path or not message or not content_base64:
            raise ValueError("path, message, and content_base64 must be non-empty")
        payload: dict[str, Any] = {"message": message, "content": content_base64}
        if branch is not None:
            payload["branch"] = branch
        if sha is not None:
            payload["sha"] = sha
        if committer is not None:
            payload["committer"] = committer
        if author is not None:
            payload["author"] = author
        return self._client.put(
            f"/repos/{owner}/{repo}/contents/{path}",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_repo_file(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        message: str,
        sha: str,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Delete a file in a repository. Destructive — confirm with the user.

        ``sha`` is the file's current blob SHA from
        :meth:`get_file_contents`.
        """
        if not path or not message or not sha:
            raise ValueError("path, message, and sha must be non-empty")
        payload: dict[str, Any] = {"message": message, "sha": sha}
        if branch is not None:
            payload["branch"] = branch
        return self._client.delete(
            f"/repos/{owner}/{repo}/contents/{path}",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_readme(self, owner: str, repo: str, *, ref: str | None = None) -> dict[str, Any]:
        """Return the repository README.

        Returns the contents resource (``content`` is base64-encoded).
        """
        params = {"ref": ref} if ref else None
        return self._client.get(f"/repos/{owner}/{repo}/readme", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tags(
        self,
        owner: str,
        repo: str,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List Git tags.

        Returns raw tag objects with ``name``, ``commit.sha``,
        ``zipball_url``, etc.
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/tags",
            params={"per_page": per_page, "page": page},
        ).json()

    # MARK: - Releases

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_releases(
        self,
        owner: str,
        repo: str | None = None,
        *,
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List releases for a repository.

        Returns compact summaries: ``release_ref``, ``tag_name`` (the
        stable user-facing identifier), ``name``, ``draft``,
        ``prerelease``, ``author``, ``published_at``, ``html_url``.
        Set ``include_metadata=False`` for raw release objects. Set
        ``include_ids=True`` to include the opaque ``release_id``.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}/releases",
            params={"per_page": per_page, "page": page},
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._release_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {"releases": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_release(self, owner: str, repo: str, release_id: int) -> dict[str, Any]:
        """Return one release by ID.

        ``release_id`` is the opaque GitHub release ID from
        :meth:`list_releases` (with ``include_ids=True``).
        """
        return self._client.get(f"/repos/{owner}/{repo}/releases/{release_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_latest_release(self, owner: str, repo: str) -> dict[str, Any]:
        """Return the most recent published, non-draft release."""
        return self._client.get(f"/repos/{owner}/{repo}/releases/latest").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_release(
        self,
        owner: str,
        repo: str,
        *,
        tag_name: str,
        target_commitish: str | None = None,
        name: str | None = None,
        body: str | None = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        """Create a release.

        ``tag_name`` is the user-facing release tag (e.g. ``v1.2.3``).
        Returns the new release resource.
        """
        if not tag_name:
            raise ValueError("tag_name must be a non-empty string")
        payload: dict[str, Any] = {
            "tag_name": tag_name,
            "draft": draft,
            "prerelease": prerelease,
        }
        if target_commitish is not None:
            payload["target_commitish"] = target_commitish
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["body"] = body
        return self._client.post(f"/repos/{owner}/{repo}/releases", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_release(
        self,
        owner: str,
        repo: str,
        release_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch an existing release."""
        if not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(
            f"/repos/{owner}/{repo}/releases/{release_id}",
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_release(self, owner: str, repo: str, release_id: int) -> dict[str, Any]:
        """Delete a release. Destructive — confirm with the user."""
        self._client.delete(f"/repos/{owner}/{repo}/releases/{release_id}")
        return {"id": release_id, "deleted": True}

    # MARK: - Workflows & checks

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workflows(
        self,
        owner: str,
        repo: str | None = None,
        *,
        per_page: int = 25,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List Actions workflows for a repository.

        Returns compact summaries: ``workflow_ref``, ``workflow_id`` (the
        numeric ID needed by :meth:`list_workflow_runs` and
        :meth:`dispatch_workflow`), ``name``, ``state``, ``path``,
        timestamps, and ``html_url``. The ``workflow_id`` is the stable
        identifier — it is not "opaque" in the dangerous sense, the
        Actions API exposes no other handle. ``include_ids=True`` adds
        the GraphQL ``node_id``.

        Set ``include_metadata=False`` for the raw envelope.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}/actions/workflows",
            params={"per_page": per_page, "page": page},
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        workflows: list[Any] = raw.get("workflows", [])
        summaries = [
            self._workflow_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(workflows, start=1)
            if isinstance(item, dict)
        ]
        return {
            "workflows": summaries,
            "total_count": raw.get("total_count", len(summaries)),
            "page": page,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workflow_runs(
        self,
        owner: str,
        repo: str | None = None,
        *,
        workflow_id: int | str | None = None,
        status: str | None = None,
        branch: str | None = None,
        event: str | None = None,
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List workflow runs, optionally narrowed to one workflow.

        Returns compact summaries: ``run_ref``, ``run_id``, ``name``,
        ``display_title``, ``status``, ``conclusion``, ``event``,
        ``branch``, ``short_sha``, ``run_number``, ``run_attempt``,
        ``actor``, timestamps, ``html_url``. ``run_id`` is the stable
        identifier for cancel/rerun. Set ``include_metadata=False`` for
        the raw envelope.
        """
        owner_name, repo_name = self._resolve_repo(owner, repo)
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        suffix = (
            f"/actions/workflows/{workflow_id}/runs" if workflow_id is not None else "/actions/runs"
        )
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        for name, value in (("status", status), ("branch", branch), ("event", event)):
            if value is not None:
                params[name] = value
        raw: _JsonResponse = self._client.get(
            f"/repos/{owner_name}/{repo_name}{suffix}", params=params
        ).json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        runs: list[Any] = raw.get("workflow_runs", [])
        summaries = [
            self._run_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(runs, start=1)
            if isinstance(item, dict)
        ]
        return {
            "workflow_runs": summaries,
            "total_count": raw.get("total_count", len(summaries)),
            "page": page,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_workflow_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Return one workflow run by ID.

        Returns the raw run resource.
        """
        return self._client.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def cancel_workflow_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Cancel a running workflow."""
        response = self._client.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/cancel")
        return {"cancelled": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rerun_workflow(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Re-run a workflow run."""
        response = self._client.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun")
        return {"rerun": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def dispatch_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: int | str,
        *,
        ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a ``workflow_dispatch`` event.

        ``workflow_id`` is the numeric ID from :meth:`list_workflows`.
        ``ref`` is a branch name, tag, or SHA.
        """
        if not ref:
            raise ValueError("ref must be a non-empty string")
        payload: dict[str, Any] = {"ref": ref}
        if inputs is not None:
            payload["inputs"] = inputs
        response = self._client.post(
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            json=payload,
        )
        return {"dispatched": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_check_runs(
        self,
        owner: str,
        repo: str,
        ref: str,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, Any]:
        """List check runs for a ref (branch name, tag, or SHA).

        Returns the raw envelope ``{"total_count", "check_runs"}``.
        """
        if not ref:
            raise ValueError("ref must be a non-empty string")
        return self._client.get(
            f"/repos/{owner}/{repo}/commits/{ref}/check-runs",
            params={"per_page": per_page, "page": page},
        ).json()

    # MARK: - Collaborators, orgs, teams, forks

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_collaborators(
        self,
        owner: str,
        repo: str,
        *,
        affiliation: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List collaborators on a repository.

        Returns raw user resources — ``login`` is the stable identifier.
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if affiliation is not None:
            params["affiliation"] = affiliation
        return self._client.get(
            f"/repos/{owner}/{repo}/collaborators",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_collaborator(
        self,
        owner: str,
        repo: str,
        username: str,
        *,
        permission: str = "push",
    ) -> dict[str, Any]:
        """Invite a collaborator to a repository.

        ``permission`` must be one of ``pull``, ``triage``, ``push``,
        ``maintain``, ``admin``.
        """
        if not username:
            raise ValueError("username must be a non-empty string")
        if permission not in {"pull", "triage", "push", "maintain", "admin"}:
            raise ValueError("permission must be pull, triage, push, maintain, or admin")
        return self._client.put(
            f"/repos/{owner}/{repo}/collaborators/{username}",
            json={"permission": permission},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_collaborator(
        self,
        owner: str,
        repo: str,
        username: str,
    ) -> dict[str, Any]:
        """Remove a collaborator from a repository. Destructive — confirm.

        Returns ``{"username": ..., "removed": True}``.
        """
        if not username:
            raise ValueError("username must be a non-empty string")
        self._client.delete(f"/repos/{owner}/{repo}/collaborators/{username}")
        return {"username": username, "removed": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_organization_repos(
        self,
        org: str,
        *,
        type: str = "all",
        per_page: int = 10,
        page: int = 1,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List repositories in an organization.

        Returns compact ``repo_ref`` summaries. Use ``full_name`` as
        input to other tools. ``include_metadata=False`` returns the raw
        provider list.
        """
        if not org:
            raise ValueError("org must be a non-empty string")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        raw: _JsonResponse = self._client.get(
            f"/orgs/{org}/repos",
            params={"type": type, "per_page": per_page, "page": page},
        ).json()
        if not include_metadata or not isinstance(raw, list):
            return raw
        summaries = [
            self._repo_summary(self._as_dict(item), index=index, include_ids=include_ids)
            for index, item in enumerate(raw, start=1)
            if isinstance(item, dict)
        ]
        return {"repositories": summaries, "count": len(summaries), "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_organization_members(
        self,
        org: str,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List members of an organization.

        Returns raw user resources — ``login`` is the stable identifier.
        """
        if not org:
            raise ValueError("org must be a non-empty string")
        return self._client.get(
            f"/orgs/{org}/members",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_teams(
        self,
        org: str,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List teams in an organization.

        Returns raw team resources — ``slug`` is the stable identifier.
        """
        if not org:
            raise ValueError("org must be a non-empty string")
        return self._client.get(
            f"/orgs/{org}/teams",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_forks(
        self,
        owner: str,
        repo: str,
        *,
        sort: str = "newest",
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List forks of a repository.

        Returns raw repository resources for each fork.
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/forks",
            params={"sort": sort, "per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def fork_repository(
        self,
        owner: str,
        repo: str,
        *,
        organization: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Fork a repository into the authenticated user's account (or org).

        Returns the new fork's repository resource.
        """
        payload: dict[str, Any] = {}
        if organization is not None:
            payload["organization"] = organization
        if name is not None:
            payload["name"] = name
        return self._client.post(
            f"/repos/{owner}/{repo}/forks",
            json=payload or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_stargazers(
        self,
        owner: str,
        repo: str,
        *,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List users who starred a repository.

        Returns raw user resources — ``login`` is the stable identifier.
        """
        return self._client.get(
            f"/repos/{owner}/{repo}/stargazers",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_rate_limit(self) -> dict[str, Any]:
        """Return GitHub API rate-limit counters for the current token."""
        return self._client.get("/rate_limit").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, username: str) -> dict[str, Any]:
        """Return public profile for a user by login.

        Returns the raw user resource.
        """
        if not username:
            raise ValueError("username must be a non-empty string")
        return self._client.get(f"/users/{username}").json()

    # MARK: - Internal helpers

    def _resolve_owner_repo_issue(
        self,
        owner: Any,
        repo: Any,
        issue_number: Any,
    ) -> tuple[str, str, int]:
        """Resolve ``(owner, repo, issue_number)`` from tolerant inputs.

        Supports:
        - ``("octocat", "Hello", 42)``
        - ``("octocat/Hello", 42)``  (repo is the number)
        - ``(repo_dict, 42)``  (repo is the number)
        - ``(issue_dict,)``  (owner is the issue dict)
        """
        # issue dict alone
        if (
            isinstance(owner, dict)
            and repo is None
            and issue_number is None
            and ("number" in owner or "issue_number" in owner)
        ):
            number = self._resolve_issue_number(owner)
            owner_name, repo_name = self._resolve_repo(owner)
            return owner_name, repo_name, number
        # owner=str-with-slash, repo=int
        if (
            isinstance(owner, str)
            and "/" in owner
            and isinstance(repo, int)
            and issue_number is None
        ):
            owner_name, repo_name = self._resolve_repo(owner)
            return owner_name, repo_name, repo
        # owner=dict (repo), repo=int
        if isinstance(owner, dict) and isinstance(repo, int) and issue_number is None:
            owner_name, repo_name = self._resolve_repo(owner)
            return owner_name, repo_name, repo
        # standard (owner, repo, number)
        if isinstance(owner, str) and isinstance(repo, str) and isinstance(issue_number, int):
            return owner, repo, issue_number
        raise ValueError(
            "provide (owner, repo, issue_number), (full_name, number), or an issue dict"
        )

    @staticmethod
    def _resolve_repo_from_full_name(full_name: str) -> tuple[str, str]:
        if "/" not in full_name:
            raise ValueError("full_name must be 'owner/repo'")
        owner, repo = full_name.split("/", 1)
        return owner, repo
