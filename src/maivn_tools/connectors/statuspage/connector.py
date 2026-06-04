"""Atlassian Statuspage v1 REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Helpers


def _coerce_id(candidate: Any, *, field: str) -> str:
    """Accept a string ID, a resource dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError(f"{field} is required")
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in (field, "id"):
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        items = cast(list[Any], candidate)
        return _coerce_id(items[0], field=field)
    raise ValueError(f"{field} must be a non-empty string (or a resource dict)")


@toolset(prefix="statuspage")
class StatuspageToolSet:
    """A connector for the Atlassian Statuspage v1 REST API.

    Args:
        api_key: Page API key.
        page_id: Page ID this toolset operates against.
    """

    metadata = ProviderMetadata(
        name="statuspage",
        display_name="Statuspage",
        version="0.1.0",
        description="Incidents, components, maintenances, and subscriber pushes.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.statuspage.io/",
        homepage_url="https://www.atlassian.com/software/statuspage",
        tags=("observability", "communications"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        page_id: str,
        base_url: str = "https://api.statuspage.io",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key or not page_id:
            raise ValueError("api_key and page_id are required")
        self.connection = connection
        self._page_id = page_id
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Authorization", prefix="OAuth"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _path(self, suffix: str) -> str:
        return f"/v1/pages/{self._page_id}{suffix}"

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page(self) -> dict[str, Any]:
        """Return the page's configuration (name, URL, branding, etc.)."""
        return cast(dict[str, Any], self._client.get(self._path("")).json())

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_components(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List components on the status page.

        Returns compact summaries: ``component_ref``, ``name``,
        ``status`` (``operational``, ``degraded_performance``, etc.),
        ``description``, ``group_id``. Raw component IDs are omitted by
        default; set ``include_ids=True`` when a follow-up tool
        (``update_component``) needs the raw ID.
        """
        payload: Any = self._client.get(self._path("/components")).json()
        if not include_metadata:
            return cast(dict[str, Any], payload)
        items: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, component in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(component, dict):
                continue
            entry = cast(dict[str, Any], component)
            summary: dict[str, Any] = {
                "component_ref": f"component_{index}",
                "name": entry.get("name", ""),
                "status": entry.get("status", ""),
                "description": entry.get("description", ""),
                "group_id": entry.get("group_id", ""),
            }
            if include_ids:
                summary["component_id"] = entry.get("id", "")
            summaries.append(summary)
        return {"components": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_component(
        self,
        component_id: Any,
        *,
        status: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update a component's status, name, or description.

        ``component_id`` accepts a string ID or a component dict from
        ``list_components(include_ids=True)``. ``status`` must be one of
        ``operational``, ``under_maintenance``, ``degraded_performance``,
        ``partial_outage``, ``major_outage``.
        """
        cid = _coerce_id(component_id, field="component_id")
        component: dict[str, Any] = {}
        if status is not None:
            valid = {
                "operational",
                "under_maintenance",
                "degraded_performance",
                "partial_outage",
                "major_outage",
            }
            if status not in valid:
                raise ValueError(f"status must be one of {sorted(valid)}")
            component["status"] = status
        if name is not None:
            component["name"] = name
        if description is not None:
            component["description"] = description
        if not component:
            raise ValueError("at least one update field is required")
        return cast(
            dict[str, Any],
            self._client.patch(
                self._path(f"/components/{cid}"),
                json={"component": component},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_incidents(
        self,
        *,
        q: str | None = None,
        page: int = 1,
        per_page: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List incidents on the status page.

        Best first tool for incident overviews. Returns compact summaries:
        ``incident_ref``, ``name``, ``status``
        (``investigating``/``identified``/``monitoring``/``resolved``),
        ``impact``, ``created_at``, ``resolved_at``, ``shortlink``. Raw
        incident IDs omitted by default; set ``include_ids=True`` when
        a follow-up tool (``update_incident``, ``delete_incident``) needs
        them.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if include_metadata:
            per_page = min(per_page, _SUMMARY_MAX)
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if q is not None:
            params["q"] = q
        payload: Any = self._client.get(self._path("/incidents"), params=params).json()
        if not include_metadata:
            return cast(dict[str, Any], payload)
        items: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, incident in enumerate(items, start=1):
            if not isinstance(incident, dict):
                continue
            entry = cast(dict[str, Any], incident)
            summary: dict[str, Any] = {
                "incident_ref": f"incident_{index}",
                "name": entry.get("name", ""),
                "status": entry.get("status", ""),
                "impact": entry.get("impact", ""),
                "created_at": entry.get("created_at", ""),
                "resolved_at": entry.get("resolved_at", ""),
                "shortlink": entry.get("shortlink", ""),
            }
            if include_ids:
                summary["incident_id"] = entry.get("id", "")
            summaries.append(summary)
        return {"incidents": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_incident(
        self,
        *,
        name: str,
        status: str = "investigating",
        impact_override: str | None = None,
        body: str | None = None,
        component_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an incident.

        Returns the new incident. ``status`` must be one of
        ``investigating``, ``identified``, ``monitoring``, ``resolved``,
        ``scheduled``. ``body`` is the public-facing message.
        """
        if not name:
            raise ValueError("name is required")
        if status not in {
            "investigating",
            "identified",
            "monitoring",
            "resolved",
            "scheduled",
        }:
            raise ValueError("invalid status")
        incident: dict[str, Any] = {"name": name, "status": status}
        if impact_override is not None:
            incident["impact_override"] = impact_override
        if body is not None:
            incident["body"] = body
        if component_ids is not None:
            incident["component_ids"] = component_ids
        return cast(
            dict[str, Any],
            self._client.post(self._path("/incidents"), json={"incident": incident}).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_incident(
        self,
        incident_id: Any,
        *,
        status: str | None = None,
        body: str | None = None,
        impact_override: str | None = None,
    ) -> dict[str, Any]:
        """Patch an incident.

        ``incident_id`` accepts a string ID or an incident dict. Use to
        post updates (``body``) and advance the status.
        """
        iid = _coerce_id(incident_id, field="incident_id")
        incident: dict[str, Any] = {}
        if status is not None:
            incident["status"] = status
        if body is not None:
            incident["body"] = body
        if impact_override is not None:
            incident["impact_override"] = impact_override
        if not incident:
            raise ValueError("at least one update field is required")
        return cast(
            dict[str, Any],
            self._client.patch(
                self._path(f"/incidents/{iid}"),
                json={"incident": incident},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_incident(self, incident_id: Any) -> dict[str, Any]:
        """Delete an incident.

        Destructive — the incident and its updates are removed. Confirm
        with the user first. ``incident_id`` accepts a string ID or an
        incident dict.
        """
        iid = _coerce_id(incident_id, field="incident_id")
        response = self._client.delete(self._path(f"/incidents/{iid}"))
        return {
            "incident_id": iid,
            "deleted": True,
            "status": response.status,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def schedule_maintenance(
        self,
        *,
        name: str,
        scheduled_for: str,
        scheduled_until: str,
        body: str | None = None,
        component_ids: list[str] | None = None,
        auto_in_progress: bool = True,
        auto_completed: bool = True,
    ) -> dict[str, Any]:
        """Schedule a maintenance window.

        Returns the scheduled-maintenance incident. ``scheduled_for`` /
        ``scheduled_until`` are ISO-8601 timestamps.
        """
        if not name or not scheduled_for or not scheduled_until:
            raise ValueError("name, scheduled_for, and scheduled_until are required")
        incident: dict[str, Any] = {
            "name": name,
            "status": "scheduled",
            "scheduled_for": scheduled_for,
            "scheduled_until": scheduled_until,
            "scheduled_auto_in_progress": auto_in_progress,
            "scheduled_auto_completed": auto_completed,
        }
        if body is not None:
            incident["body"] = body
        if component_ids is not None:
            incident["component_ids"] = component_ids
        return cast(
            dict[str, Any],
            self._client.post(self._path("/incidents"), json={"incident": incident}).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_subscribers(
        self,
        *,
        type: str | None = None,
        page: int = 1,
        per_page: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List subscribers (email/sms/webhook).

        Returns compact summaries: ``subscriber_ref``, ``mode``
        (email/sms/webhook), ``email``/``phone_number``/``endpoint``,
        ``quarantined_at``. Raw subscriber IDs omitted by default; set
        ``include_ids=True`` if you need them.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if include_metadata:
            per_page = min(per_page, _SUMMARY_MAX)
        # The subscribers endpoint is the documented exception that uses the
        # 'limit' query param instead of the 'per_page' used by all other
        # endpoints; map the public per_page kwarg onto 'limit' on the wire.
        params: dict[str, Any] = {"page": page, "limit": per_page}
        if type is not None:
            params["type"] = type
        payload: Any = self._client.get(self._path("/subscribers"), params=params).json()
        if not include_metadata:
            return cast(dict[str, Any], payload)
        items: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, subscriber in enumerate(items, start=1):
            if not isinstance(subscriber, dict):
                continue
            entry = cast(dict[str, Any], subscriber)
            summary: dict[str, Any] = {
                "subscriber_ref": f"subscriber_{index}",
                "mode": entry.get("mode", ""),
                "email": entry.get("email", ""),
                "phone_number": entry.get("phone_number", ""),
                "endpoint": entry.get("endpoint", ""),
                "quarantined_at": entry.get("quarantined_at", ""),
            }
            if include_ids:
                summary["subscriber_id"] = entry.get("id", "")
            summaries.append(summary)
        return {"subscribers": summaries}
