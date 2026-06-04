"""Segment Tracking + Public API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="segment")
class SegmentToolSet:
    """A connector for Segment's Tracking + Public APIs.

    Args:
        write_key: Source write key for the Tracking API.
        public_api_token: Personal access token for the Public API
            (sources / destinations / warehouses management).
    """

    metadata = ProviderMetadata(
        name="segment",
        display_name="Segment",
        version="0.1.0",
        description="Track / identify / page / group + sources, destinations, and warehouses.",
        auth_modes=(AuthMode.BASIC, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://segment.com/docs/connections/",
        homepage_url="https://segment.com/",
        tags=("analytics", "cdp"),
    )

    def __init__(
        self,
        *,
        write_key: str | None = None,
        public_api_token: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not write_key and not public_api_token:
            raise ValueError("at least one of write_key or public_api_token is required")
        self.connection = connection
        self._tracking: HttpClient | None = None
        self._public: HttpClient | None = None
        if write_key:
            self._tracking = HttpClient(
                base_url="https://api.segment.io",
                auth=BasicAuth(write_key, ""),
                transport=transport,
                default_headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        if public_api_token:
            self._public = HttpClient(
                base_url="https://api.segmentapis.com",
                auth=BearerTokenAuth(public_api_token),
                transport=transport,
                default_headers={
                    "Accept": "application/vnd.segment.v1+json",
                    "Content-Type": "application/vnd.segment.v1+json",
                },
            )

    @property
    def client(self) -> HttpClient:
        client = self._public or self._tracking
        if client is None:
            raise ValueError("no client configured (provide write_key or public_api_token)")
        return client

    def _require_tracking(self) -> HttpClient:
        if self._tracking is None:
            raise ValueError("write_key must be set in the constructor")
        return self._tracking

    def _require_public(self) -> HttpClient:
        if self._public is None:
            raise ValueError("public_api_token must be set in the constructor")
        return self._public

    # MARK: - Internal helpers

    @staticmethod
    def _entity_summary(
        entity: dict[str, Any],
        *,
        ref_prefix: str,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
            "name": entity.get("name", "") or entity.get("displayName", ""),
            "slug": entity.get("slug", ""),
            "enabled": entity.get("enabled", entity.get("isActive", True)),
        }
        metadata = entity.get("metadata")
        if isinstance(metadata, dict):
            metadata_dict = cast("dict[str, Any]", metadata)
            summary["category"] = metadata_dict.get("slug", "") or metadata_dict.get("name", "")
        if include_ids:
            summary[f"{ref_prefix}_id"] = entity.get("id", "")
        return summary

    @staticmethod
    def _payload_data(payload: object) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        data: object = cast("dict[str, Any]", payload).get("data")
        if not isinstance(data, dict):
            return None
        return cast("dict[str, Any]", data)

    @staticmethod
    def _next_cursor(data: dict[str, Any] | None) -> Any:
        if data is None:
            return None
        pagination: object = data.get("pagination", {}) or {}
        if not isinstance(pagination, dict):
            return None
        return cast("dict[str, Any]", pagination).get("next")

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track(
        self,
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
        event: str,
        properties: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a ``track`` event.

        At least one of ``user_id``/``anonymous_id`` must be provided.
        ``event`` is the action name (e.g. ``"Signed Up"``). Returns
        ``{"success": True}`` on accepted ingest.
        """
        if not user_id and not anonymous_id:
            raise ValueError("user_id or anonymous_id is required")
        if not event:
            raise ValueError("event is required")
        body: dict[str, Any] = {"event": event}
        if user_id is not None:
            body["userId"] = user_id
        if anonymous_id is not None:
            body["anonymousId"] = anonymous_id
        if properties is not None:
            body["properties"] = properties
        if context is not None:
            body["context"] = context
        return self._require_tracking().post("/v1/track", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def identify(
        self,
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
        traits: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an ``identify`` call.

        Use to set/update traits on a user (email, name, plan, etc.). At
        least one of ``user_id``/``anonymous_id`` is required.
        """
        if not user_id and not anonymous_id:
            raise ValueError("user_id or anonymous_id is required")
        body: dict[str, Any] = {}
        if user_id is not None:
            body["userId"] = user_id
        if anonymous_id is not None:
            body["anonymousId"] = anonymous_id
        if traits is not None:
            body["traits"] = traits
        if context is not None:
            body["context"] = context
        return self._require_tracking().post("/v1/identify", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def group(
        self,
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
        group_id: str,
        traits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a ``group`` call to associate a user with a group/org.

        Use for B2B "user belongs to company X" mappings. At least one of
        ``user_id``/``anonymous_id`` must be provided.
        """
        if not group_id:
            raise ValueError("group_id is required")
        if not user_id and not anonymous_id:
            raise ValueError("user_id or anonymous_id is required")
        body: dict[str, Any] = {"groupId": group_id}
        if user_id is not None:
            body["userId"] = user_id
        if anonymous_id is not None:
            body["anonymousId"] = anonymous_id
        if traits is not None:
            body["traits"] = traits
        return self._require_tracking().post("/v1/group", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def page(
        self,
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
        name: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a ``page`` call for a web pageview.

        At least one of ``user_id``/``anonymous_id`` must be provided.
        """
        if not user_id and not anonymous_id:
            raise ValueError("user_id or anonymous_id is required")
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if user_id is not None:
            body["userId"] = user_id
        if anonymous_id is not None:
            body["anonymousId"] = anonymous_id
        if properties is not None:
            body["properties"] = properties
        return self._require_tracking().post("/v1/page", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch(
        self,
        *,
        batch: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a batched payload (up to 500 KB).

        Each item in ``batch`` must include ``type`` (``track``/``identify``
        /etc.) and the matching shape for that call.
        """
        if not batch:
            raise ValueError("batch must be non-empty")
        body: dict[str, Any] = {"batch": batch}
        if context is not None:
            body["context"] = context
        return self._require_tracking().post("/v1/batch", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_workspace(self) -> dict[str, Any]:
        """Return the workspace bound to the Public API token.

        The Segment Public API token maps to exactly one workspace; this
        returns that single Workspace wrapped under ``data.workspace``.
        """
        return self._require_public().get("/workspace").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sources(
        self,
        *,
        page_size: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List sources in the workspace.

        Best first tool for source discovery. Returns compact summaries
        with ``source_ref`` (``source_1``, ``source_2``, ...), the source
        name, slug, category, and enabled state. Raw Segment source IDs
        are omitted unless ``include_ids=True``; set it only when a
        follow-up tool needs the raw ID. ``cursor`` paginates.
        """
        params: dict[str, Any] = {"pagination.count": page_size}
        if cursor is not None:
            params["pagination.cursor"] = cursor
        payload: object = self._require_public().get("/sources", params=params).json()
        data = self._payload_data(payload)
        raw_sources: object = data.get("sources", []) if data is not None else []
        if not isinstance(raw_sources, list):
            return cast("dict[str, Any]", payload)
        sources_list = cast("list[object]", raw_sources)
        summaries: list[dict[str, Any]] = [
            self._entity_summary(
                cast("dict[str, Any]", source),
                ref_prefix="source",
                index=index,
                include_ids=include_ids,
            )
            for index, source in enumerate(sources_list, start=1)
            if isinstance(source, dict)
        ]
        next_cursor = self._next_cursor(data)
        return {
            "sources": summaries,
            "nextCursor": next_cursor,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_source(self, source_id: str) -> dict[str, Any]:
        """Return one source by ID.

        ``source_id`` is the raw Segment source ID returned by
        ``list_sources(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers.
        """
        if not source_id:
            raise ValueError("source_id is required")
        return self._require_public().get(f"/sources/{source_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_destinations(
        self,
        *,
        page_size: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List destinations in the workspace.

        Returns compact summaries with ``destination_ref``, name, slug,
        and enabled state. Raw destination IDs are omitted unless
        ``include_ids=True``.
        """
        params: dict[str, Any] = {"pagination.count": page_size}
        if cursor is not None:
            params["pagination.cursor"] = cursor
        payload: object = self._require_public().get("/destinations", params=params).json()
        data = self._payload_data(payload)
        raw_destinations: object = data.get("destinations", []) if data is not None else []
        if not isinstance(raw_destinations, list):
            return cast("dict[str, Any]", payload)
        destinations_list = cast("list[object]", raw_destinations)
        summaries: list[dict[str, Any]] = [
            self._entity_summary(
                cast("dict[str, Any]", destination),
                ref_prefix="destination",
                index=index,
                include_ids=include_ids,
            )
            for index, destination in enumerate(destinations_list, start=1)
            if isinstance(destination, dict)
        ]
        next_cursor = self._next_cursor(data)
        return {
            "destinations": summaries,
            "nextCursor": next_cursor,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_warehouses(
        self,
        *,
        page_size: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List data warehouses configured in the workspace.

        Returns compact summaries with ``warehouse_ref``, name, slug, and
        enabled state. Raw warehouse IDs are omitted unless
        ``include_ids=True``.
        """
        params: dict[str, Any] = {"pagination.count": page_size}
        if cursor is not None:
            params["pagination.cursor"] = cursor
        payload: object = self._require_public().get("/warehouses", params=params).json()
        data = self._payload_data(payload)
        raw_warehouses: object = data.get("warehouses", []) if data is not None else []
        if not isinstance(raw_warehouses, list):
            return cast("dict[str, Any]", payload)
        warehouses_list = cast("list[object]", raw_warehouses)
        summaries: list[dict[str, Any]] = [
            self._entity_summary(
                cast("dict[str, Any]", warehouse),
                ref_prefix="warehouse",
                index=index,
                include_ids=include_ids,
            )
            for index, warehouse in enumerate(warehouses_list, start=1)
            if isinstance(warehouse, dict)
        ]
        next_cursor = self._next_cursor(data)
        return {
            "warehouses": summaries,
            "nextCursor": next_cursor,
        }
