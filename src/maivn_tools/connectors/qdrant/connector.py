"""Qdrant REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _coerce_collection_name(candidate: Any) -> str:
    """Best-effort lookup of a Qdrant collection name from input."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("collection", "collection_name", "name"):
            value = mapping.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            value = _coerce_collection_name(item)
            if value:
                return value
    return ""


# MARK: ToolSet


@toolset(prefix="qdrant")
class QdrantToolSet:
    """A connector for the Qdrant REST API.

    Args:
        base_url: Qdrant instance URL (default ``http://localhost:6333``).
        api_key: Optional API key for Qdrant Cloud.
    """

    metadata = ProviderMetadata(
        name="qdrant",
        display_name="Qdrant",
        version="0.1.0",
        description="Collections, points, search, scrolling, and filters.",
        auth_modes=(AuthMode.API_KEY, AuthMode.NONE),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        documentation_url="https://qdrant.tech/documentation/concepts/",
        homepage_url="https://qdrant.tech/",
        tags=("vector-store", "ai"),
    )

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:6333",
        api_key: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.connection = connection
        auth = ApiKeyAuth(api_key, header="api-key") if api_key else NoAuth()
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=auth,
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
    def list_collections(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List all collections.

        Best first tool for collection discovery. Returns compact
        summaries: ``collection_ref`` (``collection_1``, ``collection_2``,
        ...), ``name`` (user-facing label and Qdrant key). ``name`` is
        kept because it is both human-readable and the API identifier.
        Set ``include_ids=True`` to include the raw record.
        """
        payload: dict[str, Any] = cast(dict[str, Any], self._client.get("/collections").json())
        result_obj = payload.get("result", {})
        result: dict[str, Any] = (
            cast(dict[str, Any], result_obj) if isinstance(result_obj, dict) else {}
        )
        collections_obj = result.get("collections", [])
        collections: list[Any] = (
            cast("list[Any]", collections_obj) if isinstance(collections_obj, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(collections, start=1):
            if not isinstance(item, dict):
                continue
            item_dict = cast(dict[str, Any], item)
            summary: dict[str, Any] = {
                "collection_ref": f"collection_{index}",
                "name": item_dict.get("name", ""),
            }
            if include_ids:
                summary["raw"] = item_dict
            summaries.append(summary)
        return {"collections": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_collection(self, name: Any) -> dict[str, Any]:
        """Return a collection's configuration and stats.

        Accepts a raw collection name or a collection dict returned by
        :meth:`list_collections`. Returns
        ``{"result": {"vectors_count": ..., "config": {...}, "status":
        ...}}``.
        """
        resolved = _coerce_collection_name(name)
        if not resolved:
            raise ValueError("name is required")
        return self._client.get(f"/collections/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_collection(
        self,
        *,
        name: str,
        vector_size: int,
        distance: str = "Cosine",
        hnsw_config: dict[str, Any] | None = None,
        on_disk_payload: bool = False,
    ) -> dict[str, Any]:
        """Create a collection.

        ``distance`` must be one of ``Cosine``, ``Dot``, ``Euclid``,
        ``Manhattan``. ``on_disk_payload`` reduces memory for large
        metadata.
        """
        if not name or vector_size < 1:
            raise ValueError("name and a positive vector_size are required")
        if distance not in {"Cosine", "Dot", "Euclid", "Manhattan"}:
            raise ValueError("distance must be Cosine/Dot/Euclid/Manhattan")
        body: dict[str, Any] = {
            "vectors": {"size": vector_size, "distance": distance},
            "on_disk_payload": on_disk_payload,
        }
        if hnsw_config is not None:
            body["hnsw_config"] = hnsw_config
        return self._client.put(f"/collections/{name}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_collection(self, name: Any) -> dict[str, Any]:
        """Delete a collection and all its points (irreversible).

        Destructive and not reversible. Confirm with the user first.
        Accepts a raw collection name or a collection dict returned by
        :meth:`list_collections`.
        """
        resolved = _coerce_collection_name(name)
        if not resolved:
            raise ValueError("name is required")
        return self._client.delete(f"/collections/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_points(
        self,
        *,
        collection: str,
        points: list[dict[str, Any]],
        wait: bool = True,
    ) -> dict[str, Any]:
        """Upsert points into a collection.

        Each point is ``{"id": <int|str>, "vector": [<float>, ...],
        "payload": {...}}``. ``wait=True`` blocks until indexed.
        """
        if not collection or not points:
            raise ValueError("collection and points are required")
        return self._client.put(
            f"/collections/{collection}/points",
            params={"wait": str(wait).lower()},
            json={"points": points},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        *,
        collection: str,
        vector: list[float],
        limit: int = 10,
        with_payload: bool = True,
        with_vector: bool = False,
        filter: dict[str, Any] | None = None,
        score_threshold: float | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """Search nearest neighbors by vector.

        Best tool for retrieval-augmented lookups. ``limit`` defaults to
        10. Returns ``{"result": [{"id": ..., "score": ..., "payload":
        {...}}, ...]}``. The ``id`` on each result is the document /
        chunk identifier the agent needs to fetch back via
        :meth:`retrieve_points`.
        """
        if not collection or not vector:
            raise ValueError("collection and vector are required")
        body: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": with_payload,
            "with_vector": with_vector,
        }
        if filter is not None:
            body["filter"] = filter
        if score_threshold is not None:
            body["score_threshold"] = score_threshold
        if offset is not None:
            body["offset"] = offset
        return self._client.post(f"/collections/{collection}/points/search", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def retrieve_points(
        self,
        *,
        collection: str,
        ids: list[str | int],
        with_payload: bool = True,
        with_vector: bool = False,
    ) -> dict[str, Any]:
        """Retrieve points by ID.

        Hydrate document records returned by :meth:`search` (use their
        ``id`` field).
        """
        if not collection or not ids:
            raise ValueError("collection and ids are required")
        return self._client.post(
            f"/collections/{collection}/points",
            json={
                "ids": ids,
                "with_payload": with_payload,
                "with_vector": with_vector,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def scroll(
        self,
        *,
        collection: str,
        limit: int = 100,
        offset: str | int | None = None,
        filter: dict[str, Any] | None = None,
        with_payload: bool = True,
    ) -> dict[str, Any]:
        """Scroll through points (the snapshot iterator).

        Use this for bulk iteration rather than search. Pass the
        ``next_page_offset`` from the prior response as ``offset`` to
        continue.
        """
        if not collection:
            raise ValueError("collection is required")
        body: dict[str, Any] = {"limit": limit, "with_payload": with_payload}
        if offset is not None:
            body["offset"] = offset
        if filter is not None:
            body["filter"] = filter
        return self._client.post(f"/collections/{collection}/points/scroll", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_points(
        self,
        *,
        collection: str,
        ids: list[str | int] | None = None,
        filter: dict[str, Any] | None = None,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Delete points by ID or filter (irreversible).

        Destructive and not reversible. Provide either ``ids`` or
        ``filter``. Confirm with the user before any bulk deletion.
        """
        if not collection:
            raise ValueError("collection is required")
        if not ids and not filter:
            raise ValueError("Provide ids or filter")
        body: dict[str, Any] = {}
        if ids is not None:
            body["points"] = ids
        if filter is not None:
            body["filter"] = filter
        return self._client.post(
            f"/collections/{collection}/points/delete",
            params={"wait": str(wait).lower()},
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_payload_index(
        self,
        *,
        collection: str,
        field_name: str,
        field_schema: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Create a secondary index on a payload field.

        Required before filtering on a payload field at scale.
        ``field_schema`` is the field type (e.g. ``"keyword"``,
        ``"integer"``, ``"float"``, ``"geo"``).
        """
        if not collection or not field_name or not field_schema:
            raise ValueError("collection, field_name, and field_schema are required")
        return self._client.put(
            f"/collections/{collection}/index",
            json={"field_name": field_name, "field_schema": field_schema},
        ).json()
