"""Milvus / Zilliz Cloud REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import NoAuth
from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _coerce_collection_name(candidate: Any) -> str:
    """Best-effort lookup of a Milvus collection name from input."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for key in ("collection_name", "collectionName", "name"):
            value: Any = mapping.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            resolved = _coerce_collection_name(item)
            if resolved:
                return resolved
    return ""


# MARK: ToolSet


@toolset(prefix="milvus")
class MilvusToolSet:
    """A connector for the Milvus / Zilliz Cloud v2 REST API.

    Args:
        base_url: Cluster endpoint URL (e.g. ``https://in03-...zillizcloud.com``).
        token: Bearer-style token (``"username:password"`` or API key).
        db_name: Database name (default ``"default"``).
    """

    metadata = ProviderMetadata(
        name="milvus",
        display_name="Milvus",
        version="0.1.0",
        description="Collections, entities, vector search, partitions, and indexes.",
        auth_modes=(AuthMode.BEARER, AuthMode.NONE),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        documentation_url="https://milvus.io/api-reference/restful/v2.4.x/About.md",
        homepage_url="https://milvus.io/",
        tags=("vector-store", "ai"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        db_name: str = "default",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.connection = connection
        self._db = db_name
        auth = BearerTokenAuth(token) if token else NoAuth()
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

    def _attach_db(self, body: dict[str, Any]) -> dict[str, Any]:
        body.setdefault("dbName", self._db)
        return body

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_collections(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List collections in the active database.

        Best first tool for collection discovery. Returns compact
        summaries: ``collection_ref`` (``collection_1``,
        ``collection_2``, ...), ``name`` (user-facing label, also the
        Milvus API key). ``name`` is kept because it is both
        human-readable and the API identifier. Set ``include_ids=True``
        to keep raw provider records.
        """
        raw_payload: object = self._client.post(
            "/v2/vectordb/collections/list", json=self._attach_db({})
        ).json()
        payload: dict[str, Any] = (
            cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
        )
        raw_data: Any = payload.get("data", [])
        rows: list[Any] = cast("list[Any]", raw_data) if isinstance(raw_data, list) else []
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(rows, start=1):
            if isinstance(item, str):
                summary: dict[str, Any] = {
                    "collection_ref": f"collection_{index}",
                    "name": item,
                }
            elif isinstance(item, dict):
                record = cast(dict[Any, Any], item)
                summary = {
                    "collection_ref": f"collection_{index}",
                    "name": record.get("collectionName") or record.get("name") or "",
                }
                if include_ids:
                    summary["raw"] = record
            else:
                continue
            summaries.append(summary)
        code: Any = payload.get("code")
        return {"collections": summaries, "code": code}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_collection(self, collection_name: Any) -> dict[str, Any]:
        """Return a collection's schema and statistics.

        Accepts a raw collection name or a collection dict returned by
        :meth:`list_collections`. Returns the full Milvus describe
        response (fields, num_shards, num_partitions, etc.).
        """
        resolved = _coerce_collection_name(collection_name)
        if not resolved:
            raise ValueError("collection_name is required")
        return self._client.post(
            "/v2/vectordb/collections/describe",
            json=self._attach_db({"collectionName": resolved}),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_collection(
        self,
        *,
        collection_name: str,
        dimension: int,
        metric_type: str = "COSINE",
        primary_field: str = "id",
        vector_field: str = "vector",
        id_type: str = "Int64",
    ) -> dict[str, Any]:
        """Create a "quick setup" collection.

        ``metric_type`` must be one of ``L2``, ``IP``, ``COSINE``,
        ``HAMMING``, ``JACCARD``. ``id_type`` is typically ``Int64`` or
        ``VarChar``. Returns the Milvus status response.
        """
        if not collection_name or dimension < 1:
            raise ValueError("collection_name and a positive dimension are required")
        if metric_type not in {"L2", "IP", "COSINE", "HAMMING", "JACCARD"}:
            raise ValueError("metric_type must be L2/IP/COSINE/HAMMING/JACCARD")
        body = {
            "collectionName": collection_name,
            "dimension": dimension,
            "metricType": metric_type,
            "primaryFieldName": primary_field,
            "vectorFieldName": vector_field,
            "idType": id_type,
        }
        return self._client.post(
            "/v2/vectordb/collections/create",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def drop_collection(self, collection_name: Any) -> dict[str, Any]:
        """Drop a collection and all its entities (irreversible).

        Destructive and not reversible. Confirm with the user first.
        Accepts a raw collection name or a collection dict returned by
        :meth:`list_collections`.
        """
        resolved = _coerce_collection_name(collection_name)
        if not resolved:
            raise ValueError("collection_name is required")
        return self._client.post(
            "/v2/vectordb/collections/drop",
            json=self._attach_db({"collectionName": resolved}),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def insert(
        self,
        *,
        collection_name: str,
        data: list[dict[str, Any]],
        partition_name: str | None = None,
    ) -> dict[str, Any]:
        """Insert entities.

        Each row in ``data`` is a dict of field values. Returns the
        Milvus status response including ``insertCount``.
        """
        if not collection_name or not data:
            raise ValueError("collection_name and data are required")
        body: dict[str, Any] = {
            "collectionName": collection_name,
            "data": data,
        }
        if partition_name is not None:
            body["partitionName"] = partition_name
        return self._client.post(
            "/v2/vectordb/entities/insert",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert(
        self,
        *,
        collection_name: str,
        data: list[dict[str, Any]],
        partition_name: str | None = None,
    ) -> dict[str, Any]:
        """Upsert entities (insert or update by primary key)."""
        if not collection_name or not data:
            raise ValueError("collection_name and data are required")
        body: dict[str, Any] = {
            "collectionName": collection_name,
            "data": data,
        }
        if partition_name is not None:
            body["partitionName"] = partition_name
        return self._client.post(
            "/v2/vectordb/entities/upsert",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        *,
        collection_name: str,
        data: list[list[float]],
        limit: int = 10,
        anns_field: str = "vector",
        filter: str | None = None,
        output_fields: list[str] | None = None,
        partition_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """ANN search.

        Best tool for retrieval-augmented lookups. ``data`` is a list of
        query vectors. ``limit`` defaults to 10. ``filter`` is a Milvus
        expression (e.g. ``"category == 'docs'"``). Returns ``{"data":
        [[{"id": ..., "distance": ..., "entity": {...}}, ...]]}``. The
        ``id`` is the entity primary key the agent needs to fetch back.
        """
        if not collection_name or not data:
            raise ValueError("collection_name and data are required")
        body: dict[str, Any] = {
            "collectionName": collection_name,
            "data": data,
            "limit": limit,
            "annsField": anns_field,
        }
        if filter is not None:
            body["filter"] = filter
        if output_fields is not None:
            body["outputFields"] = output_fields
        if partition_names is not None:
            body["partitionNames"] = partition_names
        return self._client.post(
            "/v2/vectordb/entities/search",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_entities(
        self,
        *,
        collection_name: str,
        ids: list[str | int],
        output_fields: list[str] | None = None,
        partition_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch entities by primary key.

        Use this to hydrate full entity records after :meth:`search`.
        """
        if not collection_name or not ids:
            raise ValueError("collection_name and ids are required")
        body: dict[str, Any] = {
            "collectionName": collection_name,
            "id": ids,
        }
        if output_fields is not None:
            body["outputFields"] = output_fields
        if partition_names is not None:
            body["partitionNames"] = partition_names
        return self._client.post(
            "/v2/vectordb/entities/get",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query(
        self,
        *,
        collection_name: str,
        filter: str,
        output_fields: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Run a scalar-filter query.

        Best tool for non-vector filtering (e.g. ``filter="category ==
        'invoices' and year > 2020"``). Returns ``{"data": [...]}``.
        """
        if not collection_name or not filter:
            raise ValueError("collection_name and filter are required")
        body: dict[str, Any] = {
            "collectionName": collection_name,
            "filter": filter,
            "limit": limit,
            "offset": offset,
        }
        if output_fields is not None:
            body["outputFields"] = output_fields
        return self._client.post(
            "/v2/vectordb/entities/query",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_entities(
        self,
        *,
        collection_name: str,
        filter: str | None = None,
        ids: list[str | int] | None = None,
        partition_name: str | None = None,
    ) -> dict[str, Any]:
        """Delete entities by ID or filter (irreversible).

        Destructive and not reversible. Provide either ``filter`` or
        ``ids``. Confirm with the user before bulk deletion.
        """
        if not collection_name:
            raise ValueError("collection_name is required")
        if not filter and not ids:
            raise ValueError("Provide filter or ids")
        body: dict[str, Any] = {"collectionName": collection_name}
        if filter is not None:
            body["filter"] = filter
        if ids is not None:
            body["id"] = ids
        if partition_name is not None:
            body["partitionName"] = partition_name
        return self._client.post(
            "/v2/vectordb/entities/delete",
            json=self._attach_db(body),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_partition(
        self,
        *,
        collection_name: str,
        partition_name: str,
    ) -> dict[str, Any]:
        """Create a partition inside a collection.

        Partitions logically group entities and enable per-partition
        search.
        """
        if not collection_name or not partition_name:
            raise ValueError("collection_name and partition_name are required")
        return self._client.post(
            "/v2/vectordb/partitions/create",
            json=self._attach_db(
                {
                    "collectionName": collection_name,
                    "partitionName": partition_name,
                }
            ),
        ).json()
