"""Looker API 4.0 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_DASHBOARDS_OUTPUT,
    LIST_LOOKS_OUTPUT,
    LIST_USERS_OUTPUT,
)


@toolset(prefix="looker")
class LookerToolSet:
    """A connector for the Looker API 4.0.

    Args:
        base_url: Looker host URL (e.g.
            ``"https://acme.cloud.looker.com:19999"``). Looker's API runs
            on port ``19999`` on Looker-hosted instances; self-hosted
            customers may use the standard 443.
        access_token: Access token obtained from ``POST /login`` against
            the Looker host. It is sent as ``Authorization: token
            <access_token>`` (Looker uses the literal ``token`` scheme, not
            ``Bearer``). The connector does not perform the login handshake
            itself so that token rotation stays with the caller.
    """

    metadata = ProviderMetadata(
        name="looker",
        display_name="Looker",
        version="0.1.0",
        description="Looks, dashboards, queries, users, and content.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://cloud.google.com/looker/docs/api-and-integration",
        homepage_url="https://looker.com/",
        tags=("bi", "analytics"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url or not access_token:
            raise ValueError("base_url and access_token are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token, scheme="token"),
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
    def _look_summary(
        look: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "look_ref": f"look_{index}",
            "title": look.get("title", ""),
            "description": look.get("description", "") or "",
            "view_count": look.get("view_count", 0),
            "updated_at": look.get("updated_at", ""),
        }
        if include_ids:
            summary["look_id"] = look.get("id", "")
        return summary

    @staticmethod
    def _dashboard_summary(
        dashboard: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "dashboard_ref": f"dashboard_{index}",
            "title": dashboard.get("title", ""),
            "description": dashboard.get("description", "") or "",
            "view_count": dashboard.get("view_count", 0),
            "updated_at": dashboard.get("updated_at", ""),
        }
        if include_ids:
            summary["dashboard_id"] = dashboard.get("id", "")
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
            "name": user.get("display_name", "") or user.get("first_name", ""),
            "email": user.get("email", ""),
            "is_disabled": user.get("is_disabled", False),
        }
        if include_ids:
            summary["user_id"] = user.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def me(self) -> dict[str, Any]:
        """Return the authenticated Looker user.

        Use once at startup to confirm the token works.
        """
        return self._client.get("/api/4.0/user").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_LOOKS_OUTPUT)
    def list_looks(
        self,
        *,
        fields: str | None = None,
        limit: int = 25,
        offset: int | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Looks (saved single-tile reports).

        Best first tool for Look discovery. Returns compact summaries with
        ``look_ref``, title, description, view count, and ``updated_at``.
        Raw Looker IDs are omitted unless ``include_ids=True`` — they are
        internal handles. Set ``fields`` to a comma string to control
        which raw fields Looker returns when summary mode is bypassed.
        Pagination uses ``limit``/``offset`` (Looker's supported scheme;
        ``page``/``per_page`` are deprecated).
        """
        params: dict[str, Any] = {"limit": limit}
        if fields is not None:
            params["fields"] = fields
        if offset is not None:
            params["offset"] = offset
        payload: Any = self._client.get("/api/4.0/looks", params=params).json()
        if not isinstance(payload, list):
            return cast(dict[str, Any], payload)
        items = cast(list[Any], payload)
        summaries = [
            self._look_summary(cast(dict[str, Any], look), index=index, include_ids=include_ids)
            for index, look in enumerate(items, start=1)
            if isinstance(look, dict)
        ]
        return {"looks": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_look(
        self,
        look_id: int,
        *,
        fields: str | None = None,
    ) -> dict[str, Any]:
        """Return one Look by ID.

        ``look_id`` is the raw Looker Look ID returned by
        ``list_looks(include_ids=True)``. The ID is an internal handle and
        should not appear in final answers.
        """
        if not look_id:
            raise ValueError("look_id is required")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = fields
        return self._client.get(f"/api/4.0/looks/{look_id}", params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_look(
        self,
        look_id: int,
        *,
        result_format: str = "json",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Run a Look and return its data.

        ``result_format`` is one of ``json``/``json_detail``/``csv``/
        ``txt``/``html``/``md``/``xlsx``/``sql``/``png``/``jpg``. Use
        ``json`` for normal data work. Returns either the parsed JSON or
        a ``{"status", "body"}`` dict for non-JSON formats.
        """
        if not look_id:
            raise ValueError("look_id is required")
        if result_format not in {
            "json",
            "json_detail",
            "csv",
            "txt",
            "html",
            "md",
            "xlsx",
            "sql",
            "png",
            "jpg",
        }:
            raise ValueError("invalid result_format")
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        response = self._client.get(
            f"/api/4.0/looks/{look_id}/run/{result_format}",
            params=params or None,
        )
        try:
            return response.json()
        except ValueError:
            return {"status": response.status, "body": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_DASHBOARDS_OUTPUT)
    def list_dashboards(
        self,
        *,
        fields: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List dashboards in the Looker instance.

        Best first tool for dashboard discovery. Returns compact summaries
        with ``dashboard_ref``, title, description, view count, and
        ``updated_at``. Raw Looker dashboard IDs are omitted unless
        ``include_ids=True``; set it only when a follow-up
        ``get_dashboard`` call needs the raw ID.
        """
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = fields
        payload: Any = self._client.get("/api/4.0/dashboards", params=params or None).json()
        if not isinstance(payload, list):
            return cast(dict[str, Any], payload)
        items = cast(list[Any], payload)
        summaries = [
            self._dashboard_summary(
                cast(dict[str, Any], dashboard), index=index, include_ids=include_ids
            )
            for index, dashboard in enumerate(items, start=1)
            if isinstance(dashboard, dict)
        ]
        return {"dashboards": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dashboard(
        self,
        dashboard_id: str,
        *,
        fields: str | None = None,
    ) -> dict[str, Any]:
        """Return one dashboard by ID.

        ``dashboard_id`` is the raw Looker dashboard ID returned by
        ``list_dashboards(include_ids=True)``. The ID is an internal
        handle and should not appear in final answers.
        """
        if not dashboard_id:
            raise ValueError("dashboard_id is required")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = fields
        return self._client.get(
            f"/api/4.0/dashboards/{dashboard_id}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_query(
        self,
        *,
        model: str,
        view: str,
        fields: list[str],
        filters: dict[str, str] | None = None,
        sorts: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Create an ad-hoc query against a LookML view.

        Use to build a one-off query without saving a Look. Returns
        ``{"id": <query_id>, ...}``; pass the ``id`` to :meth:`run_query`
        to execute.
        """
        if not model or not view or not fields:
            raise ValueError("model, view, and fields are required")
        body: dict[str, Any] = {
            "model": model,
            "view": view,
            "fields": fields,
        }
        if filters is not None:
            body["filters"] = filters
        if sorts is not None:
            body["sorts"] = sorts
        if limit is not None:
            body["limit"] = limit
        return self._client.post("/api/4.0/queries", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_query(
        self,
        query_id: int,
        *,
        result_format: str = "json",
    ) -> dict[str, Any]:
        """Run a previously created query.

        ``query_id`` comes from ``create_query``. Returns parsed JSON for
        ``json`` format, otherwise ``{"status", "body"}``.
        """
        if not query_id:
            raise ValueError("query_id is required")
        response = self._client.get(f"/api/4.0/queries/{query_id}/run/{result_format}")
        try:
            return response.json()
        except ValueError:
            return {"status": response.status, "body": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_USERS_OUTPUT)
    def list_users(
        self,
        *,
        limit: int = 25,
        offset: int | None = None,
        sorts: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Looker users.

        Returns compact summaries with ``user_ref``, display name, email,
        and ``is_disabled``. Raw Looker user IDs are omitted unless
        ``include_ids=True``. Pagination uses ``limit``/``offset`` (Looker's
        supported scheme; ``page``/``per_page`` are deprecated).
        """
        params: dict[str, Any] = {"limit": limit}
        if offset is not None:
            params["offset"] = offset
        if sorts is not None:
            params["sorts"] = sorts
        payload: Any = self._client.get("/api/4.0/users", params=params).json()
        if not isinstance(payload, list):
            return cast(dict[str, Any], payload)
        items = cast(list[Any], payload)
        summaries = [
            self._user_summary(cast(dict[str, Any], user), index=index, include_ids=include_ids)
            for index, user in enumerate(items, start=1)
            if isinstance(user, dict)
        ]
        return {"users": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_content(
        self,
        terms: str,
        *,
        types: str | None = None,
        limit: int = 25,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """Search Looker content (Looks/dashboards/etc.).

        ``terms`` is the keyword query (URL-encoded into the path);
        ``types`` narrows by content type (e.g. ``"dashboard"``). Returns
        the raw search payload. Pagination uses ``limit``/``offset``
        (Looker's supported scheme; ``page``/``per_page`` are deprecated).
        """
        if not terms:
            raise ValueError("terms is required")
        params: dict[str, Any] = {"limit": limit}
        if types is not None:
            params["types"] = types
        if offset is not None:
            params["offset"] = offset
        path = f"/api/4.0/content/{quote(terms, safe='')}"
        return self._client.get(path, params=params).json()
