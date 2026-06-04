# pyright: strict
"""Tests for vector store connectors.

Pinecone, Weaviate, Qdrant, Chroma, and Milvus.
"""

from __future__ import annotations

import pytest

from maivn_tools.connectors.chroma import ChromaToolSet
from maivn_tools.connectors.milvus import MilvusToolSet
from maivn_tools.connectors.pinecone import PineconeToolSet
from maivn_tools.connectors.qdrant import QdrantToolSet
from maivn_tools.connectors.weaviate import WeaviateToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Pinecone


def _pinecone() -> tuple[PineconeToolSet, MockTransport]:
    transport = MockTransport()
    return (
        PineconeToolSet(
            api_key="k",
            index_host="https://idx-abc.svc.region.pinecone.io",
            transport=transport,
        ),
        transport,
    )


def test_pinecone_requires_key() -> None:
    with pytest.raises(ValueError):
        PineconeToolSet(api_key="")


def test_pinecone_data_plane_requires_host() -> None:
    transport = MockTransport()
    bare = PineconeToolSet(api_key="k", transport=transport)
    transport.enqueue(json_response({"indexes": []}))
    bare.list_indexes()
    with pytest.raises(ValueError):
        bare.describe_index_stats()


def test_pinecone_control_plane() -> None:
    connector, transport = _pinecone()
    for _ in range(4):
        transport.enqueue(json_response({"name": "idx"}))
    connector.list_indexes()
    connector.describe_index("idx")
    connector.create_index(
        name="idx",
        dimension=1536,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
        deletion_protection="enabled",
    )
    connector.delete_index("idx")
    assert transport.requests[0].headers["Api-Key"] == "k"
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.describe_index("")
    with pytest.raises(ValueError):
        connector.create_index(name="", dimension=10)
    with pytest.raises(ValueError):
        connector.create_index(name="x", dimension=0)
    with pytest.raises(ValueError):
        connector.create_index(name="x", dimension=10, metric="bogus")
    with pytest.raises(ValueError):
        connector.delete_index("")


def test_pinecone_data_plane() -> None:
    connector, transport = _pinecone()
    for _ in range(7):
        transport.enqueue(json_response({"matches": []}))
    connector.describe_index_stats()
    connector.upsert(
        vectors=[{"id": "1", "values": [0.1] * 4}],
        namespace="ns",
    )
    connector.query(top_k=5, vector=[0.1] * 4, namespace="ns", include_values=True)
    connector.query(top_k=5, id="1", filter={"k": "v"})
    connector.fetch(ids=["1", "2"], namespace="ns")
    connector.delete_vectors(ids=["1"], namespace="ns")
    connector.update_vector(id="1", values=[0.2] * 4, set_metadata={"a": 1})
    with pytest.raises(ValueError):
        connector.upsert(vectors=[])
    with pytest.raises(ValueError):
        connector.query(top_k=0, vector=[0.1])
    with pytest.raises(ValueError):
        connector.query(top_k=5)
    with pytest.raises(ValueError):
        connector.query(top_k=5, vector=[0.1], id="1")
    with pytest.raises(ValueError):
        connector.fetch(ids=[])
    with pytest.raises(ValueError):
        connector.delete_vectors()
    with pytest.raises(ValueError):
        connector.update_vector(id="")


# MARK: - Weaviate


def _weaviate() -> tuple[WeaviateToolSet, MockTransport]:
    transport = MockTransport()
    return (
        WeaviateToolSet(base_url="https://w.example", api_key="k", transport=transport),
        transport,
    )


def test_weaviate_requires_base_url() -> None:
    with pytest.raises(ValueError):
        WeaviateToolSet(base_url="")


def test_weaviate_schema() -> None:
    connector, transport = _weaviate()
    for _ in range(5):
        transport.enqueue(json_response({"classes": []}))
    connector.get_meta()
    connector.list_classes()
    connector.get_class("Article")
    connector.create_class({"class": "Article", "properties": []})
    connector.delete_class("Article")
    assert transport.requests[0].headers["Authorization"] == "Bearer k"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_class("")
    with pytest.raises(ValueError):
        connector.create_class({})
    with pytest.raises(ValueError):
        connector.delete_class("")


