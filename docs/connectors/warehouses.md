# Data warehouses

Analytics warehouse connectors. For transactional databases see
[Databases](databases.md).

Both warehouse connectors default to **read-only**: a regex-based
validator rejects any statement whose first keyword is outside the
connector's allowed read set, and any compound statement (multiple
semicolons) or mutation keyword inside the body is rejected as well.
Snowflake allows `SELECT`, `WITH`, `SHOW`, `DESCRIBE` (`DESC`),
`EXPLAIN`, and `USE`; BigQuery allows the narrower `SELECT`, `WITH`,
and `EXPLAIN`.

Both connectors follow the same agent-ready pattern as the database
connectors: catalog list tools return compact summary envelopes with
stable ordinal refs (`dataset_ref`, `table_ref`, `schema_ref`,
`warehouse_ref`, etc.) plus the user-facing names (`dataset_id`,
`table_id`, `name`, `database_name`, `schema_name`). Default
`max_results` is **25** for list tools and **100** for query tools;
table-preview tools default to **5 rows**. Pass `include_metadata=False`
to receive the raw provider response untouched.

## SnowflakeToolSet

`SnowflakeToolSet` wraps Snowflake's [SQL API
v2](https://docs.snowflake.com/en/developer-guide/sql-api/index) (HTTP).
Authenticate with a Snowflake-issued JWT or OAuth bearer token.

```python
from maivn_tools import SnowflakeToolSet

connector = SnowflakeToolSet(
    account="xy12345.us-east-1",
    token=secrets["SNOWFLAKE_JWT"],
    warehouse="ANALYTICS_WH",
    database="ANALYTICS",
    schema="PUBLIC",
)
```

Tools: `run_query(sql, bindings)`, `submit_async_query(sql, bindings)`,
`get_statement(statement_handle, partition)`,
`cancel_statement(statement_handle)` (destructive),
`list_databases(max_results)`,
`list_schemas(database, max_results)`,
`list_tables(database, schema, max_results)`,
`list_views(database, schema, max_results)`,
`describe_table(name, database, schema)`,
`list_warehouses(max_results)`, `server_version`.

`run_query` and `submit_async_query` validate the SQL is read-only
before submission. Identifier-taking tools validate names against
`^[A-Za-z_][A-Za-z0-9_$]*$` so they cannot inject SQL.

### Agent-ready behavior

- `list_databases`, `list_schemas`, `list_tables`, `list_views`, and
  `list_warehouses` return envelopes with ordinal refs (`database_ref`,
  `schema_ref`, `table_ref`, `view_ref`, `warehouse_ref`) and the
  user-facing `SHOW`-row columns (`name`, `database_name`,
  `schema_name`, `kind`, `owner`, plus size / state for warehouses).
  Default `max_results` is **25**.
- `describe_table(name, database, schema)` returns the raw Snowflake
  `DESCRIBE TABLE` payload (column rows under `data` with names under
  `resultSetMetaData.rowType`).
- `run_query` / `submit_async_query` return the raw SQL API envelope
  (`{"resultSetMetaData": {...}, "data": [...], "statementHandle": ...}`).
- Destructive tools: `cancel_statement` (aborts an in-flight statement;
  partial result partitions may be discarded).

Example:

```python
tables = connector.list_tables(database="ANALYTICS", schema="PUBLIC")
# {"tables": [{"table_ref": "table_1", "name": "ORDERS", "database_name": "ANALYTICS", "schema_name": "PUBLIC", "kind": "TABLE", "rows": 10000, "bytes": 1234567}, ...], "returned": 25, "total": 47, "truncated": True}
```

## BigQueryToolSet

`BigQueryToolSet` wraps the BigQuery [REST
API v2](https://cloud.google.com/bigquery/docs/reference/rest).
Authenticate with a Google OAuth access token (typically from a service
account with the `BigQuery Data Viewer` + `BigQuery Job User` roles, or
the appropriate `bigquery.*` scopes).

```python
from maivn_tools import BigQueryToolSet

connector = BigQueryToolSet(
    project_id="my-gcp-project",
    token=token_cache,
)
```

Tools: `list_datasets(max_results, include_metadata, ...)`,
`get_dataset(dataset_id)`,
`list_tables(dataset_id, max_results, include_metadata, ...)`,
`get_table(dataset_id, table_id)`,
`get_table_data(dataset_id, table_id, max_results, ...)`,
`run_query(sql, max_results, ...)`,
`get_query_results(job_id, max_results, ...)`,
`get_job(job_id, location)`, `list_jobs(max_results, ...)`,
`cancel_job(job_id, location)` (destructive),
`list_routines(dataset_id, max_results, ...)`,
`list_models(dataset_id, max_results, ...)`.

`run_query` rejects anything that is not a `SELECT`, `WITH`, or
`EXPLAIN` statement. `get_table_data` is the cheapest way to fetch raw
rows; `run_query` should be reserved for analytics-style queries where
billing-per-byte-scanned is acceptable.

### Agent-ready behavior

- `list_datasets` and `list_tables` return compact summaries by default
  with stable refs (`dataset_ref`, `table_ref`) plus the user-facing
  `dataset_id`, `table_id`, parent `project_id`, `location`, `type`
  (`TABLE` / `VIEW` / `MATERIALIZED_VIEW` / `EXTERNAL`),
  `friendly_name`, and `labels`. Pass `include_metadata=False` for the
  raw BigQuery list response. `nextPageToken` is preserved for paging.
- `get_table_data` defaults to **5 rows** so quick previews stay
  cheap; raise `max_results` for larger samples or use `run_query` with
  a `LIMIT`.
- `run_query` / `get_query_results` default to **100 rows** per page.
- `list_jobs`, `list_routines`, `list_models` default to **25** and
  return the raw BigQuery list response (these are inspection tools
  used less often than dataset / table exploration).
- Destructive tools: `cancel_job` (aborts an in-flight job; partial
  destination-table writes from long loads may be left behind).

Example:

```python
datasets = connector.list_datasets()
# {"datasets": [{"dataset_ref": "dataset_1", "dataset_id": "analytics", "project_id": "my-gcp-project", "location": "US", ...}, ...]}
tables = connector.list_tables(dataset_id=datasets["datasets"][0]["dataset_id"])
```
