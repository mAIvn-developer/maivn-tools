"""PostHog REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# PostHog Cloud uses region-specific, split hosts: the private management API
# lives on ``{region}.posthog.com`` and event ingestion on the public
# ``{region}.i.posthog.com`` host. ``app.posthog.com`` is the legacy host.
_DEFAULT_MANAGEMENT_HOST = "us.posthog.com"
# Maps a cloud management host to its paired ingestion host.
_INGESTION_HOST_BY_MANAGEMENT: dict[str, str] = {
    "us.posthog.com": "us.i.posthog.com",
    "eu.posthog.com": "eu.i.posthog.com",
    # Legacy host still redirects; pair it with the legacy ingestion host.
    "app.posthog.com": "app.i.posthog.com",
}
# Current single-event ingestion path (``/capture/`` is a legacy alias).
_CAPTURE_PATH = "/i/v0/e/"


@toolset(prefix="posthog")
class PostHogToolSet:
    """A connector for PostHog.

    Args:
        personal_api_key: Personal API key (for the management API).
        project_api_key: Project-scoped public key (for event capture).
        project_id: Numeric project ID.
        host: PostHog management host (default ``"us.posthog.com"``;
            EU Cloud: ``"eu.posthog.com"``; self-hosted: e.g.
            ``"posthog.example.com"``). The matching ingestion host is
            derived automatically for cloud regions; for self-hosted
            instances the same host is used for both.
    """

    metadata = ProviderMetadata(
        name="posthog",
        display_name="PostHog",
        version="0.1.0",
        description="Event capture, insights, feature flags, persons, and cohorts.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://posthog.com/docs/api",
        homepage_url="https://posthog.com/",
        tags=("analytics", "product"),
    )

    def __init__(
        self,
        *,
        personal_api_key: str,
        project_api_key: str | None = None,
        project_id: int,
        host: str = _DEFAULT_MANAGEMENT_HOST,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not personal_api_key or not project_id:
            raise ValueError("personal_api_key and project_id are required")
        self.connection = connection
        self._project_id = project_id
        self._project_api_key = project_api_key
        # Ingestion goes to the paired public host for cloud regions; for
        # self-hosted instances the same host serves both surfaces.
        ingestion_host = _INGESTION_HOST_BY_MANAGEMENT.get(host, host)
        self._ingestion_base_url = f"https://{ingestion_host}"
        self._client = HttpClient(
            base_url=f"https://{host}",
            auth=BearerTokenAuth(personal_api_key),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _event_summary(
        event: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_person: Any = event.get("person")
        person: dict[str, Any] = (
            cast("dict[str, Any]", raw_person) if isinstance(raw_person, dict) else {}
        )
        summary: dict[str, Any] = {
            "event_ref": f"event_{index}",
            "event": event.get("event", ""),
            "distinct_id": event.get("distinct_id", ""),
            "timestamp": event.get("timestamp", ""),
            "person_name": person.get("name", ""),
        }
        if include_ids:
            summary["event_id"] = event.get("id", "")
        return summary

    @staticmethod
    def _insight_summary(
        insight: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_created_by: Any = insight.get("created_by")
        created_by: dict[str, Any] = (
            cast("dict[str, Any]", raw_created_by) if isinstance(raw_created_by, dict) else {}
        )
        summary: dict[str, Any] = {
            "insight_ref": f"insight_{index}",
            "name": insight.get("name", "") or insight.get("derived_name", ""),
            "description": insight.get("description", ""),
            "created_by": created_by.get("email", ""),
            "updated_at": insight.get("updated_at", ""),
        }
        if include_ids:
            summary["insight_id"] = insight.get("id", "")
            summary["short_id"] = insight.get("short_id", "")
        return summary

    @staticmethod
    def _person_summary(
        person: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_properties: Any = person.get("properties")
        properties: dict[str, Any] = (
            cast("dict[str, Any]", raw_properties) if isinstance(raw_properties, dict) else {}
        )
        raw_distinct_ids: Any = person.get("distinct_ids", [])
        distinct_ids: list[Any] = (
            cast("list[Any]", raw_distinct_ids) if isinstance(raw_distinct_ids, list) else []
        )
        summary: dict[str, Any] = {
            "person_ref": f"person_{index}",
            "name": properties.get("name", "") or properties.get("email", ""),
            "email": properties.get("email", ""),
            "distinct_id": distinct_ids[0] if distinct_ids else "",
            "created_at": person.get("created_at", ""),
        }
        if include_ids:
            summary["person_id"] = person.get("id", "")
            summary["distinct_ids"] = distinct_ids
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def capture(
        self,
        *,
        event: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Send one event via the ingestion API (``/i/v0/e/``).

        Use to log a single analytics event for a user identified by
        ``distinct_id``. Requires ``project_api_key`` to be set on the
        connector. Posts to the public ingestion host
        (e.g. ``us.i.posthog.com``). Returns ``{"status": 1}`` on success.
        """
        if not event or not distinct_id:
            raise ValueError("event and distinct_id are required")
        if not self._project_api_key:
            raise ValueError("project_api_key must be set to capture events")
        body: dict[str, Any] = {
            "api_key": self._project_api_key,
            "event": event,
            "distinct_id": distinct_id,
        }
        if properties is not None:
            body["properties"] = properties
        if timestamp is not None:
            body["timestamp"] = timestamp
        return self._client.post(f"{self._ingestion_base_url}{_CAPTURE_PATH}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_events(
        self,
        *,
        after: str | None = None,
        before: str | None = None,
        distinct_id: str | None = None,
        event: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recent events in the project.

        Best first tool for event triage. Returns compact summaries with
        ``event_ref`` (``event_1``, ``event_2``, ...), event name, distinct
        ID, timestamp, and person name (when present). Raw PostHog event
        IDs are omitted unless ``include_ids=True`` — they are internal
        handles. Pagination tokens (``next``) are preserved.
        """
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        if distinct_id is not None:
            params["distinct_id"] = distinct_id
        if event is not None:
            params["event"] = event
        payload = cast(
            "dict[str, Any]",
            self._client.get(
                f"/api/projects/{self._project_id}/events/",
                params=params,
            ).json(),
        )
        results: Any = payload.get("results")
        if not isinstance(results, list):
            return payload
        results_list = cast("list[Any]", results)
        summaries = [
            self._event_summary(cast("dict[str, Any]", item), index=index, include_ids=include_ids)
            for index, item in enumerate(results_list, start=1)
            if isinstance(item, dict)
        ]
        return {
            "events": summaries,
            "next": payload.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_insights(
        self,
        *,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List saved insights.

        Returns compact summaries with ``insight_ref``, name, description,
        creator email, and ``updated_at``. Raw PostHog insight IDs are
        omitted unless ``include_ids=True``; set it only when a follow-up
        ``get_insight`` call needs the raw ID.
        """
        payload = cast(
            "dict[str, Any]",
            self._client.get(
                f"/api/projects/{self._project_id}/insights/",
                params={"limit": limit},
            ).json(),
        )
        results: Any = payload.get("results")
        if not isinstance(results, list):
            return payload
        results_list = cast("list[Any]", results)
        summaries = [
            self._insight_summary(
                cast("dict[str, Any]", item), index=index, include_ids=include_ids
            )
            for index, item in enumerate(results_list, start=1)
            if isinstance(item, dict)
        ]
        return {
            "insights": summaries,
            "next": payload.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_insight(self, insight_id: int) -> dict[str, Any]:
        """Return one insight by ID.

        ``insight_id`` is the raw PostHog insight ID returned by
        ``list_insights(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers.
        """
        if not insight_id:
            raise ValueError("insight_id is required")
        return self._client.get(f"/api/projects/{self._project_id}/insights/{insight_id}/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_hogql(self, *, query: str) -> dict[str, Any]:
        """Run an ad-hoc HogQL query.

        Best for "give me ``X`` aggregated by ``Y``" questions that don't
        match a saved insight. Returns ``{"results": [...], ...}``.
        """
        if not query:
            raise ValueError("query is required")
        return self._client.post(
            f"/api/projects/{self._project_id}/query/",
            json={"query": {"kind": "HogQLQuery", "query": query}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_feature_flags(self) -> dict[str, Any]:
        """List feature flags in the project.

        Returns the PostHog feature-flag list payload. Use
        ``create_feature_flag``/``update_feature_flag`` to mutate.
        """
        return self._client.get(f"/api/projects/{self._project_id}/feature_flags/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_feature_flag(
        self,
        *,
        key: str,
        name: str | None = None,
        filters: dict[str, Any] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        """Create a feature flag.

        ``key`` is the public flag identifier code reads. Returns the
        created flag resource.
        """
        if not key:
            raise ValueError("key is required")
        body: dict[str, Any] = {"key": key, "active": active}
        if name is not None:
            body["name"] = name
        if filters is not None:
            body["filters"] = filters
        return self._client.post(
            f"/api/projects/{self._project_id}/feature_flags/", json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_feature_flag(
        self,
        flag_id: int,
        *,
        active: bool | None = None,
        filters: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Patch a feature flag.

        Provide ``flag_id`` (numeric) and any of ``active``/``filters``/
        ``name`` to update. Returns the updated flag resource.
        """
        if not flag_id:
            raise ValueError("flag_id is required")
        body: dict[str, Any] = {}
        if active is not None:
            body["active"] = active
        if filters is not None:
            body["filters"] = filters
        if name is not None:
            body["name"] = name
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.patch(
            f"/api/projects/{self._project_id}/feature_flags/{flag_id}/",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_persons(
        self,
        *,
        search: str | None = None,
        distinct_id: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List persons in the project.

        Returns compact summaries with ``person_ref``, name, email,
        primary ``distinct_id``, and ``created_at``. Raw PostHog person
        IDs are omitted unless ``include_ids=True``.
        """
        params: dict[str, Any] = {"limit": limit}
        if search is not None:
            params["search"] = search
        if distinct_id is not None:
            params["distinct_id"] = distinct_id
        payload = cast(
            "dict[str, Any]",
            self._client.get(
                f"/api/projects/{self._project_id}/persons/",
                params=params,
            ).json(),
        )
        results: Any = payload.get("results")
        if not isinstance(results, list):
            return payload
        results_list = cast("list[Any]", results)
        summaries = [
            self._person_summary(cast("dict[str, Any]", item), index=index, include_ids=include_ids)
            for index, item in enumerate(results_list, start=1)
            if isinstance(item, dict)
        ]
        return {
            "persons": summaries,
            "next": payload.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_cohorts(self) -> dict[str, Any]:
        """List cohorts in the project.

        Returns the PostHog cohort list payload.
        """
        return self._client.get(f"/api/projects/{self._project_id}/cohorts/").json()