def test_weaviate_objects() -> None:
    connector, transport = _weaviate()
    for _ in range(6):
        transport.enqueue(json_response({"id": "1"}))
    connector.get_object(object_id="1", class_name="Article", include=["vector"])
    connector.create_object(
        class_name="Article",
        properties={"title": "x"},
        id="00000000-0000-0000-0000-000000000001",
        vector=[0.1] * 4,
    )
    connector.update_object(
        class_name="Article",
        object_id="1",
        properties={"title": "y"},
        vector=[0.2] * 4,
    )
    connector.delete_object(class_name="Article", object_id="1")
    connector.batch_objects([{"class": "Article", "properties": {"t": "x"}}])
    connector.graphql_query("{ Get { Article { title } } }", variables={"a": 1})
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_object(object_id="")
    with pytest.raises(ValueError):
        connector.create_object(class_name="", properties={"x": 1})
    with pytest.raises(ValueError):
        connector.create_object(class_name="A", properties={})
    with pytest.raises(ValueError):
        connector.update_object(class_name="", object_id="1")
    with pytest.raises(ValueError):
        connector.delete_object(class_name="", object_id="1")
    with pytest.raises(ValueError):
        connector.batch_objects([])
    with pytest.raises(ValueError):
        connector.graphql_query("")


# MARK: - Qdrant


def _qdrant() -> tuple[QdrantToolSet, MockTransport]:
    transport = MockTransport()
    return (
        QdrantToolSet(base_url="https://q.example", api_key="k", transport=transport),
        transport,
    )


def test_qdrant_requires_base_url() -> None:
    with pytest.raises(ValueError):
        QdrantToolSet(base_url="")


def test_qdrant_collections() -> None:
    connector, transport = _qdrant()
    for _ in range(4):
        transport.enqueue(json_response({"result": {}}))
    connector.list_collections()
    connector.get_collection("col")
    connector.create_collection(
        name="col",
        vector_size=128,
        distance="Cosine",
        on_disk_payload=True,
    )
    connector.delete_collection("col")
    assert transport.requests[0].headers["api-key"] == "k"
    assert transport.requests[2].method == "PUT"
    with pytest.raises(ValueError):
        connector.get_collection("")
    with pytest.raises(ValueError):
        connector.create_collection(name="", vector_size=128)
    with pytest.raises(ValueError):
        connector.create_collection(name="x", vector_size=0)
    with pytest.raises(ValueError):
        connector.create_collection(name="x", vector_size=10, distance="bogus")
    with pytest.raises(ValueError):
        connector.delete_collection("")


def test_qdrant_points() -> None:
    connector, transport = _qdrant()
    for _ in range(6):
        transport.enqueue(json_response({"result": {}}))
    connector.upsert_points(
        collection="col",
        points=[{"id": 1, "vector": [0.1] * 4, "payload": {"k": "v"}}],
    )
    connector.search(
        collection="col",
        vector=[0.1] * 4,
        limit=5,
        filter={"must": []},
        score_threshold=0.5,
        offset=10,
    )
    connector.retrieve_points(collection="col", ids=[1, 2])
    connector.scroll(collection="col", limit=50, offset="cur", filter={"must": []})
    connector.delete_points(collection="col", ids=[1, 2])
    connector.create_payload_index(
        collection="col",
        field_name="cat",
        field_schema="keyword",
    )
    with pytest.raises(ValueError):
        connector.upsert_points(collection="", points=[{"id": 1}])
    with pytest.raises(ValueError):
        connector.upsert_points(collection="c", points=[])
    with pytest.raises(ValueError):
        connector.search(collection="", vector=[0.1])
    with pytest.raises(ValueError):
        connector.search(collection="c", vector=[])
    with pytest.raises(ValueError):
        connector.retrieve_points(collection="", ids=[1])
    with pytest.raises(ValueError):
        connector.retrieve_points(collection="c", ids=[])
    with pytest.raises(ValueError):
        connector.scroll(collection="")
    with pytest.raises(ValueError):
        connector.delete_points(collection="")
    with pytest.raises(ValueError):
        connector.delete_points(collection="c")
    with pytest.raises(ValueError):
        connector.create_payload_index(collection="", field_name="x", field_schema="keyword")


