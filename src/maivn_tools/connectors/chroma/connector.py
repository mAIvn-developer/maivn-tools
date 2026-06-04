"""Chroma REST API connector (HTTP-server flavor)."""

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


def _coerce_collection_id(candidate: Any) -> str:
    """Best-effort lookup of a Chroma collection UUID from input.

    The v2 REST collection endpoints address collections by ``collection_id``
    (a UUID), not by name. Accepts a raw UUID string or a collection dict
    returned by :meth:`ChromaToolSet.list_collections`
    (``include_ids=True``) / :meth:`ChromaToolSet.get_collection`.
    """
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("id", "collection_id"):
            value: Any = mapping.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            resolved = _coerce_collection_id(item)
            if resolved:
                return resolved
    return ""


# MARK: ToolSet


@toolset(prefix="chroma")
class ChromaToolSet:
    """A connector for the Chroma vector-store HTTP API.

    Args:
        base_url: Chroma HTTP server URL (default ``http://localhost:8000``).
        auth_token: Optional bearer-style token for the static-token
            authenticator.
        tenant: Tenant name (default ``"default_tenant"``).
        database: Database name (default ``"default_database"``).
    """

    metadata = ProviderMetadata(
        name="chroma",
        display_name="Chroma",
        version="0.1.0",
        description="Collections, documents, embeddings, query, and metadata filters.",
        auth_modes=(AuthMode.API_KEY, AuthMode.NONE),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        documentation_url="https://docs.trychroma.com/",
        homepage_url="https://www.trychroma.com/",
        tags=("vector-store", "ai"),
    )

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        auth_token: str | None = None,
        tenant: str = "default_tenant",
        database: str = "default_database",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.connection = connection
        self._tenant = tenant
        self._database = database
        auth = (
            ApiKeyAuth(auth_token, header="Authorization", prefix="Bearer")
            if auth_token
            else NoAuth()
        )
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

    def _base(self) -> str:
        return f"/api/v2/tenants/{self._tenant}/databases/{self._database}"

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def heartbeat(self) -> dict[str, Any]:
        """Return server heartbeat (a liveness probe).

        Use this once at startup to confirm connectivity.
        """
        return self._client.get("/api/v2/heartbeat").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_collections(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List collections in the active tenant/database.

        Best first tool for collection discovery. Returns compact
        summaries: ``collection_ref`` (``collection_1``, ``collection_2``,
        ...), ``name`` (user-facing label, also used for follow-up
        lookups), ``metadata``, ``dimension``. ``name`` is kept because
        it is the human-facing identifier. Raw provider ``id`` (a UUID
        used by write tools like :meth:`add`) is omitted by default - it
        is an internal handle. Set ``include_ids=True`` when a follow-up
        tool needs the raw ``collection_id``.
        """
        payload: Any = self._client.get(f"{self._base()}/collections").json()
        collections: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(collections, start=1):
            if not isinstance(item, dict):
                continue
            entry = cast(dict[str, Any], item)
            summary: dict[str, Any] = {
                "collection_ref": f"collection_{index}",
                "name": entry.get("name", ""),
                "metadata": entry.get("metadata", {}),
                "dimension": entry.get("dimension"),
            }
            if include_ids:
                summary["collection_id"] = entry.get("id", "")
            summaries.append(summary)
        return {"collections": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_collection(self, collection_id: Any) -> dict[str, Any]:
        """Return a collection by its UUID.

        The v2 REST endpoint addresses collections by ``collection_id``
        (a UUID), not by name. Pass the UUID from
        :meth:`list_collections` (``include_ids=True``) or a collection
        dict containing an ``id``. Returns ``{"id": ..., "name": ...,
        "metadata": {...}, "dimension": ...}``. The ``id`` is the UUID
        write tools (:meth:`add`, :meth:`upsert`, :meth:`query`) take as
        ``collection_id``.
        """
        resolved = _coerce_collection_id(collection_id)
        if not resolved:
            raise ValueError("collection_id is required")
        return self._client.get(f"{self._base()}/collections/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_collection(
        self,
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
        get_or_create: bool = False,
        configuration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create (or get-or-create) a collection.

        ``metadata`` is collection-level metadata (e.g.
        ``{"hnsw:space": "cosine"}`` to set the distance metric).
        Returns the new collection resource (with server-assigned
        ``id``).
        """
        if not name:
            raise ValueError("name is required")
        body: dict[str, Any] = {"name": name, "get_or_create": get_or_create}
        if metadata is not None:
            body["metadata"] = metadata
        if configuration is not None:
            body["configuration"] = configuration
        return self._client.post(f"{self._base()}/collections", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_collection(self, collection_id: Any) -> dict[str, Any]:
        """Delete a collection and all its documents (irreversible).

        Destructive and not reversible. Confirm with the user first.
        The v2 REST endpoint addresses collections by ``collection_id``
        (a UUID), not by name. Pass the UUID from
        :meth:`list_collections` (``include_ids=True``) or a collection
        dict containing an ``id``.
        """
        resolved = _coerce_collection_id(collection_id)
        if not resolved:
            raise ValueError("collection_id is required")
        response = self._client.delete(f"{self._base()}/collections/{resolved}")
        return {"collection_id": resolved, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add(
        self,
        *,
        collection_id: str,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
        documents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add documents to a collection.

        ``collection_id`` is the collection UUID (from :meth:`get_collection`
        or :meth:`list_collections` with ``include_ids=True``). ``ids``
        is the per-document identifier list. ``embeddings`` is required:
        the v2 REST API does not generate embeddings server-side, so
        callers must embed client-side and pass one vector per ``id``.
        """
        if not collection_id or not ids:
            raise ValueError("collection_id and ids are required")
        if not embeddings:
            raise ValueError("embeddings is required")
        if len(embeddings) != len(ids):
            raise ValueError("embeddings must have the same length as ids")
        body: dict[str, Any] = {"ids": ids, "embeddings": embeddings}
        if metadatas is not None:
            body["metadatas"] = metadatas
        if documents is not None:
            body["documents"] = documents
        return self._client.post(
            f"{self._base()}/collections/{collection_id}/add", json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert(
        self,
        *,
        collection_id: str,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
        documents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Upsert documents in a collection (insert or replace by ID).

        ``collection_id`` is the collection UUID. ``embeddings`` is
        required: the v2 REST API does not generate embeddings
        server-side, so callers must embed client-side and pass one
        vector per ``id``.
        """
        if not collection_id or not ids:
            raise ValueError("collection_id and ids are required")
        if not embeddings:
            raise ValueError("embeddings is required")
        if len(embeddings) != len(ids):
            raise ValueError("embeddings must have the same length as ids")
        body: dict[str, Any] = {"ids": ids, "embeddings": embeddings}
        if metadatas is not None:
            body["metadatas"] = metadatas
        if documents is not None:
            body["documents"] = documents
        return self._client.post(
            f"{self._base()}/collections/{collection_id}/upsert", json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query(
        self,
        *,
        collection_id: str,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: dict[str, Any] | None = None,
        where_document: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a nearest-neighbor query.

        Best tool for retrieval-augmented lookups. ``query_embeddings``
        (a list of query vectors) is required: the v2 REST API does not
        accept raw text or embed server-side, so callers must embed
        query text client-side first. ``n_results`` defaults to 10.

        Returns nested arrays-of-arrays, one inner list per submitted
        query embedding: ``{"ids": [[...]], "distances": [[...]],
        "metadatas": [[...]], "documents": [[...]]}``. Index results as
        ``result[field][query_index][result_index]``. The per-result
        ``ids`` are document identifiers the agent needs to keep.
        """
        if not collection_id:
            raise ValueError("collection_id is required")
        if not query_embeddings:
            raise ValueError("query_embeddings is required")
        body: dict[str, Any] = {"n_results": n_results}
        body["query_embeddings"] = query_embeddings
        if where is not None:
            body["where"] = where
        if where_document is not None:
            body["where_document"] = where_document
        if include is not None:
            body["include"] = include
        return self._client.post(
            f"{self._base()}/collections/{collection_id}/query", json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_documents(
        self,
        *,
        collection_id: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """List or filter documents in a collection.

        Returns ``{"ids": [...], "metadatas": [...], "documents":
        [...]}``. Use this to hydrate documents after :meth:`query`.
        """
        if not collection_id:
            raise ValueError("collection_id is required")
        body: dict[str, Any] = {}
        if ids is not None:
            body["ids"] = ids
        if where is not None:
            body["where"] = where
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if include is not None:
            body["include"] = include
        return self._client.post(
            f"{self._base()}/collections/{collection_id}/get", json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_documents(
        self,
        *,
        collection_id: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete documents by ID or filter (irreversible).

        Destructive and not reversible. Provide either ``ids`` or
        ``where``. Confirm with the user before bulk deletion.
        """
        if not collection_id:
            raise ValueError("collection_id is required")
        if not ids and not where:
            raise ValueError("Provide ids or where")
        body: dict[str, Any] = {}
        if ids is not None:
            body["ids"] = ids
        if where is not None:
            body["where"] = where
        return self._client.post(
            f"{self._base()}/collections/{collection_id}/delete", json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def count_documents(self, collection_id: str) -> dict[str, Any]:
        """Return the document count for a collection.

        ``collection_id`` is the collection UUID.
        """
        if not collection_id:
            raise ValueError("collection_id is required")
        return self._client.get(f"{self._base()}/collections/{collection_id}/count").json()
