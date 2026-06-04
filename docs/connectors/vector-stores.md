# Vector stores

`maivn-tools` ships first-party connectors for the most common vector
databases used in RAG pipelines. Each toolset follows the standard
`@toolset` / `@toolify` shape; the snippets below show only the
constructor and the headline tool surface.

> Tip: most agents only need read access (search + fetch). Register
> with `add_toolset(..., include_tags=["read"])` to drop write / delete
> tools.

## Agent-ready behavior (overview)

- **List tools** (`list_indexes` for Pinecone, `list_classes` for
  Weaviate, `list_collections` for Qdrant / Chroma / Milvus) return
  compact summaries by default with a stable display ref (`index_ref`,
  `class_ref`, `collection_ref`). The user-facing **name** (Pinecone index name,
  Weaviate class name, Qdrant/Chroma/Milvus collection name) is kept
  in the summary because it is also the API identifier callers pass
  back. Opaque records can be opted into with `include_ids=True`.
- **Search / query / GraphQL results are NOT hidden.** Tools like
  `query`, `search`, `graphql_query` return the per-match `id`,
  `score`, `metadata`, and (optionally) `vector` exactly as the
  provider returns them -- the agent needs the document ID to fetch
  the source record back via `fetch` / `retrieve_points` /
  `get_documents` / `get_entities` / `get_object`.
- Name-taking tools (`describe_index`, `get_class`, `get_collection`,
  `delete_index`, `delete_class`, `delete_collection`,
  `drop_collection`) accept the raw name or the dict returned by the
  matching list tool.
- Destructive tools (`delete_index`, `delete_class`, `delete_object`,
  `delete_collection`, `delete_vectors`, `delete_points`,
  `delete_documents`, `drop_collection`, `delete_entities`) require
  user confirmation -- they remove indexed data and are not
  reversible.

## PineconeToolSet

```python
from maivn_tools import PineconeToolSet

connector = PineconeToolSet(
    api_key=secrets["PINECONE_API_KEY"],
    index_host="https://my-index-abc.svc.region.pinecone.io",
)
```

`index_host` is the per-index endpoint returned by the control plane's
`describe_index` call. Control-plane tools (indexes / collections) work
without it; data-plane tools (`describe_index_stats`, `upsert`, `query`,
`fetch`, `delete_vectors`, `update_vector`) require it.

Tools: `list_indexes`, `describe_index`, `create_index`, `delete_index`
(destructive), `describe_index_stats`, `upsert`, `query`, `fetch`,
`delete_vectors` (destructive), `update_vector`.

**Agent-ready behavior**

- `list_indexes`: summary with `index_ref`, `name`, `dimension`,
  `metric`, `status`, `host`, `spec`. Names + hosts are kept (they are
  the user-facing keys). Set `include_ids=True` to attach the raw
  index record under `raw`.
- `describe_index` and `delete_index` accept a raw name or an index
  dict from `list_indexes`.
- `query` returns the raw Pinecone `{"matches": [...]}` payload --
  per-match `id`/`score`/`metadata` are exposed unchanged so the agent
  can pass IDs to `fetch`.

```python
indexes = connector.list_indexes()
stats = connector.describe_index(indexes["indexes"][0])  # dict accepted
```

## WeaviateToolSet

```python
from maivn_tools import WeaviateToolSet

connector = WeaviateToolSet(
    base_url="https://my-cluster.weaviate.network",
    api_key=secrets["WEAVIATE_API_KEY"],  # optional for self-hosted
)
```

REST schema + objects plus a GraphQL escape hatch for queries. Tools:
`get_meta`, `list_classes`, `get_class`, `create_class`, `delete_class`
(destructive), `get_object`, `create_object`, `update_object`,
`delete_object` (destructive), `batch_objects`, `graphql_query`.

**Agent-ready behavior**

- `list_classes`: summary with `class_ref`, `class_name`,
  `description`, `vectorizer`, `vector_index_type`,
  `replication_factor`, `property_count`. The class name is kept (it
  is the API identifier). Set `include_ids=True` to attach the full
  schema record under `raw`.
- `get_class`, `delete_class` accept a raw class name or a class dict.
- `graphql_query` returns the raw GraphQL response -- object IDs
  (`_additional { id }`) are intentionally surfaced so the agent can
  pass them to `get_object`.

## QdrantToolSet

```python
from maivn_tools import QdrantToolSet

connector = QdrantToolSet(
    base_url="https://my-cluster.qdrant.cloud",
    api_key=secrets["QDRANT_API_KEY"],  # optional for self-hosted
)
```

Tools: `list_collections`, `get_collection`, `create_collection`,
`delete_collection` (destructive), `upsert_points`, `search`,
`retrieve_points`, `scroll`, `delete_points` (destructive),
`create_payload_index`.

**Agent-ready behavior**

- `list_collections`: summary with `collection_ref`, `name`. Set
  `include_ids=True` to attach the full record under `raw`.
- `get_collection`, `delete_collection` accept a raw name or a
  collection dict.
- `search` (default limit 10) returns the raw `{"result": [{"id":
  ..., "score": ..., "payload": {...}}, ...]}` -- per-result `id` is
  what the agent passes to `retrieve_points`.

## ChromaToolSet

```python
from maivn_tools import ChromaToolSet

connector = ChromaToolSet(
    base_url="http://localhost:8000",
    auth_token=secrets.get("CHROMA_TOKEN"),  # optional static token
)
```

Targets the Chroma `/api/v2/tenants/.../databases/...` HTTP server.
Override `tenant`/`database` in the constructor for non-default
namespaces. Tools: `heartbeat`, `list_collections`, `get_collection`,
`create_collection`, `delete_collection` (destructive), `add`, `upsert`,
`query`, `get_documents`, `delete_documents` (destructive),
`count_documents`.

**Agent-ready behavior**

- `list_collections`: summary with `collection_ref`, `name`,
  `metadata`, `dimension`. Raw `collection_id` UUIDs (needed by `add`,
  `upsert`, `query`, `get_documents`, `delete_documents`,
  `count_documents`) are hidden by default; opt in with
  `include_ids=True`. Alternatively, call `get_collection(name)` --
  that returns the full record (including the `id`) by design.
- `get_collection`, `delete_collection` accept a raw name or a
  collection dict.
- `query` (default `n_results=10`) returns the raw
  `{"ids": [...], "distances": [...], "metadatas": [...], "documents":
  [...]}` -- per-result `ids` are kept.

## MilvusToolSet

```python
from maivn_tools import MilvusToolSet

connector = MilvusToolSet(
    base_url="https://in03-abc.serverless.us-west-2.cloud.zilliz.com",
    token=secrets["ZILLIZ_TOKEN"],  # "username:password" or API key
)
```

Targets the v2 RESTful API used by both self-hosted Milvus and Zilliz
Cloud. Tools: `list_collections`, `describe_collection`,
`create_collection`, `drop_collection` (destructive), `insert`,
`upsert`, `search`, `get_entities`, `query`, `delete_entities`
(destructive), `create_partition`.

**Agent-ready behavior**

- `list_collections`: summary with `collection_ref`, `name` (the
  Milvus collection name). Set `include_ids=True` to attach the
  raw record under `raw`.
- `describe_collection`, `drop_collection` accept a raw collection
  name or a collection dict.
- `search` (default limit 10) and `query` (default limit 100) return
  the raw Milvus payloads -- per-result `id` and `entity` payload are
  preserved so the agent can pass IDs to `get_entities`.