# MARK: - Chroma


def _chroma() -> tuple[ChromaToolSet, MockTransport]:
    transport = MockTransport()
    return (
        ChromaToolSet(
            base_url="http://localhost:8000",
            auth_token="t",
            transport=transport,
        ),
        transport,
    )


def test_chroma_requires_base_url() -> None:
    with pytest.raises(ValueError):
        ChromaToolSet(base_url="")


def test_chroma_collections() -> None:
    connector, transport = _chroma()
    for _ in range(5):
        transport.enqueue(json_response({"id": "c1"}))
    connector.heartbeat()
    connector.list_collections()
    connector.get_collection("col")
    connector.create_collection(
        name="col",
        metadata={"hnsw:space": "cosine"},
        get_or_create=True,
    )
    connector.delete_collection("col")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert (
        "/api/v2/tenants/default_tenant/databases/default_database/collections"
        in transport.requests[1].url
    )
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_collection("")
    with pytest.raises(ValueError):
        connector.create_collection(name="")
    with pytest.raises(ValueError):
        connector.delete_collection("")


def test_chroma_documents() -> None:
    connector, transport = _chroma()
    for _ in range(7):
        transport.enqueue(json_response({"ids": []}))
    connector.add(
        collection_id="cid",
        ids=["1"],
        embeddings=[[0.1] * 4],
        documents=["hello"],
        metadatas=[{"k": "v"}],
    )
    connector.upsert(
        collection_id="cid",
        ids=["1"],
        embeddings=[[0.1] * 4],
    )
    connector.query(
        collection_id="cid",
        query_embeddings=[[0.1] * 4],
        n_results=5,
        where={"k": "v"},
        where_document={"$contains": "x"},
        include=["distances"],
    )
    connector.query(collection_id="cid", query_embeddings=[[0.1] * 4])
    connector.get_documents(
        collection_id="cid",
        ids=["1"],
        where={"k": "v"},
        limit=10,
        offset=0,
        include=["documents"],
    )
    connector.delete_documents(collection_id="cid", ids=["1"])
    connector.count_documents("cid")
    with pytest.raises(ValueError):
        connector.add(collection_id="", ids=["1"], embeddings=[[0.1]])
    with pytest.raises(ValueError):
        connector.add(collection_id="c", ids=[], embeddings=[])
    with pytest.raises(ValueError):
        connector.upsert(collection_id="", ids=["1"], embeddings=[[0.1]])
    with pytest.raises(ValueError):
        connector.query(collection_id="", query_embeddings=[[0.1]])
    with pytest.raises(ValueError):
        connector.query(collection_id="c", query_embeddings=[])
    with pytest.raises(ValueError):
        connector.get_documents(collection_id="")
    with pytest.raises(ValueError):
        connector.delete_documents(collection_id="")
    with pytest.raises(ValueError):
        connector.delete_documents(collection_id="c")
    with pytest.raises(ValueError):
        connector.count_documents("")


# MARK: - Milvus


def _milvus() -> tuple[MilvusToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MilvusToolSet(
            base_url="https://m.example",
            token="t",
            transport=transport,
        ),
        transport,
    )


def test_milvus_requires_base_url() -> None:
    with pytest.raises(ValueError):
        MilvusToolSet(base_url="")


def test_milvus_collections() -> None:
    connector, transport = _milvus()
    for _ in range(4):
        transport.enqueue(json_response({"data": []}))
    connector.list_collections()
    connector.describe_collection("col")
    connector.create_collection(
        collection_name="col",
        dimension=128,
        metric_type="COSINE",
        primary_field="id",
        vector_field="vector",
        id_type="VarChar",
    )
    connector.drop_collection("col")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[0].json_body["dbName"] == "default"
    with pytest.raises(ValueError):
        connector.describe_collection("")
    with pytest.raises(ValueError):
        connector.create_collection(collection_name="", dimension=10)
    with pytest.raises(ValueError):
        connector.create_collection(collection_name="x", dimension=0)
    with pytest.raises(ValueError):
        connector.create_collection(collection_name="x", dimension=10, metric_type="bogus")
    with pytest.raises(ValueError):
        connector.drop_collection("")


