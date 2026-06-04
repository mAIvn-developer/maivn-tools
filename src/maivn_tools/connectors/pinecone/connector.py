"""Pinecone REST API connector (control + data planes)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

# Current stable Pinecone API version. Pinecone pins versions via the
# ``X-Pinecone-API-Version`` header and guarantees each stable version a
# minimum 12-month support window. Bump this single constant to migrate.
_API_VERSION = "2025-10"


# MARK: Helpers


def _coerce_name(candidate: Any, *, key: str) -> str:
    """Best-effort lookup of an index name from a dict/list/scalar input."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[str, Any]", candidate)
        for k in (key, "name", "index_name"):
            value: Any = mapping.get(k)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            resolved = _coerce_name(item, key=key)
            if resolved:
                return resolved
    return ""


# MARK: ToolSet


@toolset(prefix="pinecone")
class PineconeToolSet:
    """A connector for the Pinecone REST API.

    Args:
        api_key: API key from the Pinecone console.
        index_host: Optional pre-resolved index host URL (e.g.
            ``https://my-index-abc123.svc.us-east1-aws.pinecone.io``).
            Required for data-plane (upsert / query / fetch / delete)
            calls. Control-plane (indexes / collections) calls go to the
            global ``api.pinecone.io`` endpoint.
        control_plane_url: Override for the control plane.
    """

    metadata = ProviderMetadata(
        name="pinecone",
        display_name="Pinecone",
        version="0.1.0",
        description="Indexes, vectors, namespaces, collections, and metadata filters.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        documentation_url="https://docs.pinecone.io/reference/",
        homepage_url="https://www.pinecone.io/",
        tags=("vector-store", "ai"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        index_host: str | None = None,
        control_plane_url: str = "https://api.pinecone.io",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._control = HttpClient(
            base_url=control_plane_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Api-Key"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Pinecone-API-Version": _API_VERSION,
            },
        )
        self._data: HttpClient | None = None
        if index_host is not None:
            self._data = HttpClient(
                base_url=index_host.rstrip("/"),
                auth=ApiKeyAuth(api_key, header="Api-Key"),
                transport=transport,
                default_headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Pinecone-API-Version": _API_VERSION,
                },
            )

    @property
    def client(self) -> HttpClient:
        return self._control

    def _require_data(self) -> HttpClient:
        if self._data is None:
            raise ValueError(
                "index_host must be set in the constructor to call data-plane endpoints"
            )
        return self._data

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_indexes(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List indexes in the Pinecone project.

        Best first tool for index discovery. Returns compact summaries:
        ``index_ref`` (``index_1``, ``index_2``, ...), ``name``,
        ``dimension``, ``metric``, ``status``, ``host``, ``spec``.
        ``name`` and ``host`` are user-facing labels (and Pinecone keys),
        so they are kept. Set ``include_ids=True`` if the full raw record
        is needed.
        """
        raw: Any = self._control.get("/indexes").json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        raw_indexes: Any = payload.get("indexes", [])
        indexes: list[Any] = cast("list[Any]", raw_indexes) if isinstance(raw_indexes, list) else []
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(indexes, start=1):
            if not isinstance(item, dict):
                continue
            record = cast("dict[str, Any]", item)
            status: Any = record.get("status")
            state: Any = ""
            if isinstance(status, dict):
                state = cast("dict[str, Any]", status).get("state", "")
            summary: dict[str, Any] = {
                "index_ref": f"index_{index}",
                "name": record.get("name", ""),
                "dimension": record.get("dimension"),
                "metric": record.get("metric", ""),
                "status": state,
                "host": record.get("host", ""),
                "spec": record.get("spec", {}),
            }
            if include_ids:
                summary["raw"] = record
            summaries.append(summary)
        return {"indexes": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_index(self, name: Any) -> dict[str, Any]:
        """Return one index's full configuration.

        Accepts a raw index name or an index dict returned by
        :meth:`list_indexes`. Returns the Pinecone index resource
        (``name``, ``dimension``, ``metric``, ``host``, ``spec``,
        ``status``).
        """
        resolved = _coerce_name(name, key="name")
        if not resolved:
            raise ValueError("name is required")
        return self._control.get(f"/indexes/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_index(
        self,
        *,
        name: str,
        dimension: int,
        metric: str = "cosine",
        spec: dict[str, Any] | None = None,
        deletion_protection: str = "disabled",
    ) -> dict[str, Any]:
        """Create a serverless or pod-based index.

        ``metric`` must be one of ``cosine``, ``euclidean``,
        ``dotproduct``. ``spec`` is the deployment spec
        (``{"serverless": {"cloud": ..., "region": ...}}`` or
        ``{"pod": {...}}``). Returns the new index resource.
        """
        if not name or dimension < 1:
            raise ValueError("name and a positive dimension are required")
        if metric not in {"cosine", "euclidean", "dotproduct"}:
            raise ValueError("metric must be cosine/euclidean/dotproduct")
        body: dict[str, Any] = {
            "name": name,
            "dimension": dimension,
            "metric": metric,
            "deletion_protection": deletion_protection,
        }
        if spec is not None:
            body["spec"] = spec
        return self._control.post("/indexes", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_index(self, name: Any) -> dict[str, Any]:
        """Delete an index and all its vectors (irreversible).

        Destructive and not reversible. Confirm with the user first.
        Accepts a raw index name or an index dict returned by
        :meth:`list_indexes` / :meth:`describe_index`.
        """
        resolved = _coerce_name(name, key="name")
        if not resolved:
            raise ValueError("name is required")
        response = self._control.delete(f"/indexes/{resolved}")
        return {"name": resolved, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_index_stats(self) -> dict[str, Any]:
        """Return per-namespace stats for the configured index.

        Requires ``index_host`` to have been set on the connector.
        Returns ``{"namespaces": {<ns>: {"vectorCount": ...}, ...},
        "dimension": ..., "indexFullness": ..., "totalVectorCount": ...}``.
        """
        return self._require_data().post("/describe_index_stats", json={}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert(
        self,
        *,
        vectors: list[dict[str, Any]],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Upsert vectors into the configured index.

        Each vector is ``{"id": <str>, "values": [<float>, ...],
        "metadata": {...}}``. Returns ``{"upsertedCount": <n>}``.
        """
        if not vectors:
            raise ValueError("vectors must be non-empty")
        body: dict[str, Any] = {"vectors": vectors}
        if namespace is not None:
            body["namespace"] = namespace
        return self._require_data().post("/vectors/upsert", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query(
        self,
        *,
        top_k: int = 10,
        vector: list[float] | None = None,
        id: str | None = None,
        namespace: str | None = None,
        filter: dict[str, Any] | None = None,
        include_values: bool = False,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Query nearest neighbors by vector or by ID.

        Best tool for retrieval-augmented lookups. Provide either
        ``vector`` (an embedding) or ``id`` (look up neighbors of an
        existing vector). ``top_k`` defaults to 10. Returns
        ``{"matches": [{"id": ..., "score": ..., "metadata": {...}}, ...]}``.
        The ``id`` on each match is the document/chunk identifier that
        downstream tools (e.g. :meth:`fetch`) consume - this is data the
        agent needs, not an internal handle.
        """
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if (vector is None) == (id is None):
            raise ValueError("Provide exactly one of vector or id")
        body: dict[str, Any] = {
            "topK": top_k,
            "includeValues": include_values,
            "includeMetadata": include_metadata,
        }
        if vector is not None:
            body["vector"] = vector
        if id is not None:
            body["id"] = id
        if namespace is not None:
            body["namespace"] = namespace
        if filter is not None:
            body["filter"] = filter
        return self._require_data().post("/query", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def fetch(
        self,
        *,
        ids: list[str],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Fetch vectors by ID.

        Returns ``{"vectors": {<id>: {"id": ..., "values": [...],
        "metadata": {...}}}}``. Use the IDs returned by :meth:`query` to
        hydrate full vector + metadata records.
        """
        if not ids:
            raise ValueError("ids must be non-empty")
        params: dict[str, Any] = {"ids": ids}
        if namespace is not None:
            params["namespace"] = namespace
        return self._require_data().get("/vectors/fetch", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_vectors(
        self,
        *,
        ids: list[str] | None = None,
        delete_all: bool = False,
        namespace: str | None = None,
        filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete vectors by ID, filter, or all.

        Destructive and not reversible. ``delete_all=True`` removes every
        vector in the namespace. Confirm with the user before any bulk or
        ``delete_all`` operation.
        """
        if not ids and not delete_all and not filter:
            raise ValueError("Provide ids, filter, or delete_all=True")
        body: dict[str, Any] = {"deleteAll": delete_all}
        if ids is not None:
            body["ids"] = ids
        if namespace is not None:
            body["namespace"] = namespace
        if filter is not None:
            body["filter"] = filter
        return self._require_data().post("/vectors/delete", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_vector(
        self,
        *,
        id: str,
        values: list[float] | None = None,
        set_metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Patch a vector's values or metadata.

        ``id`` is the vector identifier (typically a document / chunk
        ID). At least one of ``values`` or ``set_metadata`` should be
        provided.
        """
        if not id:
            raise ValueError("id is required")
        body: dict[str, Any] = {"id": id}
        if values is not None:
            body["values"] = values
        if set_metadata is not None:
            body["setMetadata"] = set_metadata
        if namespace is not None:
            body["namespace"] = namespace
        return self._require_data().post("/vectors/update", json=body).json()
