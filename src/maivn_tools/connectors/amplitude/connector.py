"""Amplitude HTTP API connector (HTTP V2 + Dashboard REST + Cohorts)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    EXPORT_RAW_EVENTS_OUTPUT,
    GET_USER_SEARCH_OUTPUT,
    LIST_COHORTS_OUTPUT,
)

# Dashboard / Cohort / Export REST hosts (Basic auth).
_REST_HOST_US = "amplitude.com"
_REST_HOST_EU = "analytics.eu.amplitude.com"
# Event ingestion hosts for HTTP V2 (/2/httpapi) and Identify (/identify).
_INGEST_HOST_US = "api2.amplitude.com"
_INGEST_HOST_EU = "api.eu.amplitude.com"


@toolset(prefix="amplitude")
class AmplitudeToolSet:
    """A connector for Amplitude.

    Args:
        api_key: Project API key (used for HTTP V2 ingest).
        secret_key: Project secret key (paired with the API key for Basic
            auth against the Dashboard / Cohort APIs).
        region: ``"US"`` (default) or ``"EU"``.
    """

    metadata = ProviderMetadata(
        name="amplitude",
        display_name="Amplitude",
        version="0.1.0",
        description="Event ingest, dashboards, cohorts, and user lookups.",
        auth_modes=(AuthMode.BASIC, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://www.docs.developers.amplitude.com/",
        homepage_url="https://amplitude.com/",
        tags=("analytics", "product"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        region: str = "US",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("api_key and secret_key are required")
        if region not in {"US", "EU"}:
            raise ValueError("region must be US or EU")
        self.connection = connection
        self._api_key = api_key
        rest_host = _REST_HOST_US if region == "US" else _REST_HOST_EU
        ingest_host = _INGEST_HOST_US if region == "US" else _INGEST_HOST_EU
        self._client = HttpClient(
            base_url=f"https://{rest_host}",
            auth=BasicAuth(api_key, secret_key),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        # Event ingestion (HTTP V2 + Identify) lives on a separate host and
        # authenticates via the in-body/form api_key, not the Basic header.
        self._ingest_client = HttpClient(
            base_url=f"https://{ingest_host}",
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @property
    def ingest_client(self) -> HttpClient:
        return self._ingest_client

    # MARK: - Internal helpers

    @staticmethod
    def _cohort_summary(
        cohort: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "cohort_ref": f"cohort_{index}",
            "name": cohort.get("name", ""),
            "description": cohort.get("description", ""),
            "size": cohort.get("size", 0),
            "owner": cohort.get("owner", ""),
            "last_modified": cohort.get("last_mod", "") or cohort.get("lastMod", ""),
        }
        if include_ids:
            summary["cohort_id"] = cohort.get("id", "")
        return summary

    @staticmethod
    def _user_summary(
        user: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "user_ref": f"user_{index}",
            "user_id": user.get("user_id", ""),
            "last_seen": user.get("last_seen", "") or user.get("last_used", ""),
        }
        if include_ids:
            summary["amplitude_id"] = user.get("amplitude_id", "")
            summary["device_id"] = user.get("device_id", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload_events(
        self,
        events: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send events via HTTP V2.

        Use this to ingest a batch of analytics events. Each entry in
        ``events`` must include at least ``event_type`` and one of
        ``user_id``/``device_id``. Returns the Amplitude ingest receipt
        ``{"code": 200, "events_ingested": <n>, ...}``.
        """
        if not events:
            raise ValueError("events must be non-empty")
        body: dict[str, Any] = {"api_key": self._api_key, "events": events}
        if options is not None:
            body["options"] = options
        return self._ingest_client.post(
            "/2/httpapi",
            json=body,
            headers={"Content-Type": "application/json"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def identify(self, identifications: list[dict[str, Any]]) -> dict[str, Any]:
        """Update user / group properties via the Identify API.

        Each entry should carry ``user_id`` or ``device_id`` and a
        ``user_properties`` dict. Returns the ingest receipt. Confirm the
        identification payload with the user before calling.
        """
        if not identifications:
            raise ValueError("identifications must be non-empty")
        import json as _json
        from urllib.parse import urlencode

        form_body = urlencode(
            {
                "api_key": self._api_key,
                "identification": _json.dumps(identifications),
            }
        ).encode("utf-8")
        return self._ingest_client.post(
            "/identify",
            data=form_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def event_segmentation(
        self,
        *,
        event: dict[str, Any],
        start: str,
        end: str,
        interval: int = 1,
        segment_definitions: list[dict[str, Any]] | None = None,
        group_by: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run an event-segmentation chart query.

        Best tool for "how many <event> happened over <range>" questions.
        ``start``/``end`` are Amplitude date strings (``"YYYYMMDD"`` or
        ``"YYYYMMDDTHH"``). Returns the segmentation chart payload with a
        ``data`` series.
        """
        if not event or not start or not end:
            raise ValueError("event, start, and end are required")
        import json as _json

        params: dict[str, Any] = {
            "e": _json.dumps(event),
            "start": start,
            "end": end,
            "i": interval,
        }
        if segment_definitions is not None:
            params["s"] = _json.dumps(segment_definitions)
        if group_by is not None:
            params["g"] = _json.dumps(group_by)
        return self._client.get("/api/2/events/segmentation", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def funnel_analysis(
        self,
        *,
        events: list[dict[str, Any]],
        start: str,
        end: str,
        conversion_window: int | None = None,
        mode: str = "ordered",
    ) -> dict[str, Any]:
        """Run a funnel analysis across an ordered list of events.

        Use to measure step-conversion through a defined flow.
        ``conversion_window`` is in seconds. ``mode`` must be one of
        ``ordered``/``unordered``/``sequential``.
        """
        if not events or not start or not end:
            raise ValueError("events, start, and end are required")
        if mode not in {"ordered", "unordered", "sequential"}:
            raise ValueError("mode must be ordered/unordered/sequential")
        import json as _json

        params: dict[str, Any] = {
            "e": [_json.dumps(e) for e in events],
            "start": start,
            "end": end,
            "mode": mode,
        }
        if conversion_window is not None:
            params["cs"] = conversion_window
        return self._client.get("/api/2/funnels", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def retention_analysis(
        self,
        *,
        starting_event: dict[str, Any],
        returning_event: dict[str, Any],
        start: str,
        end: str,
        retention_type: str = "n-day",
        interval: int = 1,
    ) -> dict[str, Any]:
        """Run a retention analysis.

        Use to measure how often users that triggered ``starting_event``
        come back and trigger ``returning_event`` within the date range.
        ``retention_type`` (the ``rm`` param) must be one of ``bracket``,
        ``rolling``, or ``n-day``. Returns the Amplitude retention payload.
        """
        if not start or not end:
            raise ValueError("start and end are required")
        if retention_type not in {"bracket", "rolling", "n-day"}:
            raise ValueError("retention_type must be bracket/rolling/n-day")
        import json as _json

        return self._client.get(
            "/api/2/retention",
            params={
                "se": _json.dumps(starting_event),
                "re": _json.dumps(returning_event),
                "start": start,
                "end": end,
                "rm": retention_type,
                "i": interval,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_activity(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return a user's recent event stream.

        Use after ``get_user_search`` (or when you already have a known
        ``user_id``) to inspect what the user has done recently. Returns
        ``{"userData": {...}, "events": [...]}``.
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(
            "/api/2/useractivity",
            params={"user": user_id, "offset": offset, "limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(GET_USER_SEARCH_OUTPUT)
    def get_user_search(
        self,
        search: str,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search for users by user ID, device ID, or Amplitude ID.

        Best first tool for finding a user. Returns compact
        ``user_ref`` summaries (``user_1``, ``user_2``, ...) with the
        public ``user_id`` and ``last_seen`` fields by default. Raw
        Amplitude IDs (``amplitude_id``, ``device_id``) are omitted unless
        ``include_ids=True``. Pass ``user_id`` to ``get_user_activity``
        for the user's event stream.
        """
        if not search:
            raise ValueError("search is required")
        payload: dict[str, Any] = self._client.get(
            "/api/2/usersearch", params={"user": search}
        ).json()
        matches: object = payload.get("matches", [])
        if not isinstance(matches, list):
            return payload
        matches_list = cast("list[Any]", matches)
        summaries = [
            self._user_summary(cast("dict[str, Any]", user), index=index, include_ids=include_ids)
            for index, user in enumerate(matches_list, start=1)
            if isinstance(user, dict)
        ]
        return {
            "users": summaries,
            "type": payload.get("type", ""),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_COHORTS_OUTPUT)
    def list_cohorts(
        self,
        *,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List behavioral cohorts in the Amplitude project.

        Best first tool for cohort discovery. Returns compact summaries
        with ``cohort_ref`` (``cohort_1``, ``cohort_2``, ...), human name,
        owner, size, and description. Raw Amplitude cohort IDs are omitted
        unless ``include_ids=True``; set that flag only when a follow-up
        ``get_cohort`` call needs the raw ID.
        """
        payload: dict[str, Any] = self._client.get("/api/3/cohorts").json()
        cohorts: object = payload.get("cohorts", [])
        if not isinstance(cohorts, list):
            return payload
        cohorts_list = cast("list[Any]", cohorts)
        limited: list[Any] = (
            cohorts_list[:limit] if limit and len(cohorts_list) > limit else cohorts_list
        )
        summaries = [
            self._cohort_summary(
                cast("dict[str, Any]", cohort), index=index, include_ids=include_ids
            )
            for index, cohort in enumerate(limited, start=1)
            if isinstance(cohort, dict)
        ]
        return {
            "cohorts": summaries,
            "totalAvailable": len(cohorts_list),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_cohort(
        self,
        cohort_id: str,
        *,
        props: bool = False,
    ) -> dict[str, Any]:
        """Return a cohort's user list.

        ``cohort_id`` is the raw Amplitude cohort ID returned by
        ``list_cohorts(include_ids=True)``. Returns ``{"cohort_id": ...,
        "request_id": ..., "members": [...]}``. The ID is an internal
        handle and should not appear in final answers.
        """
        if not cohort_id:
            raise ValueError("cohort_id is required")
        return self._client.get(
            f"/api/5/cohorts/request/{cohort_id}",
            params={"props": "1" if props else "0"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(EXPORT_RAW_EVENTS_OUTPUT)
    def export_raw_events(
        self,
        *,
        start: str,
        end: str,
    ) -> dict[str, Any]:
        """Request a raw event export.

        ``start``/``end`` are Amplitude date strings (``"YYYYMMDDTHH"``).
        Returns ``{"status": <http_status>}``. Large exports may take time
        to be available for download via the Amplitude UI.
        """
        if not start or not end:
            raise ValueError("start and end are required")
        response = self._client.get(
            "/api/2/export",
            params={"start": start, "end": end},
        )
        return {"status": response.status}