def test_milvus_entities() -> None:
    connector, transport = _milvus()
    for _ in range(7):
        transport.enqueue(json_response({"data": []}))
    connector.insert(
        collection_name="col",
        data=[{"id": 1, "vector": [0.1] * 4}],
        partition_name="p",
    )
    connector.upsert(
        collection_name="col",
        data=[{"id": 1, "vector": [0.1] * 4}],
    )
    connector.search(
        collection_name="col",
        data=[[0.1] * 4],
        limit=5,
        filter="id > 0",
        output_fields=["id"],
        partition_names=["p"],
    )
    connector.get_entities(
        collection_name="col",
        ids=[1, 2],
        output_fields=["id"],
        partition_names=["p"],
    )
    connector.query(
        collection_name="col",
        filter="id > 0",
        output_fields=["id"],
        limit=100,
        offset=0,
    )
    connector.delete_entities(collection_name="col", filter="id > 0")
    connector.create_partition(collection_name="col", partition_name="p")
    with pytest.raises(ValueError):
        connector.insert(collection_name="", data=[{}])
    with pytest.raises(ValueError):
        connector.insert(collection_name="c", data=[])
    with pytest.raises(ValueError):
        connector.upsert(collection_name="", data=[{}])
    with pytest.raises(ValueError):
        connector.search(collection_name="", data=[[0.1]])
    with pytest.raises(ValueError):
        connector.search(collection_name="c", data=[])
    with pytest.raises(ValueError):
        connector.get_entities(collection_name="", ids=[1])
    with pytest.raises(ValueError):
        connector.get_entities(collection_name="c", ids=[])
    with pytest.raises(ValueError):
        connector.query(collection_name="", filter="x")
    with pytest.raises(ValueError):
        connector.query(collection_name="c", filter="")
    with pytest.raises(ValueError):
        connector.delete_entities(collection_name="")
    with pytest.raises(ValueError):
        connector.delete_entities(collection_name="c")
    with pytest.raises(ValueError):
        connector.create_partition(collection_name="", partition_name="p")
    with pytest.raises(ValueError):
        connector.create_partition(collection_name="c", partition_name="")


# MARK: - Agent-ready summary defaults


def test_pinecone_list_indexes_returns_summaries_without_raw() -> None:
    connector, transport = _pinecone()
    transport.enqueue(
        json_response(
            {
                "indexes": [
                    {
                        "name": "support-docs",
                        "dimension": 1536,
                        "metric": "cosine",
                        "host": "support-docs-abc.svc.pinecone.io",
                        "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
                        "status": {"state": "Ready"},
                    }
                ]
            }
        )
    )
    result = connector.list_indexes()
    assert result["indexes"][0]["index_ref"] == "index_1"
    assert result["indexes"][0]["name"] == "support-docs"
    assert result["indexes"][0]["dimension"] == 1536
    assert result["indexes"][0]["status"] == "Ready"
    assert "raw" not in result["indexes"][0]


def test_pinecone_list_indexes_include_ids_attaches_raw() -> None:
    connector, transport = _pinecone()
    transport.enqueue(
        json_response(
            {
                "indexes": [
                    {"name": "support-docs", "dimension": 1536, "metric": "cosine"},
                ]
            }
        )
    )
    result = connector.list_indexes(include_ids=True)
    assert result["indexes"][0]["raw"]["name"] == "support-docs"


def test_pinecone_describe_index_accepts_dict() -> None:
    connector, transport = _pinecone()
    transport.enqueue(json_response({"name": "support-docs"}))
    connector.describe_index({"name": "support-docs", "index_ref": "index_1"})
    assert transport.requests[-1].url.endswith("/indexes/support-docs")


def test_pinecone_delete_index_accepts_dict() -> None:
    connector, transport = _pinecone()
    transport.enqueue(json_response({}))
    connector.delete_index({"name": "old-docs", "index_ref": "index_1"})
    assert transport.requests[-1].method == "DELETE"
    assert transport.requests[-1].url.endswith("/indexes/old-docs")


