"""Snyk REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_ISSUES_OUTPUT,
    LIST_ORGANIZATIONS_OUTPUT,
    LIST_PROJECTS_OUTPUT,
)

# Currently recommended GA REST API date version (see docs.snyk.io REST API docs).
_API_VERSION = "2024-10-15"


@toolset(prefix="snyk")
class SnykToolSet:
    """A connector for the Snyk REST + v1 API.

    Args:
        api_token: Snyk API token.
        version: REST API ``version`` query parameter (default ``"2024-10-15"``).
    """

    metadata = ProviderMetadata(
        name="snyk",
        display_name="Snyk",
        version="0.1.0",
        description="Organizations, projects, issues, dependencies, and scans.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.snyk.io/snyk-api",
        homepage_url="https://snyk.io/",
        tags=("security", "sca", "vulnerabilities"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        version: str = _API_VERSION,
        base_url: str = "https://api.snyk.io",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("api_token is required")
        self.connection = connection
        self._rest_version = version
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_token, header="Authorization", prefix="token"),
            transport=transport,
            default_headers={
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Summary helpers

    @staticmethod
    def _as_mapping(value: object) -> dict[str, Any]:
        return cast("dict[str, Any]", value) if isinstance(value, dict) else {}

    @classmethod
    def _attrs(cls, entry: dict[str, Any]) -> dict[str, Any]:
        return cls._as_mapping(entry.get("attributes"))

    @classmethod
    def _org_summary(
        cls,
        org: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = cls._attrs(org)
        summary: dict[str, Any] = {
            "org_ref": f"org_{index}",
            "name": attrs.get("name", ""),
            "slug": attrs.get("slug", ""),
        }
        if include_ids:
            summary["org_id"] = org.get("id", "")
        return summary

    @classmethod
    def _project_summary(
        cls,
        project: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = cls._attrs(project)
        summary: dict[str, Any] = {
            "project_ref": f"project_{index}",
            "name": attrs.get("name", ""),
            "origin": attrs.get("origin", ""),
            "type": attrs.get("type", ""),
            "target_reference": attrs.get("target_reference", ""),
            "status": attrs.get("status", ""),
        }
        if include_ids:
            summary["project_id"] = project.get("id", "")
        return summary

    @classmethod
    def _issue_summary(
        cls,
        issue: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = cls._attrs(issue)
        summary: dict[str, Any] = {
            "vuln_ref": f"vuln_{index}",
            "title": attrs.get("title", ""),
            "severity": attrs.get("effective_severity_level", "") or attrs.get("severity", ""),
            "type": attrs.get("type", ""),
            "status": attrs.get("status", ""),
            "ignored": bool(attrs.get("ignored", False)),
            "created_at": attrs.get("created_at", ""),
        }
        if include_ids:
            summary["vuln_id"] = issue.get("id", "")
            summary["key"] = attrs.get("key", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORGANIZATIONS_OUTPUT)
    def list_organizations(
        self,
        *,
        limit: int = 25,
        starting_after: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Snyk organizations the token can see.

        Returns ``{"organizations": [...]}`` with ``org_ref``, ``name``,
        ``slug``. Raw ``org_id`` is omitted by default — set
        ``include_ids=True`` when a follow-up tool needs it.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {
            "version": self._rest_version,
            "limit": limit,
        }
        if starting_after is not None:
            params["starting_after"] = starting_after
        payload: object = self._client.get("/rest/orgs", params=params).json()
        mapping = self._as_mapping(payload)
        raw_orgs: list[dict[str, Any]] = []
        data_field: object = mapping.get("data", [])
        if isinstance(data_field, list):
            items = cast("list[object]", data_field)
            raw_orgs = [cast("dict[str, Any]", o) for o in items if isinstance(o, dict)]
        summaries = [
            self._org_summary(org, index=index, include_ids=include_ids)
            for index, org in enumerate(raw_orgs, start=1)
        ]
        result: dict[str, Any] = {"organizations": summaries}
        if "links" in mapping:
            result["links"] = mapping["links"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PROJECTS_OUTPUT)
    def list_projects(
        self,
        *,
        org_id: str,
        limit: int = 25,
        starting_after: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List projects in an organization.

        Returns ``{"projects": [...]}`` with ``project_ref``, ``name``,
        ``origin``, ``type``, ``target_reference``, ``status``. Raw
        ``project_id`` is omitted by default.
        """
        if not org_id:
            raise ValueError("org_id is required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {
            "version": self._rest_version,
            "limit": limit,
        }
        if starting_after is not None:
            params["starting_after"] = starting_after
        payload: object = self._client.get(f"/rest/orgs/{org_id}/projects", params=params).json()
        mapping = self._as_mapping(payload)
        raw_projects: list[dict[str, Any]] = []
        data_field: object = mapping.get("data", [])
        if isinstance(data_field, list):
            items = cast("list[object]", data_field)
            raw_projects = [cast("dict[str, Any]", p) for p in items if isinstance(p, dict)]
        summaries = [
            self._project_summary(project, index=index, include_ids=include_ids)
            for index, project in enumerate(raw_projects, start=1)
        ]
        result: dict[str, Any] = {"projects": summaries}
        if "links" in mapping:
            result["links"] = mapping["links"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(
        self,
        *,
        org_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Return one Snyk project.

        Returns the raw project resource (``id``, ``attributes`` block).
        """
        if not org_id or not project_id:
            raise ValueError("org_id and project_id are required")
        result: dict[str, Any] = self._client.get(
            f"/rest/orgs/{org_id}/projects/{project_id}",
            params={"version": self._rest_version},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ISSUES_OUTPUT)
    def list_issues(
        self,
        *,
        org_id: str,
        project_id: str,
        limit: int = 25,
        starting_after: str | None = None,
        status: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List vulnerability issues for a project.

        Best first tool for triaging vulns on a project. Returns
        ``{"vulns": [...]}`` with ``vuln_ref``, ``title``, ``severity``,
        ``type``, ``status``, ``ignored``, ``created_at``. Raw
        ``vuln_id``/``key`` are omitted by default — set
        ``include_ids=True`` when you need them for downstream actions.
        """
        if not org_id or not project_id:
            raise ValueError("org_id and project_id are required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        # Snyk exposes no project-scoped issues path; issues are listed at the
        # org level and filtered to a project via scan_item.id/scan_item.type.
        params: dict[str, Any] = {
            "version": self._rest_version,
            "limit": limit,
            "scan_item.id": project_id,
            "scan_item.type": "project",
        }
        if starting_after is not None:
            params["starting_after"] = starting_after
        if status is not None:
            params["status"] = ",".join(status)
        payload: object = self._client.get(
            f"/rest/orgs/{org_id}/issues",
            params=params,
        ).json()
        mapping = self._as_mapping(payload)
        raw_issues: list[dict[str, Any]] = []
        data_field: object = mapping.get("data", [])
        if isinstance(data_field, list):
            items = cast("list[object]", data_field)
            raw_issues = [cast("dict[str, Any]", i) for i in items if isinstance(i, dict)]
        summaries = [
            self._issue_summary(issue, index=index, include_ids=include_ids)
            for index, issue in enumerate(raw_issues, start=1)
        ]
        result: dict[str, Any] = {"vulns": summaries}
        if "links" in mapping:
            result["links"] = mapping["links"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_aggregated_issues(
        self,
        *,
        org_id: str,
        project_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List aggregated issues for a project (legacy v1 endpoint).

        DEPRECATED: the v1 aggregated-issues endpoint is on Snyk's v1 EOL
        deprecation cadence; Snyk's migration guide directs callers to the
        REST Issues API instead. Prefer ``list_issues`` for new code. This
        helper is retained only for legacy callers until sunset.

        Returns the raw v1 aggregated-issues payload — issues grouped by
        package/vuln id. Useful when triaging dependency vulns.
        """
        if not org_id or not project_id:
            raise ValueError("org_id and project_id are required")
        result: dict[str, Any] = self._client.post(
            f"/v1/org/{org_id}/project/{project_id}/aggregated-issues",
            json={"filters": filters or {}},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_test(
        self,
        *,
        org_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Trigger a Snyk re-test of a project.

        Returns the v1 test response. Use after dependency updates to
        confirm vulns are resolved.
        """
        if not org_id or not project_id:
            raise ValueError("org_id and project_id are required")
        result: dict[str, Any] = self._client.post(
            f"/v1/org/{org_id}/project/{project_id}/test"
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def deactivate_project(
        self,
        *,
        org_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Deactivate a project (stops monitoring; reversible via Snyk UI).

        Destructive — the project stops receiving new scans. Confirm
        with the user before calling.
        """
        if not org_id or not project_id:
            raise ValueError("org_id and project_id are required")
        result: dict[str, Any] = self._client.post(
            f"/v1/org/{org_id}/project/{project_id}/deactivate"
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_dependencies(
        self,
        *,
        org_id: str,
        project_id: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List dependencies (v1).

        Returns the raw v1 payload. Useful for SCA reporting and
        producing a flat dependency list across one or more projects.
        """
        if not org_id:
            raise ValueError("org_id is required")
        body: dict[str, Any] = {}
        if project_id is not None:
            body["filters"] = {"projects": [project_id]}
        result: dict[str, Any] = self._client.post(
            f"/v1/org/{org_id}/dependencies",
            params={"page": page, "perPage": per_page},
            json=body,
        ).json()
        return result
