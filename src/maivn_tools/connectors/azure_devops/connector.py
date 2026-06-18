"""Azure DevOps Services REST API connector.

The connector authenticates with a personal access token (sent as basic
auth with an empty username) and exposes the most useful project, repo,
pull request, work item, and pipeline endpoints.

Agent-ready behavior:

* Broad list tools default to small ``top`` (10) and return compact,
  human-readable summaries with stable refs (``project_ref``,
  ``repo_ref``, ``pr_ref``, ``branch_ref``, ``pipeline_ref``,
  ``build_ref``).
* User-facing identifiers like ``pull_request_id``, ``work_item_id``,
  ``build_id``, ``pipeline_id`` are always shown — they are the stable
  refs used by every other tool.
* Opaque ADO GUIDs (project ``id``, repository ``id``, ``url``) are
  hidden by default; set ``include_ids=True`` only when a follow-up tool
  needs them.
* Write tools that take ``(project, repository)`` accept either two
  strings, or a project dict and repository dict from list/get.
* ``complete_pull_request`` accepts a PR dict directly so an agent can
  pipe directly from ``list_pull_requests``.
"""

# pyright: strict

from __future__ import annotations

from base64 import b64encode
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpResponse, HttpTransport
from .output_schemas import (
    LIST_BRANCHES_OUTPUT,
    LIST_BUILDS_OUTPUT,
    LIST_PIPELINES_OUTPUT,
    LIST_PROJECTS_OUTPUT,
    LIST_PULL_REQUESTS_OUTPUT,
    LIST_REPOSITORIES_OUTPUT,
)

_API_VERSION = "7.1"
_SHA_DISPLAY_LEN = 7
# Azure DevOps returns the forward-paging cursor on this response header and
# accepts it back as a ``continuationToken`` query parameter.
_CONTINUATION_HEADER = "x-ms-continuationtoken"


class _PATAuth(AuthStrategy):
    """Azure DevOps personal-access-token auth (basic with empty username)."""

    mode = AuthMode.BASIC

    def __init__(self, pat: str) -> None:
        if not pat:
            raise ValueError("pat must be a non-empty string")
        self._pat = pat

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        encoded = b64encode(f":{self._pat}".encode()).decode("ascii")
        headers = dict(request.get("headers") or {})
        headers["Authorization"] = f"Basic {encoded}"
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "scheme": "pat"}