def test_pinecone_query_returns_matches_shape() -> None:
    connector, transport = _pinecone()
    transport.enqueue(
        json_response(
            {
                "matches": [
                    {
                        "id": "doc-12",
                        "score": 0.91,
                        "metadata": {"title": "Pricing"},
                    }
                ]
            }
        )
    )
    result = connector.query(top_k=3, vector=[0.1] * 4)
    # Per-match id, score, metadata are NOT internal - they are the data the
    # agent needs to keep.
    assert result["matches"][0]["id"] == "doc-12"
    assert result["matches"][0]["score"] == 0.91


def test_pinecone_query_top_k_defaults_to_10() -> None:
    connector, transport = _pinecone()
    transport.enqueue(json_response({"matches": []}))
    connector.query(vector=[0.1] * 4)
    body = transport.requests[-1].json_body
    assert body["topK"] == 10


def test_pinecone_destructive_tools_tagged() -> None:
    for name in ("delete_index", "delete_vectors"):
        method = getattr(PineconeToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True


def test_weaviate_list_classes_returns_summaries() -> None:
    connector, transport = _weaviate()
    transport.enqueue(
        json_response(
            {
                "classes": [
                    {
                        "class": "Article",
                        "description": "News articles",
                        "vectorizer": "text2vec-openai",
                        "vectorIndexType": "hnsw",
                        "replicationConfig": {"factor": 1},
                        "properties": [{"name": "title"}, {"name": "body"}],
                    }
                ]
            }
        )
    )
    result = connector.list_classes()
    assert result["classes"][0]["class_ref"] == "class_1"
    # class_name is kept because it is both human-readable and the API key.
    assert result["classes"][0]["class_name"] == "Article"
    assert result["classes"][0]["property_count"] == 2
    assert "raw" not in result["classes"][0]


def test_weaviate_get_class_accepts_dict() -> None:
    connector, transport = _weaviate()
    transport.enqueue(json_response({"class": "Article"}))
    connector.get_class({"class_name": "Article", "class_ref": "class_1"})
    assert transport.requests[-1].url.endswith("/v1/schema/Article")


def test_weaviate_delete_class_accepts_dict() -> None:
    connector, transport = _weaviate()
    transport.enqueue(json_response({}))
    connector.delete_class({"class_name": "Article", "class_ref": "class_1"})
    assert transport.requests[-1].method == "DELETE"
    assert transport.requests[-1].url.endswith("/v1/schema/Article")


def test_weaviate_destructive_tools_tagged() -> None:
    for name in ("delete_class", "delete_object"):
        method = getattr(WeaviateToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True


def test_qdrant_list_collections_returns_summaries() -> None:
    connector, transport = _qdrant()
    transport.enqueue(
        json_response(
            {
                "result": {
                    "collections": [
                        {"name": "documents"},
                        {"name": "products"},
                    ]
                }
            }
        )
    )
    result = connector.list_collections()
    assert result["collections"][0]["collection_ref"] == "collection_1"
    assert result["collections"][0]["name"] == "documents"
    assert result["collections"][1]["collection_ref"] == "collection_2"
    assert "raw" not in result["collections"][0]


def test_qdrant_get_collection_accepts_dict() -> None:
    connector, transport = _qdrant()
    transport.enqueue(json_response({"result": {}}))
    connector.get_collection({"name": "documents", "collection_ref": "collection_1"})
    assert transport.requests[-1].url.endswith("/collections/documents")


def test_qdrant_delete_collection_accepts_dict() -> None:
    connector, transport = _qdrant()
    transport.enqueue(json_response({"result": True}))
    connector.delete_collection({"name": "old", "collection_ref": "collection_1"})
    assert transport.requests[-1].method == "DELETE"
    assert transport.requests[-1].url.endswith("/collections/old")


def test_qdrant_search_returns_shaped_results() -> None:
    connector, transport = _qdrant()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {"id": 1, "score": 0.92, "payload": {"title": "Doc 1"}},
                    {"id": 2, "score": 0.81, "payload": {"title": "Doc 2"}},
                ]
            }
        )
    )
    result = connector.search(collection="docs", vector=[0.1] * 4)
    assert result["result"][0]["id"] == 1
    assert result["result"][0]["score"] == 0.92
    body = transport.requests[-1].json_body
    assert body["limit"] == 10  # default cap


