"""Sentry REST API connector."""

# pyright: strict
from __future__ import annotations

import re
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpResponse, HttpTransport

# MARK: Constants

_SUMMARY_MAX = 25
_LINK_NEXT_RE = re.compile(
    r'<[^>]*>\s*;\s*rel="next"[^,]*',
    re.IGNORECASE,
)
_LINK_RESULTS_RE = re.compile(r'results="(?P<value>[^"]*)"', re.IGNORECASE)
_LINK_CURSOR_RE = re.compile(r'cursor="(?P<value>[^"]*)"', re.IGNORECASE)


# MARK: Helpers


def _next_cursor(response: HttpResponse) -> str | None:
    """Extract the next-page cursor from Sentry's ``Link`` response header.

    Sentry paginates via the HTTP ``Link`` header, e.g.::

        <https://...>; rel="next"; results="true"; cursor="0:100:0"

    Returns the ``cursor`` value of the ``rel="next"`` segment only when it
    advertises ``results="true"``; otherwise ``None`` (no further pages).
    """
    link = response.header("Link")
    if not link:
        return None
    match = _LINK_NEXT_RE.search(link)
    if match is None:
        return None
    segment = match.group(0)
    results = _LINK_RESULTS_RE.search(segment)
    if results is not None and results.group("value").lower() != "true":
        return None
    cursor = _LINK_CURSOR_RE.search(segment)
    if cursor is None:
        return None
    return cursor.group("value") or None


