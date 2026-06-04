"""Metabase REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="metabase")
class MetabaseToolSet:
    """A connector for the Metabase REST API.

    Args:
        base_url: Metabase instance URL.
        api_key: API key (recommended) or session ID. Sent as the
            ``X-Metabase-Session`` or ``X-API-KEY`` header depending on
            ``key_kind``.
        key_kind: ``"api"`` (default) for ``X-API-KEY`` or ``"session"``
            for ``X-Metabase-Session``.
    """

    metadata = ProviderMetadata(
        name="metabase",
        display_name="Metabase",
        version="0.1.0",
        description="Cards, dashboards, databases, collections, and dataset queries.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://www.metabase.com/docs/latest/api-documentation",
        homepage_url="https://www.metabase.com/",
        tags=("bi", "analytics"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        key_kind: str = "api",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url or not api_key:
            raise ValueError("base_url and api_key are required")
        if key_kind not in {"api", "session"}:
            raise ValueError("key_kind must be api or session")
        self.connection = connection
        header = "X-API-KEY" if key_kind == "api" else "X-Metabase-Session"
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header=header),
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
    def _card_summary(
        card: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_creator: Any = card.get("creator")
        creator: dict[str, Any] = (
            cast("dict[str, Any]", raw_creator) if isinstance(raw_creator, dict) else {}
        )
        summary: dict[str, Any] = {
            "card_ref": f"card_{index}",
            "name": card.get("name", ""),
            "description": card.get("description", "") or "",
            "display": card.get("display", ""),
            "creator_email": creator.get("email", ""),
            "updated_at": card.get("updated_at", ""),
        }
        if include_ids:
            summary["card_id"] = card.get("id", "")
        return summary

    @staticmethod
    def _dashboard_summary(
        dashboard: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_creator: Any = dashboard.get("creator")
        creator: dict[str, Any] = (
            cast("dict[str, Any]", raw_creator) if isinstance(raw_creator, dict) else {}
        )
        summary: dict[str, Any] = {
            "dashboard_ref": f"dashboard_{index}",
            "name": dashboard.get("name", ""),
            "description": dashboard.get("description", "") or "",
            "creator_email": creator.get("email", ""),
            "updated_at": dashboard.get("updated_at", ""),
        }
        if include_ids:
            summary["dashboard_id"] = dashboard.get("id", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the authenticated Metabase user.

        Use once at startup to confirm the API key/session is valid.
        """
        return self._client.get("/api/user/current").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_databases(self) -> dict[str, Any]:
        """List databases configured in Metabase.

        Returns the raw Metabase database list payload. Use ``id`` from
        an entry as the ``database`` argument to :meth:`query_dataset`.
        """
        return self._client.get("/api/database").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_cards(
        self,
        *,
        collection_id: int | None = None,
        archived: bool = False,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List saved questions ("cards").

        Best first tool for finding existing analyses. Returns compact
        summaries with ``card_ref``, name, description, display type,
        creator email, and ``updated_at``. Raw Metabase card IDs are
        omitted unless ``include_ids=True``; set it only when a follow-up
        :meth:`get_card` / :meth:`run_card_query` call needs the raw ID.
        """
        params: dict[str, Any] = {"archived": str(archived).lower()}
        if collection_id is not None:
            params["collection_id"] = collection_id
        payload: Any = self._client.get("/api/card", params=params).json()
        if not isinstance(payload, list):
            return payload
        items: list[Any] = cast("list[Any]", payload)
        limited: list[Any] = items[:limit] if limit and len(items) > limit else items
        summaries = [
            self._card_summary(cast("dict[str, Any]", card), index=index, include_ids=include_ids)
            for index, card in enumerate(limited, start=1)
            if isinstance(card, dict)
        ]
        return {"cards": summaries, "totalAvailable": len(items)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_card(self, card_id: int) -> dict[str, Any]:
        """Return one card by ID.

        ``card_id`` is the raw Metabase card ID returned by
        ``list_cards(include_ids=True)``. The ID is an internal handle and
        should not appear in final answers.
        """
        if not card_id:
            raise ValueError("card_id is required")
        return self._client.get(f"/api/card/{card_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_card_query(
        self,
        card_id: int,
        *,
        parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a card's query and return its result.

        Returns the Metabase query response (``data.rows``, ``data.cols``,
        etc.).
        """
        if not card_id:
            raise ValueError("card_id is required")
        body: dict[str, Any] = {}
        if parameters is not None:
            body["parameters"] = parameters
        return self._client.post(f"/api/card/{card_id}/query", json=body or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_dashboards(
        self,
        *,
        f: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List dashboards.

        ``f`` is the Metabase filter (``all``/``mine``/etc.). Returns
        compact summaries with ``dashboard_ref``, name, description,
        creator email, and ``updated_at``. Raw Metabase dashboard IDs are
        omitted unless ``include_ids=True``.
        """
        params: dict[str, Any] = {}
        if f is not None:
            params["f"] = f
        payload: Any = self._client.get("/api/dashboard", params=params or None).json()
        if not isinstance(payload, list):
            return payload
        items: list[Any] = cast("list[Any]", payload)
        limited: list[Any] = items[:limit] if limit and len(items) > limit else items
        summaries = [
            self._dashboard_summary(
                cast("dict[str, Any]", dashboard), index=index, include_ids=include_ids
            )
            for index, dashboard in enumerate(limited, start=1)
            if isinstance(dashboard, dict)
        ]
        return {"dashboards": summaries, "totalAvailable": len(items)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dashboard(self, dashboard_id: int) -> dict[str, Any]:
        """Return one dashboard by ID.

        ``dashboard_id`` is the raw Metabase dashboard ID. The ID is an
        internal handle and should not appear in final answers.
        """
        if not dashboard_id:
            raise ValueError("dashboard_id is required")
        return self._client.get(f"/api/dashboard/{dashboard_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_collections(self) -> dict[str, Any]:
        """List collections in the Metabase instance.

        Returns the raw Metabase collection list payload.
        """
        return self._client.get("/api/collection").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_dataset(
        self,
        *,
        database: int,
        query_type: str = "native",
        native: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run an ad-hoc query (native SQL or MBQL).

        ``database`` is the Metabase database ID. For SQL use
        ``query_type="native"`` and ``native={"query": "SELECT ..."}``;
        for structured use ``query_type="query"`` with an MBQL ``query``
        dict.
        """
        if not database:
            raise ValueError("database is required")
        if query_type not in {"native", "query"}:
            raise ValueError("query_type must be native or query")
        if query_type == "native" and not native:
            raise ValueError("native is required when query_type=native")
        if query_type == "query" and not query:
            raise ValueError("query is required when query_type=query")
        body: dict[str, Any] = {"database": database, "type": query_type}
        if native is not None:
            body["native"] = native
        if query is not None:
            body["query"] = query
        if parameters is not None:
            body["parameters"] = parameters
        return self._client.post("/api/dataset", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        q: str,
        *,
        models: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Search across Metabase content (cards, dashboards, tables, ...).

        Returns the raw Metabase search payload.
        """
        if not q:
            raise ValueError("q is required")
        params: dict[str, Any] = {"q": q}
        if models is not None:
            params["models"] = models
        if limit is not None:
            params["limit"] = limit
        return self._client.get("/api/search", params=params).json()