def test_qdrant_destructive_tools_tagged() -> None:
    for name in ("delete_collection", "delete_points"):
        method = getattr(QdrantToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True


def test_chroma_list_collections_returns_summaries() -> None:
    connector, transport = _chroma()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "support",
                    "metadata": {"hnsw:space": "cosine"},
                    "dimension": 1536,
                },
                {
                    "id": "00000000-0000-0000-0000-000000000002",
                    "name": "products",
                    "metadata": None,
                    "dimension": 768,
                },
            ]
        )
    )
    result = connector.list_collections()
    assert result["collections"][0]["collection_ref"] == "collection_1"
    assert result["collections"][0]["name"] == "support"
    assert result["collections"][0]["dimension"] == 1536
    assert "collection_id" not in result["collections"][0]


def test_chroma_list_collections_include_ids() -> None:
    connector, transport = _chroma()
    transport.enqueue(
        json_response([{"id": "uuid-1", "name": "support", "metadata": {}, "dimension": 1536}])
    )
    result = connector.list_collections(include_ids=True)
    assert result["collections"][0]["collection_id"] == "uuid-1"


def test_chroma_get_collection_accepts_dict() -> None:
    connector, transport = _chroma()
    transport.enqueue(json_response({"id": "uuid", "name": "support"}))
    connector.get_collection({"id": "uuid", "name": "support", "collection_ref": "collection_1"})
    assert transport.requests[-1].url.endswith("/collections/uuid")


def test_chroma_delete_collection_accepts_dict() -> None:
    connector, transport = _chroma()
    transport.enqueue(json_response({}))
    connector.delete_collection({"id": "uuid", "name": "old", "collection_ref": "collection_1"})
    assert transport.requests[-1].method == "DELETE"


def test_chroma_query_n_results_default_is_10() -> None:
    connector, transport = _chroma()
    transport.enqueue(json_response({"ids": [[]]}))
    connector.query(collection_id="cid", query_embeddings=[[0.1]])
    body = transport.requests[-1].json_body
    assert body["n_results"] == 10


def test_chroma_destructive_tools_tagged() -> None:
    for name in ("delete_collection", "delete_documents"):
        method = getattr(ChromaToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True


def test_milvus_list_collections_returns_summaries_for_strings() -> None:
    connector, transport = _milvus()
    transport.enqueue(json_response({"code": 0, "data": ["docs", "products"]}))
    result = connector.list_collections()
    assert result["collections"][0]["collection_ref"] == "collection_1"
    assert result["collections"][0]["name"] == "docs"
    assert result["collections"][1]["name"] == "products"


def test_milvus_list_collections_returns_summaries_for_dicts() -> None:
    connector, transport = _milvus()
    transport.enqueue(
        json_response(
            {
                "code": 0,
                "data": [
                    {"collectionName": "docs"},
                    {"collectionName": "products"},
                ],
            }
        )
    )
    result = connector.list_collections()
    assert result["collections"][0]["name"] == "docs"
    assert "raw" not in result["collections"][0]


def test_milvus_describe_collection_accepts_dict() -> None:
    connector, transport = _milvus()
    transport.enqueue(json_response({"data": {}}))
    connector.describe_collection({"name": "docs", "collection_ref": "collection_1"})
    body = transport.requests[-1].json_body
    assert body["collectionName"] == "docs"


def test_milvus_drop_collection_accepts_dict() -> None:
    connector, transport = _milvus()
    transport.enqueue(json_response({"code": 0}))
    connector.drop_collection({"name": "old", "collection_ref": "collection_1"})
    body = transport.requests[-1].json_body
    assert body["collectionName"] == "old"


def test_milvus_search_default_limit_is_10() -> None:
    connector, transport = _milvus()
    transport.enqueue(json_response({"data": []}))
    connector.search(collection_name="docs", data=[[0.1] * 4])
    body = transport.requests[-1].json_body
    assert body["limit"] == 10


def test_milvus_destructive_tools_tagged() -> None:
    for name in ("drop_collection", "delete_entities"):
        method = getattr(MilvusToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True
