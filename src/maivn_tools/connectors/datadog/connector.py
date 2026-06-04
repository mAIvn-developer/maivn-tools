"""Datadog API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Auth strategy


class _DatadogAuth(AuthStrategy):
    """Auth strategy that sets DD-API-KEY and DD-APPLICATION-KEY headers."""

    mode = AuthMode.API_KEY

    def __init__(self, api_key: str, app_key: str | None) -> None:
        self._api_key = api_key
        self._app_key = app_key

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers["DD-API-KEY"] = self._api_key
        if self._app_key:
            headers["DD-APPLICATION-KEY"] = self._app_key
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "headers": ["DD-API-KEY", "DD-APPLICATION-KEY"],
        }


# MARK: Coercion helpers


def _coerce_v2_points(points: Any) -> Any:
    """Coerce v1-style ``[[timestamp, value], ...]`` points to the v2 shape.

    The Metrics v2 ``/api/v2/series`` schema requires each point to be an
    object ``{"timestamp": <int seconds>, "value": <number>}``. Points already
    in object form (or any non-list value) are returned unchanged.
    """
    if not isinstance(points, list):
        return points
    points_list = cast("list[Any]", points)
    coerced: list[Any] = []
    for point in points_list:
        if isinstance(point, (list, tuple)):
            seq = cast("list[Any] | tuple[Any, ...]", point)
            if len(seq) == 2:
                timestamp, value = seq
                coerced.append({"timestamp": int(timestamp), "value": value})
                continue
        coerced.append(point)
    return coerced


def _coerce_monitor_id(candidate: Any) -> int:
    """Accept an int, a dict from list/get_monitor, or a list of such."""
    if isinstance(candidate, bool):
        raise ValueError("monitor_id must be a non-zero int (or a monitor dict)")
    if isinstance(candidate, int):
        if not candidate:
            raise ValueError("monitor_id is required")
        return candidate
    if isinstance(candidate, str) and candidate.isdigit():
        value = int(candidate)
        if not value:
            raise ValueError("monitor_id is required")
        return value
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("monitor_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value:
                return value
            if isinstance(value, str) and value.isdigit() and int(value):
                return int(value)
    if isinstance(candidate, list) and candidate:
        candidate_list = cast("list[Any]", candidate)
        return _coerce_monitor_id(candidate_list[0])
    raise ValueError("monitor_id must be a non-zero int (or a monitor dict from list/get_monitor)")


# MARK: Tool set


@toolset(prefix="datadog")
class DatadogToolSet:
    """A connector for the Datadog REST API.

    Args:
        api_key: ``DD-API-KEY``.
        app_key: ``DD-APPLICATION-KEY``. Required for most read APIs.
        site: Datadog site (e.g. ``"datadoghq.com"``, ``"datadoghq.eu"``).
    """

    metadata = ProviderMetadata(
        name="datadog",
        display_name="Datadog",
        version="0.1.0",
        description="Logs, metrics, monitors, events, and dashboards.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.datadoghq.com/api/latest/",
        homepage_url="https://www.datadoghq.com/",
        tags=("observability", "monitoring"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        app_key: str | None = None,
        site: str = "datadoghq.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        # Log ingestion lives on a separate intake host from the rest of the
        # API surface (search/metrics/monitors/events/dashboards on api.{site}).
        self._logs_intake_url = f"https://http-intake.logs.{site}/api/v2/logs"
        self._client = HttpClient(
            base_url=f"https://api.{site}",
            auth=_DatadogAuth(api_key, app_key),
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
    def search_logs(
        self,
        *,
        query: str,
        from_time: str,
        to_time: str,
        limit: int = 25,
        cursor: str | None = None,
        indexes: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search Logs (Logs Search API v2).

        Best first tool for log triage. Returns compact summaries by default:
        each entry has ``log_ref`` (``log_1``, ``log_2``, ...), ``timestamp``,
        ``service``, ``status`` (severity), ``host``, and ``message``. The
        raw Datadog event IDs are internal handles, omitted by default; set
        ``include_ids=True`` only if a downstream tool needs them. Set
        ``include_metadata=False`` to return the raw provider payload.
        """
        if not query or not from_time or not to_time:
            raise ValueError("query, from_time, and to_time are required")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        body: dict[str, Any] = {
            "filter": {"query": query, "from": from_time, "to": to_time},
            "page": {"limit": limit},
        }
        if cursor is not None:
            body["page"]["cursor"] = cursor
        if indexes is not None:
            body["filter"]["indexes"] = indexes
        payload: dict[str, Any] = self._client.post("/api/v2/logs/events/search", json=body).json()
        if not include_metadata:
            return payload
        events: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            event_dict = cast("dict[str, Any]", event)
            attrs_value: Any = event_dict.get("attributes")
            attrs: dict[str, Any] = (
                cast("dict[str, Any]", attrs_value) if isinstance(attrs_value, dict) else {}
            )
            inner_value: Any = attrs.get("attributes")
            inner: dict[str, Any] = (
                cast("dict[str, Any]", inner_value) if isinstance(inner_value, dict) else {}
            )
            summary: dict[str, Any] = {
                "log_ref": f"log_{index}",
                "timestamp": attrs.get("timestamp", ""),
                "service": attrs.get("service", ""),
                "status": attrs.get("status", ""),
                "host": attrs.get("host", ""),
                "message": attrs.get("message", inner.get("message", "")),
            }
            tags = attrs.get("tags")
            if tags:
                summary["tags"] = tags
            if include_ids:
                summary["log_id"] = event_dict.get("id", "")
            summaries.append(summary)
        meta_value: Any = payload.get("meta")
        meta: dict[str, Any] = (
            cast("dict[str, Any]", meta_value) if isinstance(meta_value, dict) else {}
        )
        page_value: Any = meta.get("page")
        page: dict[str, Any] = (
            cast("dict[str, Any]", page_value) if isinstance(page_value, dict) else {}
        )
        return {
            "logs": summaries,
            "next_cursor": page.get("after"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_logs(
        self,
        logs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Submit logs to the ingestion pipeline.

        Returns the ingest acknowledgement. Use for forwarding agent-side
        log records into Datadog. Log intake is served by the dedicated
        ``http-intake.logs.{site}`` host, not the main ``api.{site}`` host.
        """
        if not logs:
            raise ValueError("logs must be non-empty")
        return self._client.post(self._logs_intake_url, json=logs).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_metrics(
        self,
        *,
        from_time: int,
        to_time: int,
        query: str,
    ) -> dict[str, Any]:
        """Query timeseries (v1 metrics).

        Returns the raw Datadog metrics response. ``from_time`` and
        ``to_time`` are Unix epoch seconds; ``query`` uses the Datadog query
        DSL (e.g. ``avg:system.cpu.user{*}``).
        """
        if not query or not from_time or not to_time:
            raise ValueError("query, from_time, and to_time are required")
        return self._client.get(
            "/api/v1/query",
            params={"from": from_time, "to": to_time, "query": query},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_metrics(self, series: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit metric points (Metrics API v2).

        Returns the ingest acknowledgement. Each ``series`` entry must
        include ``metric`` and ``points``. The v2 ``/api/v2/series`` schema
        requires ``points`` to be a list of objects
        ``[{"timestamp": <int seconds>, "value": <number>}, ...]`` rather than
        the v1 ``[[timestamp, value], ...]`` array-pair shape. Legacy v1-style
        pairs supplied here are coerced into the v2 object form before posting.
        """
        if not series:
            raise ValueError("series must be non-empty")
        coerced: list[dict[str, Any]] = []
        for entry in series:
            entry_obj: Any = entry
            if isinstance(entry_obj, dict) and "points" in entry_obj:
                entry_dict = cast("dict[str, Any]", entry_obj)
                entry = {**entry_dict, "points": _coerce_v2_points(entry_dict["points"])}
            coerced.append(entry)
        return self._client.post("/api/v2/series", json={"series": coerced}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_monitors(
        self,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        page: int = 0,
        page_size: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List monitors.

        Best first tool for monitor overviews. Returns compact summaries
        with ``monitor_ref`` (``monitor_1``, ...), ``name``, ``type``,
        ``state`` (alert/warn/ok/no_data), ``message``, and ``tags``.
        Numeric monitor IDs are omitted by default; set ``include_ids=True``
        when a follow-up tool (``get_monitor``, ``delete_monitor``,
        ``mute_monitor``) needs them.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if include_metadata:
            page_size = min(page_size, _SUMMARY_MAX)
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if name is not None:
            params["name"] = name
        if tags is not None:
            params["tags"] = ",".join(tags)
        payload: Any = self._client.get("/api/v1/monitor", params=params).json()
        if not include_metadata:
            return cast("dict[str, Any]", payload)
        items: list[Any] = (
            cast("list[Any]", payload)
            if isinstance(payload, list)
            else (payload.get("monitors") or [])
        )
        summaries: list[dict[str, Any]] = []
        for index, monitor in enumerate(items, start=1):
            if not isinstance(monitor, dict):
                continue
            monitor_dict = cast("dict[str, Any]", monitor)
            summary: dict[str, Any] = {
                "monitor_ref": f"monitor_{index}",
                "name": monitor_dict.get("name", ""),
                "type": monitor_dict.get("type", ""),
                "state": (monitor_dict.get("overall_state") or monitor_dict.get("state", "")),
                "message": monitor_dict.get("message", ""),
                "tags": monitor_dict.get("tags", []),
            }
            if include_ids:
                summary["monitor_id"] = monitor_dict.get("id")
            summaries.append(summary)
        return {"monitors": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_monitor(self, monitor_id: Any) -> dict[str, Any]:
        """Return a single monitor.

        ``monitor_id`` accepts an integer ID, a monitor dict returned by
        ``list_monitors(include_ids=True)``, or a list of such (the first
        valid candidate is used).
        """
        mid = _coerce_monitor_id(monitor_id)
        return self._client.get(f"/api/v1/monitor/{mid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_monitor(
        self,
        *,
        type: str,
        query: str,
        name: str,
        message: str,
        tags: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a monitor.

        Returns the new monitor resource (including its numeric ID). Use
        ``list_monitors`` first to verify the monitor does not already
        exist with the same name.
        """
        if not type or not query or not name or not message:
            raise ValueError("type, query, name, and message are required")
        body: dict[str, Any] = {
            "type": type,
            "query": query,
            "name": name,
            "message": message,
        }
        if tags is not None:
            body["tags"] = tags
        if options is not None:
            body["options"] = options
        return self._client.post("/api/v1/monitor", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_monitor(self, monitor_id: Any) -> dict[str, Any]:
        """Delete a monitor.

        Destructive — confirm with the user before calling. ``monitor_id``
        accepts an int, a monitor dict, or a list of monitor dicts.
        """
        mid = _coerce_monitor_id(monitor_id)
        return self._client.delete(f"/api/v1/monitor/{mid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mute_monitor(
        self,
        monitor_id: Any,
        *,
        scope: str | None = None,
        end: int | None = None,
    ) -> dict[str, Any]:
        """Mute a monitor (silence notifications).

        ``monitor_id`` accepts an int or a monitor dict. ``end`` is an
        optional Unix-epoch second when the mute should auto-lift.
        """
        mid = _coerce_monitor_id(monitor_id)
        body: dict[str, Any] = {}
        if scope is not None:
            body["scope"] = scope
        if end is not None:
            body["end"] = end
        return self._client.post(f"/api/v1/monitor/{mid}/mute", json=body or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def post_event(
        self,
        *,
        title: str,
        text: str,
        priority: str | None = None,
        tags: list[str] | None = None,
        alert_type: str | None = None,
    ) -> dict[str, Any]:
        """Post an event to the event stream.

        Returns the created event resource. Useful for annotating deploys,
        config changes, or any agent-driven action. Uses the v1
        ``/api/v1/events`` endpoint, which remains the supported path for all
        event categories; the v2 events API is GA only for change/alert
        categories.
        """
        if not title or not text:
            raise ValueError("title and text are required")
        body: dict[str, Any] = {"title": title, "text": text}
        if priority is not None:
            body["priority"] = priority
        if tags is not None:
            body["tags"] = tags
        if alert_type is not None:
            body["alert_type"] = alert_type
        return self._client.post("/api/v1/events", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_dashboards(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List dashboards.

        Returns compact summaries by default: ``dashboard_ref``, ``title``,
        ``description``, ``layout_type``, and ``url``. Dashboard IDs are
        opaque strings; they are omitted by default and only needed for
        ``get_dashboard``. Set ``include_ids=True`` when a follow-up tool
        needs the ID.
        """
        payload: dict[str, Any] = self._client.get("/api/v1/dashboard").json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("dashboards") or []
        summaries: list[dict[str, Any]] = []
        for index, dashboard in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(dashboard, dict):
                continue
            dashboard_dict = cast("dict[str, Any]", dashboard)
            summary: dict[str, Any] = {
                "dashboard_ref": f"dashboard_{index}",
                "title": dashboard_dict.get("title", ""),
                "description": dashboard_dict.get("description", ""),
                "layout_type": dashboard_dict.get("layout_type", ""),
                "url": dashboard_dict.get("url", ""),
            }
            if include_ids:
                summary["dashboard_id"] = dashboard_dict.get("id", "")
            summaries.append(summary)
        return {"dashboards": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        """Return one dashboard's definition.

        Returns the full dashboard resource (widgets, layout, tags, etc.).
        Use ``list_dashboards(include_ids=True)`` to discover dashboard
        IDs.
        """
        if not dashboard_id:
            raise ValueError("dashboard_id is required")
        return self._client.get(f"/api/v1/dashboard/{dashboard_id}").json()
