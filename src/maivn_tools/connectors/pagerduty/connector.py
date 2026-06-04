# pyright: strict
"""PagerDuty REST + Events v2 API connector."""

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


def _coerce_incident_id(candidate: Any) -> str:
    """Accept a string ID, an incident dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("incident_id is required")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in ("incident_id", "id"):
            value = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        candidate_list = cast(list[Any], candidate)
        return _coerce_incident_id(candidate_list[0])
    raise ValueError("incident_id must be a non-empty string (or an incident dict)")


# MARK: ToolSet


@toolset(prefix="pagerduty")
class PagerDutyToolSet:
    """A connector for PagerDuty's REST API and Events v2.

    Args:
        api_key: REST API token (read-write or read-only).
        from_email: ``From`` header email for ``POST`` calls that require
            an actor.
        events_routing_key: Optional integration routing key for the
            Events v2 endpoint.
    """

    metadata = ProviderMetadata(
        name="pagerduty",
        display_name="PagerDuty",
        version="0.1.0",
        description="Incidents, services, schedules, on-call, and Events v2.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.pagerduty.com/api-reference/",
        homepage_url="https://www.pagerduty.com/",
        tags=("observability", "incidents"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        from_email: str | None = None,
        events_routing_key: str | None = None,
        base_url: str = "https://api.pagerduty.com",
        events_url: str = "https://events.pagerduty.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._from_email = from_email
        self._routing_key = events_routing_key
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Authorization", prefix="Token token="),
            transport=transport,
            default_headers={
                "Accept": "application/vnd.pagerduty+json;version=2",
                "Content-Type": "application/json",
            },
        )
        self._events_client = HttpClient(
            base_url=events_url.rstrip("/"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _require_from(self) -> dict[str, str]:
        if not self._from_email:
            raise ValueError("from_email must be set in the constructor for this call")
        return {"From": self._from_email}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_incidents(
        self,
        *,
        statuses: list[str] | None = None,
        service_ids: list[str] | None = None,
        limit: int = 25,
        offset: int = 0,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List active and recent incidents.

        Best first tool for incident triage. Returns compact summaries:
        ``incident_ref``, ``incident_number`` (human-readable), ``title``,
        ``status`` (``triggered``/``acknowledged``/``resolved``),
        ``urgency``, ``created_at``, and ``service_name``. Raw PagerDuty
        incident IDs are internal handles, omitted by default. Set
        ``include_ids=True`` only if a follow-up call (``get_incident``,
        ``update_incident``) needs the raw ID.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if statuses is not None:
            params["statuses[]"] = statuses
        if service_ids is not None:
            params["service_ids[]"] = service_ids
        payload: dict[str, Any] = self._client.get("/incidents", params=params).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("incidents") or []
        summaries: list[dict[str, Any]] = []
        for index, incident in enumerate(items, start=1):
            if not isinstance(incident, dict):
                continue
            incident_dict = cast(dict[str, Any], incident)
            service: Any = incident_dict.get("service") or {}
            service_dict = cast(dict[str, Any], service) if isinstance(service, dict) else {}
            summary: dict[str, Any] = {
                "incident_ref": f"incident_{index}",
                "incident_number": incident_dict.get("incident_number", ""),
                "title": incident_dict.get("title", incident_dict.get("summary", "")),
                "status": incident_dict.get("status", ""),
                "urgency": incident_dict.get("urgency", ""),
                "created_at": incident_dict.get("created_at", ""),
                "service_name": service_dict.get("summary", ""),
            }
            if include_ids:
                summary["incident_id"] = incident_dict.get("id", "")
            summaries.append(summary)
        return {"incidents": summaries, "more": payload.get("more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_incident(self, incident_id: Any) -> dict[str, Any]:
        """Return a single incident's full detail.

        ``incident_id`` accepts a string ID or an incident dict from
        ``list_incidents(include_ids=True)``.
        """
        iid = _coerce_incident_id(incident_id)
        result: dict[str, Any] = self._client.get(f"/incidents/{iid}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_incident(
        self,
        incident_id: Any,
        *,
        status: str | None = None,
        assignments: list[dict[str, Any]] | None = None,
        priority_id: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        """Update an incident (acknowledge, resolve, reassign, etc.).

        ``incident_id`` accepts a string ID or an incident dict. Pass
        ``status="acknowledged"`` to acknowledge, ``status="resolved"`` to
        resolve. Returns the updated incident resource.
        """
        iid = _coerce_incident_id(incident_id)
        incident: dict[str, Any] = {"type": "incident_reference"}
        if status is not None:
            incident["status"] = status
        if assignments is not None:
            incident["assignments"] = assignments
        if priority_id is not None:
            incident["priority"] = {"id": priority_id, "type": "priority_reference"}
        if resolution is not None:
            incident["resolution"] = resolution
        if len(incident) == 1:
            raise ValueError("at least one update field is required")
        result: dict[str, Any] = self._client.put(
            f"/incidents/{iid}",
            json={"incident": incident},
            headers=self._require_from(),
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def acknowledge_incident(self, incident_id: Any) -> dict[str, Any]:
        """Acknowledge an incident (shortcut for ``update_incident(status="acknowledged")``).

        ``incident_id`` accepts a string ID or an incident dict from
        ``list_incidents(include_ids=True)``. Returns the updated incident.
        """
        return self.update_incident(incident_id, status="acknowledged")

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_incident(
        self,
        *,
        title: str,
        service_id: str,
        urgency: str = "high",
        body: str | None = None,
        priority_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an incident via the REST API.

        Returns the new incident resource. ``service_id`` must be a valid
        PagerDuty service ID; use ``list_services`` first if unknown.
        """
        if not title or not service_id:
            raise ValueError("title and service_id are required")
        if urgency not in {"high", "low"}:
            raise ValueError("urgency must be high or low")
        incident: dict[str, Any] = {
            "type": "incident",
            "title": title,
            "service": {"id": service_id, "type": "service_reference"},
            "urgency": urgency,
        }
        if body is not None:
            incident["body"] = {"type": "incident_body", "details": body}
        if priority_id is not None:
            incident["priority"] = {"id": priority_id, "type": "priority_reference"}
        result: dict[str, Any] = self._client.post(
            "/incidents",
            json={"incident": incident},
            headers=self._require_from(),
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_event(
        self,
        *,
        summary: str,
        source: str,
        severity: str = "error",
        dedup_key: str | None = None,
        custom_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger an Events v2 alert (``trigger`` action).

        Returns the Events API acknowledgement (includes the assigned
        ``dedup_key``). Use ``resolve_event`` with that ``dedup_key`` once
        the underlying condition clears.
        """
        if not self._routing_key:
            raise ValueError("events_routing_key must be set in the constructor")
        if not summary or not source:
            raise ValueError("summary and source are required")
        if severity not in {"critical", "error", "warning", "info"}:
            raise ValueError("severity must be critical/error/warning/info")
        payload: dict[str, Any] = {
            "summary": summary,
            "source": source,
            "severity": severity,
        }
        if custom_details is not None:
            payload["custom_details"] = custom_details
        body: dict[str, Any] = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "payload": payload,
        }
        if dedup_key is not None:
            body["dedup_key"] = dedup_key
        result: dict[str, Any] = self._events_client.post("/v2/enqueue", json=body).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def resolve_event(self, dedup_key: str) -> dict[str, Any]:
        """Resolve a previously-triggered Events v2 alert.

        ``dedup_key`` must match the key returned by ``trigger_event``.
        """
        if not self._routing_key:
            raise ValueError("events_routing_key must be set")
        if not dedup_key:
            raise ValueError("dedup_key is required")
        result: dict[str, Any] = self._events_client.post(
            "/v2/enqueue",
            json={
                "routing_key": self._routing_key,
                "event_action": "resolve",
                "dedup_key": dedup_key,
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_services(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List services.

        Best first tool when you need a ``service_id`` for
        ``create_incident``. Returns compact summaries: ``service_ref``,
        ``name``, ``description``, ``status``. Raw service IDs omitted by
        default; set ``include_ids=True`` when you need them.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        payload: dict[str, Any] = self._client.get(
            "/services",
            params={"limit": limit, "offset": offset},
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("services") or []
        summaries: list[dict[str, Any]] = []
        for index, service in enumerate(items, start=1):
            if not isinstance(service, dict):
                continue
            service_dict = cast(dict[str, Any], service)
            summary: dict[str, Any] = {
                "service_ref": f"service_{index}",
                "name": service_dict.get("name", service_dict.get("summary", "")),
                "description": service_dict.get("description", ""),
                "status": service_dict.get("status", ""),
            }
            if include_ids:
                summary["service_id"] = service_dict.get("id", "")
            summaries.append(summary)
        return {"services": summaries, "more": payload.get("more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_schedules(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List on-call schedules.

        Returns compact summaries: ``schedule_ref``, ``name``,
        ``description``, ``time_zone``. Raw schedule IDs omitted by
        default; needed for ``list_on_calls(schedule_ids=...)`` so set
        ``include_ids=True`` for that path.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        payload: dict[str, Any] = self._client.get(
            "/schedules",
            params={"limit": limit, "offset": offset},
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("schedules") or []
        summaries: list[dict[str, Any]] = []
        for index, schedule in enumerate(items, start=1):
            if not isinstance(schedule, dict):
                continue
            schedule_dict = cast(dict[str, Any], schedule)
            summary: dict[str, Any] = {
                "schedule_ref": f"schedule_{index}",
                "name": schedule_dict.get("name", schedule_dict.get("summary", "")),
                "description": schedule_dict.get("description", ""),
                "time_zone": schedule_dict.get("time_zone", ""),
            }
            if include_ids:
                summary["schedule_id"] = schedule_dict.get("id", "")
            summaries.append(summary)
        return {"schedules": summaries, "more": payload.get("more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_on_calls(
        self,
        *,
        schedule_ids: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List the currently active on-calls.

        Returns compact summaries: ``oncall_ref``, ``user_name``,
        ``escalation_level``, ``schedule_name``, ``start``, ``end``. Use
        this to answer "who is on call right now?" Set ``include_ids=True``
        for raw user/schedule IDs.
        """
        params: dict[str, Any] = {}
        if schedule_ids is not None:
            params["schedule_ids[]"] = schedule_ids
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        payload: dict[str, Any] = self._client.get("/oncalls", params=params or None).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("oncalls") or []
        summaries: list[dict[str, Any]] = []
        for index, oncall in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(oncall, dict):
                continue
            oncall_dict = cast(dict[str, Any], oncall)
            user: Any = oncall_dict.get("user") or {}
            user_dict = cast(dict[str, Any], user) if isinstance(user, dict) else {}
            schedule: Any = oncall_dict.get("schedule") or {}
            schedule_dict = cast(dict[str, Any], schedule) if isinstance(schedule, dict) else {}
            summary: dict[str, Any] = {
                "oncall_ref": f"oncall_{index}",
                "user_name": user_dict.get("summary", ""),
                "escalation_level": oncall_dict.get("escalation_level", ""),
                "schedule_name": schedule_dict.get("summary", ""),
                "start": oncall_dict.get("start", ""),
                "end": oncall_dict.get("end", ""),
            }
            if include_ids:
                summary["user_id"] = user_dict.get("id", "")
                summary["schedule_id"] = schedule_dict.get("id", "")
            summaries.append(summary)
        return {"oncalls": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List users.

        Returns compact summaries: ``user_ref``, ``name``, ``email``,
        ``role``, ``time_zone``. Raw user IDs omitted by default; set
        ``include_ids=True`` when needed.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        payload: dict[str, Any] = self._client.get(
            "/users",
            params={"limit": limit, "offset": offset},
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("users") or []
        summaries: list[dict[str, Any]] = []
        for index, user in enumerate(items, start=1):
            if not isinstance(user, dict):
                continue
            user_dict = cast(dict[str, Any], user)
            summary: dict[str, Any] = {
                "user_ref": f"user_{index}",
                "name": user_dict.get("name", user_dict.get("summary", "")),
                "email": user_dict.get("email", ""),
                "role": user_dict.get("role", ""),
                "time_zone": user_dict.get("time_zone", ""),
            }
            if include_ids:
                summary["user_id"] = user_dict.get("id", "")
            summaries.append(summary)
        return {"users": summaries, "more": payload.get("more", False)}