@toolset(prefix="ado")
class AzureDevOpsToolSet:
    """A connector for Azure DevOps Services REST API.

    Args:
        organization: ADO organization name (the ``X`` in ``dev.azure.com/X``).
        pat: Personal access token; sent as basic auth with an empty username.
        api_version: REST API version (default ``7.1``).
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="azure_devops",
        display_name="Azure DevOps",
        version="0.1.0",
        description="Manage Azure DevOps repos, pipelines, work items, and artifacts.",
        auth_modes=(AuthMode.BASIC, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "vso.work": "Read work items.",
            "vso.work_write": "Write work items.",
            "vso.code": "Read repos.",
            "vso.code_write": "Write to repos.",
            "vso.build": "Read build/pipeline data.",
            "vso.build_execute": "Run pipelines.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://learn.microsoft.com/en-us/rest/api/azure/devops/",
        homepage_url="https://azure.microsoft.com/en-us/products/devops",
        tags=("microsoft", "source-control", "ci-cd"),
    )

    def __init__(
        self,
        *,
        organization: str,
        pat: str,
        api_version: str = _API_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not organization:
            raise ValueError("organization is required")
        if not pat:
            raise ValueError("pat is required")
        self.connection = connection
        self._api_version = api_version
        self._organization = organization
        self._client = HttpClient(
            base_url=f"https://dev.azure.com/{organization}",
            auth=_PATAuth(pat),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _params(self, **kwargs: Any) -> dict[str, Any]:
        merged: dict[str, Any] = {"api-version": self._api_version}
        for key, value in kwargs.items():
            if value is not None:
                merged[key] = value
        return merged

    @staticmethod
    def _with_continuation(
        envelope: dict[str, Any],
        response: HttpResponse,
    ) -> dict[str, Any]:
        """Surface Azure DevOps's forward-paging cursor on the summary envelope.

        Reads the ``x-ms-continuationtoken`` response header (the only
        forward-paging mechanism for endpoints that do not accept ``$skip``)
        and, when present, exposes it as ``continuation_token`` so callers can
        pass it back to fetch the next page.
        """
        token = response.header(_CONTINUATION_HEADER)
        if token:
            envelope["continuation_token"] = token
        return envelope

    # MARK: - Tolerant input helpers

    @staticmethod
    def _resolve_project(project: Any) -> str:
        """Accept a project name string or a project dict."""
        if isinstance(project, str) and project:
            return project
        if isinstance(project, dict):
            project_dict = cast("dict[str, Any]", project)
            name = project_dict.get("name") or project_dict.get("id")
            if isinstance(name, str) and name:
                return name
        raise ValueError("project must be a non-empty string or project dict")

    @staticmethod
    def _resolve_repository(repository: Any) -> str:
        """Accept a repository name string or a repository dict."""
        if isinstance(repository, str) and repository:
            return repository
        if isinstance(repository, dict):
            repository_dict = cast("dict[str, Any]", repository)
            name = repository_dict.get("name") or repository_dict.get("id")
            if isinstance(name, str) and name:
                return name
        raise ValueError("repository must be a non-empty string or repository dict")

    # MARK: - Summary helpers

    @staticmethod
    def _short_sha(sha: Any) -> str:
        if isinstance(sha, str) and sha:
            return sha[:_SHA_DISPLAY_LEN]
        return ""

    @staticmethod
    def _user_display(user: Any) -> str:
        if isinstance(user, dict):
            user_dict = cast("dict[str, Any]", user)
            for key in ("displayName", "uniqueName", "id"):
                value = user_dict.get(key)
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
            "name": project.get("name", ""),
            "description": project.get("description", "") or "",
            "state": project.get("state", ""),
            "visibility": project.get("visibility", ""),
            "last_updated": project.get("lastUpdateTime", ""),
        }
        if include_ids:
            summary["project_id"] = project.get("id")
            summary["url"] = project.get("url", "")
        return summary

    @classmethod
    def _repo_summary(
        cls,
        repo: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        project: Any = repo.get("project") or {}
        project_dict = cast("dict[str, Any]", project) if isinstance(project, dict) else None
        summary: dict[str, Any] = {
            "repo_ref": f"repo_{index}",
            "name": repo.get("name", ""),
            "project": project_dict.get("name", "") if project_dict is not None else "",
            "default_branch": (repo.get("defaultBranch") or "").replace("refs/heads/", ""),
            "size": repo.get("size", 0),
            "is_disabled": repo.get("isDisabled", False),
            "web_url": repo.get("webUrl") or repo.get("remoteUrl") or "",
        }
        if include_ids:
            summary["repo_id"] = repo.get("id")
            summary["project_id"] = project_dict.get("id") if project_dict is not None else None
        return summary

    @classmethod
    def _pr_summary(
        cls,
        pr: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        repo: Any = pr.get("repository") or {}
        repo_dict = cast("dict[str, Any]", repo) if isinstance(repo, dict) else None
        repo_name = repo_dict.get("name", "") if repo_dict is not None else ""
        summary: dict[str, Any] = {
            "pr_ref": f"pr_{index}",
            "pull_request_id": pr.get("pullRequestId"),
            "title": pr.get("title", ""),
            "status": pr.get("status", ""),
            "is_draft": pr.get("isDraft", False),
            "author": cls._user_display(pr.get("createdBy")),
            "source_ref": pr.get("sourceRefName", ""),
            "target_ref": pr.get("targetRefName", ""),
            "merge_status": pr.get("mergeStatus", ""),
            "repository": repo_name,
            "creation_date": pr.get("creationDate", ""),
        }
        if include_ids:
            if repo_dict is not None:
                summary["repo_id"] = repo_dict.get("id")
            summary["code_review_id"] = pr.get("codeReviewId")
        return summary

    @classmethod
    def _branch_summary(
        cls,
        ref: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        name: Any = ref.get("name", "")
        if isinstance(name, str) and name.startswith("refs/heads/"):
            name = name[len("refs/heads/") :]
        sha: Any = ref.get("objectId", "")
        summary: dict[str, Any] = {
            "branch_ref": f"branch_{index}",
            "name": name,
            "short_sha": cls._short_sha(sha),
            "creator": cls._user_display(ref.get("creator")),
        }
        if include_ids:
            summary["sha"] = sha
        return summary

    @classmethod
    def _pipeline_summary(
        cls,
        pipeline: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        links: Any = pipeline.get("_links")
        web_url: Any = (
            cast("dict[str, Any]", links).get("web", {}).get("href", "")
            if isinstance(links, dict)
            else ""
        )
        summary: dict[str, Any] = {
            "pipeline_ref": f"pipeline_{index}",
            "pipeline_id": pipeline.get("id"),
            "name": pipeline.get("name", ""),
            "folder": pipeline.get("folder", ""),
            "revision": pipeline.get("revision"),
            "web_url": web_url,
        }
        if include_ids:
            summary["url"] = pipeline.get("url", "")
        return summary

    @classmethod
    def _build_summary(
        cls,
        build: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        definition: Any = build.get("definition") or {}
        definition_dict = (
            cast("dict[str, Any]", definition) if isinstance(definition, dict) else None
        )
        summary: dict[str, Any] = {
            "build_ref": f"build_{index}",
            "build_id": build.get("id"),
            "build_number": build.get("buildNumber", ""),
            "status": build.get("status", ""),
            "result": build.get("result"),
            "source_branch": (build.get("sourceBranch") or "").replace("refs/heads/", ""),
            "short_sha": cls._short_sha(build.get("sourceVersion")),
            "definition": definition_dict.get("name", "") if definition_dict is not None else "",
            "queue_time": build.get("queueTime", ""),
            "start_time": build.get("startTime", ""),
            "finish_time": build.get("finishTime", ""),
            "requested_by": cls._user_display(build.get("requestedBy")),
        }
        if include_ids:
            if definition_dict is not None:
                summary["definition_id"] = definition_dict.get("id")
            summary["url"] = build.get("url", "")
        return summary

    # MARK: - Projects

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PROJECTS_OUTPUT)
    def list_projects(
        self,
        *,
        state: str | None = None,
        top: int | None = 10,
        skip: int | None = None,
        continuation_token: str | None = None,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List projects in the organization.

        Best first tool when the user asks "what projects exist?".
        Returns compact summaries: ``project_ref``, ``name`` (the
        stable identifier used by every other tool), ``description``,
        ``state``, ``visibility``, ``last_updated``.

        Pass ``continuation_token`` (echoed back as ``continuation_token``
        in the metadata envelope) to fetch the next page. Set
        ``include_metadata=False`` for the raw envelope. Set
        ``include_ids=True`` to expose the opaque project ``id`` GUID
        (internal handle).
        """
        response = self._client.get(
            "/_apis/projects",
            params=self._params(
                stateFilter=state,
                continuationToken=continuation_token,
                **{"$top": top, "$skip": skip},
            ),
        )
        raw: Any = response.json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        envelope = cast("dict[str, Any]", raw)
        values: list[Any] = envelope.get("value", [])
        summaries = [
            self._project_summary(
                cast("dict[str, Any]", item), index=index, include_ids=include_ids
            )
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return self._with_continuation(
            {
                "projects": summaries,
                "count": envelope.get("count", len(summaries)),
            },
            response,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(self, project: str | dict[str, Any]) -> dict[str, Any]:
        """Return one project.

        ``project`` may be the name string or a project dict from
        :meth:`list_projects`. Returns the raw project resource.
        """
        name = self._resolve_project(project)
        return self._client.get(
            f"/_apis/projects/{name}",
            params=self._params(),
        ).json()

    # MARK: - Repositories & pull requests

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_REPOSITORIES_OUTPUT)
    def list_repositories(
        self,
        project: str | dict[str, Any],
        *,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List Git repositories in a project.

        Returns compact summaries: ``repo_ref``, ``name`` (the stable
        identifier passed to other tools), ``project``, ``default_branch``,
        ``size``, ``is_disabled``, ``web_url``.

        Set ``include_metadata=False`` for the raw envelope. Set
        ``include_ids=True`` to expose the opaque repo ``id`` GUID
        (needed only by a few raw ADO endpoints).
        """
        name = self._resolve_project(project)
        response = self._client.get(
            f"/{name}/_apis/git/repositories",
            params=self._params(),
        )
        raw: Any = response.json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        envelope = cast("dict[str, Any]", raw)
        values: list[Any] = envelope.get("value", [])
        summaries = [
            self._repo_summary(cast("dict[str, Any]", item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return self._with_continuation(
            {
                "repositories": summaries,
                "count": envelope.get("count", len(summaries)),
            },
            response,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_repository(
        self,
        project: str | dict[str, Any],
        repository: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Return one repository.

        Returns the raw repository resource.
        """
        proj = self._resolve_project(project)
        repo = self._resolve_repository(repository)
        return self._client.get(
            f"/{proj}/_apis/git/repositories/{repo}",
            params=self._params(),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PULL_REQUESTS_OUTPUT)
    def list_pull_requests(
        self,
        project: str | dict[str, Any],
        repository: str | dict[str, Any],
        *,
        status: str | None = None,
        top: int | None = 10,
        skip: int | None = None,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List pull requests on a repo.

        Best first tool for PR triage. Returns compact summaries:
        ``pr_ref``, ``pull_request_id`` (the stable PR number),
        ``title``, ``status``, ``is_draft``, ``author``, ``source_ref``,
        ``target_ref``, ``merge_status``, ``repository``,
        ``creation_date``.

        ``status`` must be one of ``abandoned``, ``active``, ``all``,
        ``completed``, ``notSet``. Pass ``skip`` to page past the first
        ``top`` results. Set ``include_metadata=False`` for the raw
        envelope.
        """
        proj = self._resolve_project(project)
        repo = self._resolve_repository(repository)
        params = self._params(**{"$top": top, "$skip": skip})
        if status is not None:
            if status not in {"abandoned", "active", "all", "completed", "notSet"}:
                raise ValueError("invalid status")
            params["searchCriteria.status"] = status
        response = self._client.get(
            f"/{proj}/_apis/git/repositories/{repo}/pullrequests",
            params=params,
        )
        raw: Any = response.json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        envelope = cast("dict[str, Any]", raw)
        values: list[Any] = envelope.get("value", [])
        summaries = [
            self._pr_summary(cast("dict[str, Any]", item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return self._with_continuation(
            {
                "pull_requests": summaries,
                "count": envelope.get("count", len(summaries)),
            },
            response,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_pull_request(
        self,
        project: str | dict[str, Any],
        repository: str | dict[str, Any],
        *,
        source_ref: str,
        target_ref: str,
        title: str,
        description: str | None = None,
        reviewers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Open a pull request.

        ``source_ref`` / ``target_ref`` should be fully-qualified refs
        (``refs/heads/feature``). ``reviewers`` is a list of user IDs
        (the opaque ADO identifier). Returns the new PR resource —
        ``pullRequestId`` is the user-facing identifier.
        """
        proj = self._resolve_project(project)
        repo = self._resolve_repository(repository)
        if not title:
            raise ValueError("project, repository, and title are required")
        payload: dict[str, Any] = {
            "sourceRefName": source_ref,
            "targetRefName": target_ref,
            "title": title,
        }
        if description is not None:
            payload["description"] = description
        if reviewers is not None:
            payload["reviewers"] = [{"id": r} for r in reviewers]
        return self._client.post(
            f"/{proj}/_apis/git/repositories/{repo}/pullrequests",
            params=self._params(),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def complete_pull_request(
        self,
        project: Any,
        repository: Any = None,
        pull_request_id: Any = None,
        *,
        last_merge_source_commit: str | None = None,
        squash_merge: bool = False,
        delete_source_branch: bool = False,
    ) -> dict[str, Any]:
        """Complete (merge) a pull request. Destructive in effect — confirm.

        Tolerant inputs:
        - ``complete_pull_request("MyProj", "myrepo", 1, last_merge_source_commit="abc")``
        - ``complete_pull_request(pr_dict, last_merge_source_commit="abc")``
          — pulls project, repository, and ``pullRequestId`` from the PR.
          Also pulls ``lastMergeSourceCommit.commitId`` if
          ``last_merge_source_commit`` is omitted.
        """
        proj, repo, pid, derived_commit = self._resolve_project_repo_pr(
            project, repository, pull_request_id
        )
        commit = last_merge_source_commit or derived_commit
        if not commit:
            raise ValueError("last_merge_source_commit is required")
        payload = {
            "status": "completed",
            "lastMergeSourceCommit": {"commitId": commit},
            "completionOptions": {
                "squashMerge": squash_merge,
                "deleteSourceBranch": delete_source_branch,
            },
        }
        return self._client.patch(
            f"/{proj}/_apis/git/repositories/{repo}/pullrequests/{pid}",
            params=self._params(),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_BRANCHES_OUTPUT)
    def list_branches(
        self,
        project: str | dict[str, Any],
        repository: str | dict[str, Any],
        *,
        continuation_token: str | None = None,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List refs (branches) of a repo.

        Returns compact summaries: ``branch_ref``, ``name`` (without the
        ``refs/heads/`` prefix), ``short_sha``, ``creator``. Pass
        ``continuation_token`` (echoed back as ``continuation_token`` in the
        metadata envelope) to fetch the next page. Set
        ``include_metadata=False`` for the raw envelope.
        """
        proj = self._resolve_project(project)
        repo = self._resolve_repository(repository)
        response = self._client.get(
            f"/{proj}/_apis/git/repositories/{repo}/refs",
            params=self._params(
                filter="heads/",
                continuationToken=continuation_token,
            ),
        )
        raw: Any = response.json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        envelope = cast("dict[str, Any]", raw)
        values: list[Any] = envelope.get("value", [])
        summaries = [
            self._branch_summary(cast("dict[str, Any]", item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return self._with_continuation(
            {
                "branches": summaries,
                "count": envelope.get("count", len(summaries)),
            },
            response,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file(
        self,
        project: str | dict[str, Any],
        repository: str | dict[str, Any],
        *,
        path: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Read a file from a repository.

        ``version`` is a branch name, tag, or commit. Returns the raw
        ADO item resource — ``content`` carries the file body.
        """
        proj = self._resolve_project(project)
        repo = self._resolve_repository(repository)
        if not path:
            raise ValueError("path must be a non-empty string")
        params = self._params(path=path, includeContent="true")
        if version is not None:
            params["versionDescriptor.version"] = version
        return self._client.get(
            f"/{proj}/_apis/git/repositories/{repo}/items",
            params=params,
        ).json()

    # MARK: - Work items

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_work_item(self, work_item_id: int, *, expand: str | None = None) -> dict[str, Any]:
        """Return one work item by ID.

        ``work_item_id`` is the user-facing work item number from
        :meth:`wiql_query` results.
        """
        params = self._params()
        if expand is not None:
            params["$expand"] = expand
        return self._client.get(
            f"/_apis/wit/workitems/{work_item_id}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def wiql_query(self, project: str | dict[str, Any], *, query: str) -> dict[str, Any]:
        """Run a WIQL query.

        Returns the raw WIQL response — ``workItems[*].id`` are the
        stable user-facing work item numbers you can pass to
        :meth:`get_work_item` and :meth:`update_work_item`.
        """
        proj = self._resolve_project(project)
        if not query:
            raise ValueError("project and query must be non-empty")
        return self._client.post(
            f"/{proj}/_apis/wit/wiql",
            params=self._params(),
            json={"query": query},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_work_item(
        self,
        project: str | dict[str, Any],
        *,
        type: str,
        title: str,
        description: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a work item using JSON Patch.

        ``type`` is the work item type (``Bug``, ``Task``, ``User Story``).
        Returns the new work item resource — ``id`` is the user-facing
        identifier.
        """
        proj = self._resolve_project(project)
        if not type or not title:
            raise ValueError("project, type, and title are required")
        ops: list[dict[str, Any]] = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
        ]
        if description is not None:
            ops.append({"op": "add", "path": "/fields/System.Description", "value": description})
        if extra_fields:
            for field, value in extra_fields.items():
                ops.append({"op": "add", "path": f"/fields/{field}", "value": value})
        from json import dumps as _dumps

        return self._client.post(
            f"/{proj}/_apis/wit/workitems/${type}",
            params=self._params(),
            data=_dumps(ops).encode("utf-8"),
            headers={"Content-Type": "application/json-patch+json"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_work_item(
        self,
        work_item_id: int,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a work item.

        ``fields`` is a mapping of ``System.*`` (or custom) field paths
        to new values. Returns the updated work item resource.
        """
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        ops = [
            {"op": "add", "path": f"/fields/{key}", "value": value} for key, value in fields.items()
        ]
        from json import dumps as _dumps

        return self._client.patch(
            f"/_apis/wit/workitems/{work_item_id}",
            params=self._params(),
            data=_dumps(ops).encode("utf-8"),
            headers={"Content-Type": "application/json-patch+json"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_work_item(self, work_item_id: int, *, destroy: bool = False) -> dict[str, Any]:
        """Move a work item to the recycle bin (or destroy permanently).

        Destructive — confirm with the user. ``destroy=True`` permanently
        deletes (irrecoverable).
        """
        params = self._params(destroy="true" if destroy else None)
        self._client.delete(
            f"/_apis/wit/workitems/{work_item_id}",
            params=params,
        )
        return {"id": work_item_id, "deleted": True, "destroyed": destroy}

    # MARK: - Pipelines and builds

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PIPELINES_OUTPUT)
    def list_pipelines(
        self,
        project: str | dict[str, Any],
        *,
        continuation_token: str | None = None,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List pipelines.

        Returns compact summaries: ``pipeline_ref``, ``pipeline_id``
        (the stable numeric ID passed to :meth:`run_pipeline`), ``name``,
        ``folder``, ``revision``, ``web_url``. Pass ``continuation_token``
        (echoed back as ``continuation_token`` in the metadata envelope) to
        fetch the next page. Set ``include_metadata=False`` for the raw
        envelope.
        """
        proj = self._resolve_project(project)
        response = self._client.get(
            f"/{proj}/_apis/pipelines",
            params=self._params(continuationToken=continuation_token),
        )
        raw: Any = response.json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        envelope = cast("dict[str, Any]", raw)
        values: list[Any] = envelope.get("value", [])
        summaries = [
            self._pipeline_summary(
                cast("dict[str, Any]", item), index=index, include_ids=include_ids
            )
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return self._with_continuation(
            {
                "pipelines": summaries,
                "count": envelope.get("count", len(summaries)),
            },
            response,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def run_pipeline(
        self,
        project: str | dict[str, Any],
        pipeline_id: int,
        *,
        branch: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a pipeline run.

        ``pipeline_id`` is the numeric ID from :meth:`list_pipelines`.
        ``branch`` is a fully-qualified branch ref (``refs/heads/main``)
        or short branch name. Returns the new run resource.
        """
        proj = self._resolve_project(project)
        payload: dict[str, Any] = {}
        if branch is not None:
            payload["resources"] = {"repositories": {"self": {"refName": branch}}}
        if variables is not None:
            payload["variables"] = {
                k: {"value": v, "isSecret": False} for k, v in variables.items()
            }
        return self._client.post(
            f"/{proj}/_apis/pipelines/{pipeline_id}/runs",
            params=self._params(),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_BUILDS_OUTPUT)
    def list_builds(
        self,
        project: str | dict[str, Any],
        *,
        definitions: list[int] | None = None,
        top: int | None = 10,
        continuation_token: str | None = None,
        include_ids: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List builds.

        Returns compact summaries: ``build_ref``, ``build_id`` (the
        stable build identifier), ``build_number``, ``status``,
        ``result``, ``source_branch``, ``short_sha``, ``definition``,
        ``queue_time``, ``start_time``, ``finish_time``, ``requested_by``.

        Pass ``continuation_token`` (echoed back as ``continuation_token``
        in the metadata envelope) to fetch the next page. Set
        ``include_metadata=False`` for the raw envelope.
        """
        proj = self._resolve_project(project)
        params = self._params(**{"$top": top}, continuationToken=continuation_token)
        if definitions is not None:
            params["definitions"] = ",".join(str(d) for d in definitions)
        response = self._client.get(
            f"/{proj}/_apis/build/builds",
            params=params,
        )
        raw: Any = response.json()
        if not include_metadata or not isinstance(raw, dict):
            return cast("dict[str, Any]", raw)
        envelope = cast("dict[str, Any]", raw)
        values: list[Any] = envelope.get("value", [])
        summaries = [
            self._build_summary(cast("dict[str, Any]", item), index=index, include_ids=include_ids)
            for index, item in enumerate(values, start=1)
            if isinstance(item, dict)
        ]
        return self._with_continuation(
            {
                "builds": summaries,
                "count": envelope.get("count", len(summaries)),
            },
            response,
        )

    # MARK: - Internal helpers

    def _resolve_project_repo_pr(
        self,
        project: Any,
        repository: Any,
        pull_request_id: Any,
    ) -> tuple[str, str, int, str | None]:
        """Resolve ``(project, repository, pull_request_id, derived_commit)``.

        Also returns ``lastMergeSourceCommit.commitId`` if it can be
        derived from a PR dict input.
        """
        # PR dict alone
        if (
            isinstance(project, dict)
            and repository is None
            and pull_request_id is None
            and ("pullRequestId" in project or "id" in project)
        ):
            project_dict = cast("dict[str, Any]", project)
            pid_value = project_dict.get("pullRequestId") or project_dict.get("id")
            if not isinstance(pid_value, int):
                raise ValueError("pull request dict must expose pullRequestId or id")
            pid = pid_value
            repo_obj: Any = project_dict.get("repository") or {}
            if not isinstance(repo_obj, dict):
                raise ValueError("pull request dict must expose repository")
            repo_obj_dict = cast("dict[str, Any]", repo_obj)
            proj_obj: Any = repo_obj_dict.get("project") or {}
            proj_name = (
                cast("dict[str, Any]", proj_obj).get("name") if isinstance(proj_obj, dict) else None
            )
            repo_name = repo_obj_dict.get("name")
            if not isinstance(proj_name, str) or not isinstance(repo_name, str):
                raise ValueError(
                    "pull request dict must expose repository.name and repository.project.name"
                )
            commit_obj: Any = project_dict.get("lastMergeSourceCommit") or {}
            derived_commit = (
                cast("dict[str, Any]", commit_obj).get("commitId")
                if isinstance(commit_obj, dict)
                else None
            )
            return proj_name, repo_name, pid, cast("str | None", derived_commit)
        # Standard form
        if pull_request_id is not None:
            proj = self._resolve_project(project)
            repo = self._resolve_repository(repository)
            if not isinstance(pull_request_id, int):
                raise ValueError("pull_request_id must be an int")
            return proj, repo, pull_request_id, None
        raise ValueError("provide (project, repository, pull_request_id) or a PR dict")
