"""Grafana (self-hosted / Cloud) HTTP API connector."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Helpers


def _coerce_uid(candidate: Any, *, field: str) -> str:
    """Accept a UID string, a resource dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError(f"{field} is required")
        return candidate
    if isinstance(candidate, dict):
        mapping: dict[str, Any] = cast("dict[str, Any]", candidate)
        for key in (field, "uid", "id"):
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        return _coerce_uid(candidate[0], field=field)
    raise ValueError(f"{field} must be a non-empty string (or a resource dict)")


# MARK: ToolSet


@toolset(prefix="grafana")
class GrafanaToolSet:
    """A connector for Grafana's HTTP API.

    Args:
        api_key: Service account or API token (``glsa_...``).
        base_url: Grafana base URL (e.g. ``https://stack.grafana.net``).
    """

    metadata = ProviderMetadata(
        name="grafana",
        display_name="Grafana",
        version="0.1.0",
        description="Dashboards, folders, datasources, alerting, and annotations.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://grafana.com/docs/grafana/latest/developers/http_api/",
        homepage_url="https://grafana.com/",
        tags=("observability", "dashboards"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key or not base_url:
            raise ValueError("api_key and base_url are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
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
    def search_dashboards(
        self,
        *,
        query: str | None = None,
        tag: list[str] | None = None,
        type: str | None = None,
        limit: int = 25,
        page: int = 1,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search dashboards / folders.

        Best first tool for dashboard discovery. Returns compact
        summaries: ``dashboard_ref``, ``title``, ``type``, ``url``,
        ``folder_title``, ``tags``. Dashboard UIDs are omitted by default
        because they are internal handles; set ``include_ids=True`` when
        a follow-up tool (``get_dashboard_by_uid``,
        ``delete_dashboard_by_uid``) needs the UID.
        """
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        params: dict[str, Any] = {"limit": limit, "page": page}
        if query is not None:
            params["query"] = query
        if tag is not None:
            params["tag"] = tag
        if type is not None:
            params["type"] = type
        payload: Any = self._client.get("/api/search", params=params).json()
        if not include_metadata:
            return cast("dict[str, Any]", payload)
        items: list[Any] = cast(
            "list[Any]",
            payload if isinstance(payload, list) else (payload.get("dashboards") or []),
        )
        summaries: list[dict[str, Any]] = []
        for index, raw_dashboard in enumerate(items, start=1):
            if not isinstance(raw_dashboard, dict):
                continue
            dashboard: dict[str, Any] = cast("dict[str, Any]", raw_dashboard)
            summary: dict[str, Any] = {
                "dashboard_ref": f"dashboard_{index}",
                "title": dashboard.get("title", ""),
                "type": dashboard.get("type", ""),
                "url": dashboard.get("url", ""),
                "folder_title": dashboard.get("folderTitle", ""),
                "tags": dashboard.get("tags", []),
            }
            if include_ids:
                summary["dashboard_uid"] = dashboard.get("uid", "")
                summary["dashboard_id"] = dashboard.get("id", "")
            summaries.append(summary)
        return {"dashboards": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dashboard_by_uid(self, uid: Any) -> dict[str, Any]:
        """Return a dashboard by UID.

        ``uid`` accepts a string UID or a dashboard dict from
        ``search_dashboards(include_ids=True)``. Returns the full
        dashboard JSON (panels, variables, etc.).
        """
        u = _coerce_uid(uid, field="uid")
        return self._client.get(f"/api/dashboards/uid/{u}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_or_update_dashboard(
        self,
        *,
        dashboard: dict[str, Any],
        folder_uid: str | None = None,
        message: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create or update a dashboard.

        Returns the new revision (``id``, ``uid``, ``version``,
        ``status``). To update an existing dashboard, the ``dashboard``
        dict must include its ``uid`` and ``id``; set ``overwrite=True``
        to allow replacing.
        """
        if not dashboard:
            raise ValueError("dashboard is required")
        body: dict[str, Any] = {"dashboard": dashboard, "overwrite": overwrite}
        if folder_uid is not None:
            body["folderUid"] = folder_uid
        if message is not None:
            body["message"] = message
        return self._client.post("/api/dashboards/db", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_dashboard_by_uid(self, uid: Any) -> dict[str, Any]:
        """Delete a dashboard by UID.

        Destructive — confirm with the user first. ``uid`` accepts a
        string UID or a dashboard dict.
        """
        u = _coerce_uid(uid, field="uid")
        return self._client.delete(f"/api/dashboards/uid/{u}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_folders(
        self,
        *,
        limit: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List folders.

        Returns compact summaries: ``folder_ref``, ``title``,
        ``parent_uid``. Folder UIDs omitted by default; set
        ``include_ids=True`` when needed.
        """
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        payload: Any = self._client.get("/api/folders", params={"limit": limit}).json()
        if not include_metadata:
            return cast("dict[str, Any]", payload)
        items: list[Any] = cast(
            "list[Any]",
            payload if isinstance(payload, list) else (payload.get("folders") or []),
        )
        summaries: list[dict[str, Any]] = []
        for index, raw_folder in enumerate(items, start=1):
            if not isinstance(raw_folder, dict):
                continue
            folder: dict[str, Any] = cast("dict[str, Any]", raw_folder)
            summary: dict[str, Any] = {
                "folder_ref": f"folder_{index}",
                "title": folder.get("title", ""),
                "parent_uid": folder.get("parentUid", ""),
            }
            if include_ids:
                summary["folder_uid"] = folder.get("uid", "")
                summary["folder_id"] = folder.get("id", "")
            summaries.append(summary)
        return {"folders": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_folder(
        self,
        *,
        title: str,
        uid: str | None = None,
        parent_uid: str | None = None,
    ) -> dict[str, Any]:
        """Create a folder.

        Returns the new folder resource (with its server-assigned UID if
        none was provided).
        """
        if not title:
            raise ValueError("title is required")
        body: dict[str, Any] = {"title": title}
        if uid is not None:
            body["uid"] = uid
        if parent_uid is not None:
            body["parentUid"] = parent_uid
        return self._client.post("/api/folders", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_datasources(self) -> dict[str, Any]:
        """List datasources.

        Returns the raw datasource array (each entry has ``id``, ``uid``,
        ``name``, ``type``, ``url``, etc.).
        """
        return self._client.get("/api/datasources").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_annotation(
        self,
        *,
        text: str,
        time: int,
        time_end: int | None = None,
        tags: list[str] | None = None,
        dashboard_uid: str | None = None,
        panel_id: int | None = None,
    ) -> dict[str, Any]:
        """Create an annotation (event marker on dashboards).

        Returns ``{"id": ..., "message": ...}``. Use for marking
        deploys, incident windows, or other notable events.
        """
        if not text or not time:
            raise ValueError("text and time are required")
        body: dict[str, Any] = {"text": text, "time": time}
        if time_end is not None:
            body["timeEnd"] = time_end
        if tags is not None:
            body["tags"] = tags
        if dashboard_uid is not None:
            body["dashboardUID"] = dashboard_uid
        if panel_id is not None:
            body["panelId"] = panel_id
        return self._client.post("/api/annotations", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_alert_rules(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Grafana-managed alert rules.

        Returns compact summaries: ``alert_ref``, ``title``,
        ``folder_uid``, ``rule_group``, ``condition``, ``no_data_state``,
        ``exec_err_state``. Rule UIDs omitted by default; set
        ``include_ids=True`` when needed.
        """
        payload: Any = self._client.get("/api/v1/provisioning/alert-rules").json()
        if not include_metadata:
            return cast("dict[str, Any]", payload)
        items: list[Any] = cast(
            "list[Any]",
            payload if isinstance(payload, list) else (payload.get("alerts") or []),
        )
        summaries: list[dict[str, Any]] = []
        for index, raw_rule in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(raw_rule, dict):
                continue
            rule: dict[str, Any] = cast("dict[str, Any]", raw_rule)
            summary: dict[str, Any] = {
                "alert_ref": f"alert_{index}",
                "title": rule.get("title", ""),
                "folder_uid": rule.get("folderUID", ""),
                "rule_group": rule.get("ruleGroup", ""),
                "condition": rule.get("condition", ""),
                "no_data_state": rule.get("noDataState", ""),
                "exec_err_state": rule.get("execErrState", ""),
            }
            if include_ids:
                summary["alert_uid"] = rule.get("uid", "")
            summaries.append(summary)
        return {"alerts": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_health(self) -> dict[str, Any]:
        """Return server health.

        Returns ``{"commit": ..., "database": "ok", "version": ...}``.
        Good for a sanity check before issuing more expensive calls.
        """
        return self._client.get("/api/health").json()