def _coerce_issue_id(candidate: Any) -> str:
    """Accept a string ID, an issue dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("issue_id is required")
        return candidate
    if isinstance(candidate, int) and not isinstance(candidate, bool):
        return str(candidate)
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("issue_id", "id"):
            value = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int) and not isinstance(value, bool):
                return str(value)
    if isinstance(candidate, list) and candidate:
        return _coerce_issue_id(candidate[0])
    raise ValueError("issue_id must be a non-empty string (or an issue dict)")


# MARK: ToolSet


@toolset(prefix="sentry")
class SentryToolSet:
    """A connector for the Sentry REST API.

    Args:
        auth_token: User auth token or internal-integration token.
        base_url: API root (default ``https://sentry.io/api/0``).
    """

    metadata = ProviderMetadata(
        name="sentry",
        display_name="Sentry",
        version="0.1.0",
        description="Projects, issues, events, releases, alerts, and organizations.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.sentry.io/api/",
        homepage_url="https://sentry.io/",
        tags=("observability", "errors"),
    )

    def __init__(
        self,
        *,
        auth_token: str,
        base_url: str = "https://sentry.io/api/0",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not auth_token:
            raise ValueError("auth_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(auth_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_organizations(self) -> dict[str, Any]:
        """List orgs the auth token can access.

        Returns the raw provider response (an array of org resources with
        ``slug``, ``name``, ``id``). Use ``slug`` for subsequent calls.
        """
        return self._client.get("/organizations/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_projects(self, org_slug: str) -> dict[str, Any]:
        """List projects in an organization.

        Returns the array of project resources. Each project has a ``slug``
        used for project-scoped calls and a numeric ``id``.
        """
        if not org_slug:
            raise ValueError("org_slug is required")
        return self._client.get(f"/organizations/{org_slug}/projects/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(
        self,
        *,
        org_slug: str,
        project_slug: str,
    ) -> dict[str, Any]:
        """Return a single project's detail (platform, teams, options)."""
        if not org_slug or not project_slug:
            raise ValueError("org_slug and project_slug are required")
        return self._client.get(f"/projects/{org_slug}/{project_slug}/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_issues(
        self,
        *,
        org_slug: str,
        project_slug: str,
        query: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List issues (errors) in a project.

        Best first tool for triaging errors. Returns compact summaries by
        default: ``issue_ref``, ``title``, ``culprit``, ``status``
        (``unresolved``/``resolved``/``ignored``), ``level`` (severity),
        ``count`` (events), ``last_seen``, and ``permalink``. Raw Sentry
        issue IDs are internal handles, omitted by default; set
        ``include_ids=True`` only when a follow-up tool (``get_issue``,
        ``update_issue``, ``delete_issue``) needs them.

        ``query`` follows Sentry's search DSL, e.g. ``is:unresolved``.
        """
        if not org_slug or not project_slug:
            raise ValueError("org_slug and project_slug are required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        params: dict[str, Any] = {"limit": limit}
        if query is not None:
            params["query"] = query
        if cursor is not None:
            params["cursor"] = cursor
        response = self._client.get(
            f"/projects/{org_slug}/{project_slug}/issues/",
            params=params,
        )
        payload: Any = response.json()
        if not include_metadata:
            return payload
        items: list[Any] = (
            cast("list[Any]", payload)
            if isinstance(payload, list)
            else cast("list[Any]", payload.get("issues") or [])
        )
        summaries: list[dict[str, Any]] = []
        for index, issue in enumerate(items, start=1):
            if not isinstance(issue, dict):
                continue
            issue_dict = cast("dict[str, Any]", issue)
            summary: dict[str, Any] = {
                "issue_ref": f"issue_{index}",
                "title": issue_dict.get("title", ""),
                "culprit": issue_dict.get("culprit", ""),
                "status": issue_dict.get("status", ""),
                "level": issue_dict.get("level", ""),
                "count": issue_dict.get("count", ""),
                "last_seen": issue_dict.get("lastSeen", ""),
                "permalink": issue_dict.get("permalink", ""),
            }
            if include_ids:
                summary["issue_id"] = issue_dict.get("id", "")
            summaries.append(summary)
        return {"issues": summaries, "next_cursor": _next_cursor(response)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_issue(self, issue_id: Any, *, org_slug: str) -> dict[str, Any]:
        """Return one issue's full detail.

        ``issue_id`` accepts a raw Sentry issue ID (string) or an issue
        dict returned by ``list_issues(include_ids=True)``. ``org_slug`` is
        the organization slug or ID the issue belongs to (the same
        ``org_slug`` passed to ``list_issues``).
        """
        if not org_slug:
            raise ValueError("org_slug is required")
        iid = _coerce_issue_id(issue_id)
        return self._client.get(f"/organizations/{org_slug}/issues/{iid}/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_issue(
        self,
        issue_id: Any,
        *,
        org_slug: str,
        status: str | None = None,
        assigned_to: str | None = None,
        is_bookmarked: bool | None = None,
        has_seen: bool | None = None,
    ) -> dict[str, Any]:
        """Update issue state (resolve / assign / bookmark / mark seen).

        ``issue_id`` accepts a string ID or an issue dict from
        ``list_issues(include_ids=True)``. ``org_slug`` is the organization
        slug or ID the issue belongs to. Returns the updated issue.
        """
        if not org_slug:
            raise ValueError("org_slug is required")
        iid = _coerce_issue_id(issue_id)
        body: dict[str, Any] = {}
        if status is not None:
            body["status"] = status
        if assigned_to is not None:
            body["assignedTo"] = assigned_to
        if is_bookmarked is not None:
            body["isBookmarked"] = is_bookmarked
        if has_seen is not None:
            body["hasSeen"] = has_seen
        if not body:
            raise ValueError("at least one field is required")
        return self._client.put(f"/organizations/{org_slug}/issues/{iid}/", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_issue(self, issue_id: Any, *, org_slug: str) -> dict[str, Any]:
        """Delete an issue and all its events.

        Destructive and not reversible. Confirm with the user first.
        ``issue_id`` accepts a string ID or an issue dict. ``org_slug`` is
        the organization slug or ID the issue belongs to.
        """
        if not org_slug:
            raise ValueError("org_slug is required")
        iid = _coerce_issue_id(issue_id)
        response = self._client.delete(f"/organizations/{org_slug}/issues/{iid}/")
        return {"issue_id": iid, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_events_for_issue(
        self,
        issue_id: Any,
        *,
        org_slug: str,
        full: bool = False,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List events for an issue.

        Returns the raw event list. ``org_slug`` is the organization slug or
        ID the issue belongs to. ``full=True`` includes full event data;
        otherwise a minimal subset is returned.
        """
        if not org_slug:
            raise ValueError("org_slug is required")
        iid = _coerce_issue_id(issue_id)
        params: dict[str, Any] = {"full": str(full).lower()}
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get(
            f"/organizations/{org_slug}/issues/{iid}/events/", params=params
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_releases(self, org_slug: str) -> dict[str, Any]:
        """List releases in an organization.

        Returns the array of release resources (``version``, ``dateCreated``,
        ``projects``, etc.).
        """
        if not org_slug:
            raise ValueError("org_slug is required")
        return self._client.get(f"/organizations/{org_slug}/releases/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_release(
        self,
        *,
        org_slug: str,
        version: str,
        projects: list[str],
        ref: str | None = None,
        url: str | None = None,
        commits: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a release in an organization.

        Returns the new release resource. ``projects`` is a list of project
        slugs the release applies to.
        """
        if not org_slug or not version or not projects:
            raise ValueError("org_slug, version, and projects are required")
        body: dict[str, Any] = {"version": version, "projects": projects}
        if ref is not None:
            body["ref"] = ref
        if url is not None:
            body["url"] = url
        if commits is not None:
            body["commits"] = commits
        return self._client.post(f"/organizations/{org_slug}/releases/", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_alert_rules(
        self,
        *,
        org_slug: str,
        project_slug: str,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List issue alert rules for a project.

        Returns compact summaries by default: ``alert_ref``, ``name``,
        ``environment``, ``frequency``, ``conditions_count``, and
        ``actions_count``. Rule IDs are omitted by default; set
        ``include_ids=True`` if a follow-up call needs them.
        """
        if not org_slug or not project_slug:
            raise ValueError("org_slug and project_slug are required")
        payload: Any = self._client.get(
            f"/projects/{org_slug}/{project_slug}/rules/",
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = (
            cast("list[Any]", payload)
            if isinstance(payload, list)
            else cast("list[Any]", payload.get("rules") or [])
        )
        summaries: list[dict[str, Any]] = []
        for index, rule in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(rule, dict):
                continue
            rule_dict = cast("dict[str, Any]", rule)
            summary: dict[str, Any] = {
                "alert_ref": f"alert_{index}",
                "name": rule_dict.get("name", ""),
                "environment": rule_dict.get("environment", ""),
                "frequency": rule_dict.get("frequency", ""),
                "conditions_count": len(rule_dict.get("conditions", []) or []),
                "actions_count": len(rule_dict.get("actions", []) or []),
            }
            if include_ids:
                summary["alert_id"] = rule_dict.get("id", "")
            summaries.append(summary)
        return {"alerts": summaries}
