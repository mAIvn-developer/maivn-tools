"""Weaviate REST + GraphQL API connector."""

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


def _coerce_class_name(candidate: Any) -> str:
    """Best-effort lookup of a Weaviate class name from a dict/list/scalar."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("class_name", "class", "name"):
            value = mapping.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(candidate, list | tuple):
        items = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in items:
            value = _coerce_class_name(item)
            if value:
                return value
    return ""


# MARK: ToolSet


@toolset(prefix="weaviate")
class WeaviateToolSet:
    """A connector for the Weaviate REST + GraphQL API.

    Args:
        base_url: Weaviate instance URL.
        api_key: Optional API key for WCS-hosted instances.
    """

    metadata = ProviderMetadata(
        name="weaviate",
        display_name="Weaviate",
        version="0.1.0",
        description="Classes (collections), objects, GraphQL search, and batch ops.",
        auth_modes=(AuthMode.BEARER, AuthMode.NONE),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        documentation_url="https://weaviate.io/developers/weaviate/api",
        homepage_url="https://weaviate.io/",
        tags=("vector-store", "ai"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.connection = connection
        auth = BearerTokenAuth(api_key) if api_key else NoAuth()
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
    def get_meta(self) -> dict[str, Any]:
        """Return server metadata (a liveness + version probe).

        Returns ``{"hostname": ..., "modules": {...}, "version": ...}``.
        Use this once at startup to confirm connectivity and version
        before issuing other calls.
        """
        return self._client.get("/v1/meta").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_classes(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List schema classes (collections).

        Best first tool for collection discovery. Returns compact
        summaries: ``class_ref`` (``class_1``, ``class_2``, ...),
        ``class_name`` (user-facing label and Weaviate key),
        ``description``, ``vectorizer``, ``vector_index_type``,
        ``replication_factor``, ``property_count``. ``class_name`` is
        kept because it is both human-readable and the API identifier.
        Set ``include_ids=True`` to include the full raw schema record
        per class.
        """
        payload: dict[str, Any] = self._client.get("/v1/schema").json()
        raw_classes: Any = payload.get("classes", [])
        classes: list[Any] = cast(list[Any], raw_classes) if isinstance(raw_classes, list) else []
        summaries: list[dict[str, Any]] = []
        for index, raw_cls in enumerate(classes, start=1):
            if not isinstance(raw_cls, dict):
                continue
            cls = cast(dict[str, Any], raw_cls)
            replication: Any = cls.get("replicationConfig") or {}
            vector_index = cls.get("vectorIndexType", "")
            raw_properties: Any = cls.get("properties", [])
            properties: list[Any] = (
                cast(list[Any], raw_properties) if isinstance(raw_properties, list) else []
            )
            summary: dict[str, Any] = {
                "class_ref": f"class_{index}",
                "class_name": cls.get("class", ""),
                "description": cls.get("description", ""),
                "vectorizer": cls.get("vectorizer", ""),
                "vector_index_type": vector_index,
                "replication_factor": cast(dict[str, Any], replication).get("factor")
                if isinstance(replication, dict)
                else None,
                "property_count": len(properties),
            }
            if include_ids:
                summary["raw"] = cls
            summaries.append(summary)
        return {"classes": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_class(self, class_name: Any) -> dict[str, Any]:
        """Return one class's full schema definition.

        Accepts a raw class name or a class dict returned by
        :meth:`list_classes`. Returns ``{"class": ..., "properties": [...],
        "vectorizer": ..., ...}``.
        """
        resolved = _coerce_class_name(class_name)
        if not resolved:
            raise ValueError("class_name is required")
        return self._client.get(f"/v1/schema/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_class(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Create a schema class.

        ``schema`` must include a ``class`` field (the class name).
        Returns the new class definition.
        """
        if not schema or "class" not in schema:
            raise ValueError("schema must include a 'class' field")
        return self._client.post("/v1/schema", json=schema).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_class(self, class_name: Any) -> dict[str, Any]:
        """Delete a class and every object in it (irreversible).

        Destructive and not reversible. Confirm with the user first.
        Accepts a raw class name or a class dict returned by
        :meth:`list_classes`.
        """
        resolved = _coerce_class_name(class_name)
        if not resolved:
            raise ValueError("class_name is required")
        response = self._client.delete(f"/v1/schema/{resolved}")
        return {"class": resolved, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_object(
        self,
        *,
        object_id: str,
        class_name: str | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch an object by UUID.

        ``object_id`` is a Weaviate UUID (typically returned by
        :meth:`create_object` or by :meth:`graphql_query`). Always pass
        ``class_name`` so the current ``/v1/objects/{className}/{id}`` path is
        used; omitting it falls back to the legacy class-less
        ``/v1/objects/{id}`` path, which Weaviate has deprecated.
        """
        if not object_id:
            raise ValueError("object_id is required")
        path = f"/v1/objects/{class_name}/{object_id}" if class_name else f"/v1/objects/{object_id}"
        params: dict[str, Any] = {}
        if include is not None:
            params["include"] = ",".join(include)
        return self._client.get(path, params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_object(
        self,
        *,
        class_name: str,
        properties: dict[str, Any],
        id: str | None = None,
        vector: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create an object in a class.

        Returns the new object resource (with server-assigned ``id``).
        Provide ``vector`` if your class uses ``"none"`` vectorization
        and you bring your own embeddings.
        """
        if not class_name or not properties:
            raise ValueError("class_name and properties are required")
        body: dict[str, Any] = {"class": class_name, "properties": properties}
        if id is not None:
            body["id"] = id
        if vector is not None:
            body["vector"] = vector
        return self._client.post("/v1/objects", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_object(
        self,
        *,
        class_name: str,
        object_id: str,
        properties: dict[str, Any] | None = None,
        vector: list[float] | None = None,
    ) -> dict[str, Any]:
        """Patch an object's properties or vector.

        At least one of ``properties`` or ``vector`` should be provided.
        Returns the updated object resource.
        """
        if not class_name or not object_id:
            raise ValueError("class_name and object_id are required")
        body: dict[str, Any] = {"class": class_name, "id": object_id}
        if properties is not None:
            body["properties"] = properties
        if vector is not None:
            body["vector"] = vector
        return self._client.patch(f"/v1/objects/{class_name}/{object_id}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_object(
        self,
        *,
        class_name: str,
        object_id: str,
    ) -> dict[str, Any]:
        """Delete an object (irreversible).

        Destructive and not reversible. Confirm with the user first.
        """
        if not class_name or not object_id:
            raise ValueError("class_name and object_id are required")
        response = self._client.delete(f"/v1/objects/{class_name}/{object_id}")
        return {
            "object_id": object_id,
            "deleted": True,
            "status": response.status,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_objects(self, objects: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch-upsert objects.

        Each entry is the same shape as a :meth:`create_object` body.
        Returns the per-object status array.
        """
        if not objects:
            raise ValueError("objects must be non-empty")
        return self._client.post("/v1/batch/objects", json={"objects": objects}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def graphql_query(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a GraphQL query (the primary search interface).

        Best tool for retrieval queries. ``query`` is a GraphQL string
        (e.g. ``"{ Get { Article(limit: 5, nearText: {concepts:
        [\\"GPU\\"]}) { title } } }"``). Returns ``{"data": {...},
        "errors": [...]}``. Object IDs (``_additional { id }``) in
        results are document identifiers the agent can pass to
        :meth:`get_object`.
        """
        if not query:
            raise ValueError("query is required")
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables
        return self._client.post("/v1/graphql", json=body).json()
