"""Mixpanel Ingestion + Query API connector."""

# pyright: strict

from __future__ import annotations

import base64
import json as _json
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: ToolSet


@toolset(prefix="mixpanel")
class MixpanelToolSet:
    """A connector for Mixpanel.

    Args:
        project_token: Project token used for ingest endpoints.
        service_account_user: Service-account user (for query API
            Basic auth).
        service_account_secret: Service-account secret.
        project_id: Project ID (numeric).
        region: ``"US"`` (default) or ``"EU"``.
    """

    metadata = ProviderMetadata(
        name="mixpanel",
        display_name="Mixpanel",
        version="0.1.0",
        description="Event ingest, profile updates, segmentation, and exports.",
        auth_modes=(AuthMode.API_KEY, AuthMode.BASIC),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.mixpanel.com/reference/overview",
        homepage_url="https://mixpanel.com/",
        tags=("analytics", "product"),
    )

    def __init__(
        self,
        *,
        project_token: str,
        service_account_user: str,
        service_account_secret: str,
        project_id: int,
        region: str = "US",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if (
            not project_token
            or not service_account_user
            or not service_account_secret
            or not project_id
        ):
            raise ValueError(
                "project_token, service_account_user, "
                "service_account_secret, and project_id are required"
            )
        if region not in {"US", "EU"}:
            raise ValueError("region must be US or EU")
        self.connection = connection
        self._project_token = project_token
        self._project_id = project_id
        api_host = "api.mixpanel.com" if region == "US" else "api-eu.mixpanel.com"
        query_host = "mixpanel.com" if region == "US" else "eu.mixpanel.com"
        data_host = "data.mixpanel.com" if region == "US" else "data-eu.mixpanel.com"
        self._ingest = HttpClient(
            base_url=f"https://{api_host}",
            auth=BasicAuth(service_account_user, service_account_secret),
            transport=transport,
            default_headers={"Accept": "text/plain"},
        )
        self._query = HttpClient(
            base_url=f"https://{query_host}",
            auth=BasicAuth(service_account_user, service_account_secret),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._export = HttpClient(
            base_url=f"https://{data_host}",
            auth=BasicAuth(service_account_user, service_account_secret),
            transport=transport,
            default_headers={"Accept": "application/x-ndjson"},
        )

    @property
    def client(self) -> HttpClient:
        return self._query

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track(
        self,
        *,
        event: str,
        properties: dict[str, Any],
        distinct_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one event via the ``/track`` endpoint.

        Use to log a single user action. ``properties`` must be a non-empty
        dict; ``distinct_id`` identifies the user. Returns ``{"status": 1,
        ...}`` on success.
        """
        if not event or not properties:
            raise ValueError("event and properties are required")
        event_properties: dict[str, Any] = {**properties, "token": self._project_token}
        if distinct_id is not None:
            event_properties["distinct_id"] = distinct_id
        payload: dict[str, Any] = {"event": event, "properties": event_properties}
        data = base64.b64encode(_json.dumps(payload).encode()).decode()
        return cast(
            dict[str, Any],
            self._ingest.post("/track", params={"data": data, "verbose": "1"}).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def import_events(
        self,
        events: list[dict[str, Any]],
        *,
        strict: int = 1,
    ) -> dict[str, Any]:
        """Bulk-import historical events.

        Use for backfill: each entry must have ``event``, ``properties``
        with ``time`` (epoch seconds), and a ``distinct_id``. Returns the
        import receipt.
        """
        if not events:
            raise ValueError("events must be non-empty")
        return cast(
            dict[str, Any],
            self._ingest.post(
                "/import",
                params={"project_id": self._project_id, "strict": strict},
                json=events,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def engage(self, payload: list[dict[str, Any]]) -> dict[str, Any]:
        """Update user profiles via ``/engage``.

        Use to set/update user-level properties. Each entry must include
        ``$token``, ``$distinct_id``, and an operation key like ``$set``.
        """
        if not payload:
            raise ValueError("payload must be non-empty")
        return cast(
            dict[str, Any],
            self._ingest.post(
                "/engage",
                params={"verbose": "1"},
                json=payload,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def group_update(self, payload: list[dict[str, Any]]) -> dict[str, Any]:
        """Update group profiles via ``/groups``.

        Same shape as ``engage`` but for group-analytics records. Each entry
        needs ``$token``, ``$group_key``, ``$group_id`` and an operation
        like ``$set``.
        """
        if not payload:
            raise ValueError("payload must be non-empty")
        return cast(
            dict[str, Any],
            self._ingest.post(
                "/groups",
                params={"verbose": "1"},
                json=payload,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def events_query(
        self,
        *,
        event: list[str],
        type: str = "general",
        unit: str = "day",
        interval: int = 7,
    ) -> dict[str, Any]:
        """Run the ``/events`` count query for one or more event names.

        Best tool for "how many ``<event>`` over the last N days?".
        ``unit`` is ``minute``/``hour``/``day``/``week``/``month``;
        ``interval`` is how many of those units back. Returns the Mixpanel
        ``data`` series payload.
        """
        if not event:
            raise ValueError("event must be non-empty")
        return cast(
            dict[str, Any],
            self._query.get(
                "/api/2.0/events",
                params={
                    "project_id": self._project_id,
                    "event": _json.dumps(event),
                    "type": type,
                    "unit": unit,
                    "interval": interval,
                },
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def segmentation(
        self,
        *,
        event: str,
        from_date: str,
        to_date: str,
        on: str | None = None,
        unit: str = "day",
        type: str = "general",
    ) -> dict[str, Any]:
        """Segment a single event.

        ``from_date``/``to_date`` are ``YYYY-MM-DD``. Pass ``on`` (a
        property expression like ``"properties.region"``) to group results
        by that property. Returns the ``data`` payload.
        """
        if not event or not from_date or not to_date:
            raise ValueError("event, from_date, and to_date are required")
        params: dict[str, Any] = {
            "project_id": self._project_id,
            "event": event,
            "from_date": from_date,
            "to_date": to_date,
            "unit": unit,
            "type": type,
        }
        if on is not None:
            params["on"] = on
        return cast(
            dict[str, Any],
            self._query.get("/api/2.0/segmentation", params=params).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def funnels(
        self,
        *,
        funnel_id: int,
        from_date: str,
        to_date: str,
        unit: str = "day",
    ) -> dict[str, Any]:
        """Return saved-funnel results.

        ``funnel_id`` must be an existing saved funnel in the project.
        Returns the funnel conversion payload.
        """
        if not funnel_id or not from_date or not to_date:
            raise ValueError("funnel_id, from_date, and to_date are required")
        return cast(
            dict[str, Any],
            self._query.get(
                "/api/2.0/funnels",
                params={
                    "project_id": self._project_id,
                    "funnel_id": funnel_id,
                    "from_date": from_date,
                    "to_date": to_date,
                    "unit": unit,
                },
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def retention(
        self,
        *,
        from_date: str,
        to_date: str,
        retention_type: str = "birth",
        born_event: str | None = None,
        event: str | None = None,
        unit: str = "day",
    ) -> dict[str, Any]:
        """Run a retention query.

        Use to measure how often users that did ``born_event`` return to
        do ``event`` over the given date range. ``retention_type`` is
        ``birth`` or ``compounded``.
        """
        if not from_date or not to_date:
            raise ValueError("from_date and to_date are required")
        params: dict[str, Any] = {
            "project_id": self._project_id,
            "from_date": from_date,
            "to_date": to_date,
            "retention_type": retention_type,
            "unit": unit,
        }
        if born_event is not None:
            params["born_event"] = born_event
        if event is not None:
            params["event"] = event
        return cast(
            dict[str, Any],
            self._query.get("/api/2.0/retention", params=params).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def export_events(
        self,
        *,
        from_date: str,
        to_date: str,
        event: list[str] | None = None,
        where: str | None = None,
    ) -> dict[str, Any]:
        """Export raw events as NDJSON.

        Returns ``{"status": <http_status>, "ndjson": <body>}``. Big date
        ranges yield big responses. Use ``where`` for server-side filters
        (e.g. ``"properties.k=='v'"``).
        """
        if not from_date or not to_date:
            raise ValueError("from_date and to_date are required")
        params: dict[str, Any] = {
            "project_id": self._project_id,
            "from_date": from_date,
            "to_date": to_date,
        }
        if event is not None:
            params["event"] = _json.dumps(event)
        if where is not None:
            params["where"] = where
        response = self._export.get("/api/2.0/export", params=params)
        return {"status": response.status, "ndjson": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_jql(self, *, script: str) -> dict[str, Any]:
        """Run a JQL script.

        Best for custom analytics not expressible via segmentation/funnels.
        Returns the script's return value as JSON.
        """
        if not script:
            raise ValueError("script is required")
        return cast(
            dict[str, Any],
            self._query.post(
                "/api/2.0/jql",
                params={"project_id": self._project_id},
                data=("script=" + script).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ).json(),
        )
