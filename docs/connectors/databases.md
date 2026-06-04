# Databases

Transactional database connectors. Each toolset gives an agent
read-only schema introspection and parameterized query tools over one
database engine. For analytics warehouses see
[Warehouses](warehouses.md).

Every connector follows the standard `@toolset` / `@toolify` shape and
defaults to **read-only** -- writes (and write-style SQL) are rejected
either at the parser or with `SET TRANSACTION READ ONLY` / `PRAGMA
query_only`. Use `add_toolset(..., include_tags=["read"])` to drop any
write surface a connector exposes.

All five connectors in this group follow the same agent-ready pattern
for catalog tools: `list_schemas`, `list_tables`, `list_views`,
`list_indexes`, and `list_databases` return a summary envelope
(`{<key>, returned, total, truncated}`) where each entry carries a
stable ordinal ref (`schema_ref`, `table_ref`, `view_ref`, `index_ref`,
`database_ref`) plus the user-facing schema / table / view / column /
index names. Those names are always present -- the connector never hides
identifiers an agent needs to compose a follow-up query. The
`max_results` argument caps each list (default **25**). `sample_table`
defaults to **5 rows** so quick lookups stay tidy. The read-only safety
guarantees still apply: parser denylists, `PRAGMA query_only`,
`SET TRANSACTION READ ONLY`, and identifier validation prevent
accidental writes.

## SQLiteToolSet

`SQLiteToolSet` exposes read-only schema introspection and parameterized
query tools over a local SQLite database file. It is dependency-free
(uses the standard-library `sqlite3` module) and opens a fresh
connection per call so the connector is safe to share across threads.

```python
from maivn import Agent
from maivn_tools import SQLiteToolSet, register_connector

connector = SQLiteToolSet("./reports.db", row_limit=500)
agent = Agent(model="auto")
register_connector(agent, connector)
```

Tools: `list_tables(include_views, max_results)`,
`list_views(max_results)`, `list_indexes(table=None, max_results)`,
`list_foreign_keys(table)`, `describe_table(name)`, `get_schema_dump()`,
`sample_table(name, limit)`, `count_rows(name)`,
`explain_query(sql, plan)`, `run_query(sql, parameters, row_limit)`.

`run_query` only accepts `SELECT`, `WITH`, and `EXPLAIN`. Compound
statements (multiple semicolons) are rejected, and a regex denylist
blocks `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`,
`REPLACE`, `TRUNCATE`, `ATTACH`, `DETACH`, `VACUUM`, `REINDEX`, and
`PRAGMA`. Identifier-taking tools validate `name` against
`[A-Za-z_][A-Za-z0-9_]*` so the underlying `PRAGMA` calls cannot be
hijacked.

| Argument | Default | Purpose |
| --- | --- | --- |
| `database` | required | Path to the SQLite file, or `":memory:"`. |
| `row_limit` | `500` | Maximum rows returned per query. |
| `query_timeout_seconds` | `5.0` | SQLite busy timeout. |

### Agent-ready behavior

- `list_tables`, `list_views`, and `list_indexes` return envelopes with
  ordinal `table_ref` / `view_ref` / `index_ref` plus user-facing `name`
  and (for indexes / views) the DDL `sql`. Internal `sqlite_*` objects
  are always filtered out.
- `describe_table` returns column metadata, primary keys, and indexes --
  the column `name` / `type` / `notnull` / `default` / `primary_key`
  fields a SELECT needs.
- `sample_table(name)` defaults to **5 rows**; raise `limit` (capped by
  the connector `row_limit`) when you need more.
- `run_query` defaults to **100 rows** per call; raise `row_limit` per
  call up to the configured connector ceiling.
- No write tools -- `SQLiteToolSet` is read-only by design.

Example:

```python
tables = connector.list_tables()
# {"tables": [{"table_ref": "table_1", "name": "orders", "type": "table"}, ...], "returned": 25, "total": 47, "truncated": True}
sample = connector.sample_table(tables["tables"][0]["name"])
# {"columns": ["id", "customer_id", ...], "rows": [{"id": 1, ...}, ...], "row_count": 5, "truncated": True}
```

## PostgresToolSet

`PostgresToolSet` exposes read-only schema introspection and query tools
over a PostgreSQL database. The connector wraps any DB-API 2.0 driver
behind a small connection-factory protocol so tests can inject fakes
and so the base package does not require `psycopg` to be installed.

```python
from maivn_tools import PostgresToolSet

connector = PostgresToolSet(
    dsn="postgresql://reader:password@localhost:5432/analytics",
    row_limit=500,
)
```

If `psycopg` is not installed the connector falls back to `psycopg2`.
To use a different driver, supply a `connection_factory`:

```python
import psycopg

connector = PostgresToolSet(
    connection_factory=lambda: psycopg.connect(dsn, autocommit=True),
)
```

Tools: `list_schemas(max_results)`, `list_tables(schema, max_results)`,
`list_views(schema, max_results)`,
`list_indexes(schema, table=None, max_results)`,
`list_foreign_keys(name, schema)`, `list_extensions()`,
`describe_table(name, schema)`, `get_table_size(name, schema)`,
`sample_table(name, schema, limit)`, `count_rows(name, schema)`,
`server_version()`, `explain_query(sql, analyze, verbose)`,
`run_query(sql, parameters, row_limit)`.

`run_query` only accepts `SELECT`, `WITH`, and `EXPLAIN`. The connector
issues `SET TRANSACTION READ ONLY` per call (drivers that do not support
it are silently ignored), so even if a query somehow bypasses the regex,
the database itself refuses writes. `explain_query` refuses
`analyze=True` because `EXPLAIN ANALYZE` executes the underlying query
and may have side effects.

| Argument | Default | Purpose |
| --- | --- | --- |
| `dsn` | None | Connection string used by the default factory. |
| `connection_factory` | None | Custom DB-API factory; mutually exclusive with `dsn`. |
| `row_limit` | `500` | Maximum rows returned per query. |

### Agent-ready behavior

- `list_schemas`, `list_tables`, `list_views`, and `list_indexes`
  return envelopes with ordinal refs (`schema_ref`, `table_ref`,
  `view_ref`, `index_ref`) plus the user-facing `schema` / `name` /
  `type` columns. Default `max_results` is **25**.
- `describe_table` returns `{"name", "schema", "columns", "primary_key"}`
  -- `columns[*]` carries `name`, `type`, `nullable`, `default`.
- `sample_table(name)` defaults to **5 rows**.
- `run_query` defaults to **100 rows** per call; raise `row_limit` per
  call up to the configured ceiling.

Example:

```python
tables = connector.list_tables(schema="public")
# {"tables": [{"table_ref": "table_1", "schema": "public", "name": "orders", "type": "BASE TABLE"}, ...], ...}
```

## MySQLToolSet

`MySQLToolSet` is a read-only DB-API 2.0 connector for MySQL and
MariaDB, mirroring `PostgresToolSet`. The driver
(`mysql-connector-python` or `pymysql`) is not a hard dependency -- pass
`connection_factory` or install one of the supported drivers.

```python
from maivn_tools import MySQLToolSet

connector = MySQLToolSet(connect_kwargs={
    "host": "db.example.com",
    "user": "reader",
    "password": secrets["MYSQL_PASSWORD"],
    "database": "analytics",
})
```

Tools: `list_databases(max_results)`,
`list_tables(schema, max_results)`, `describe_table(name, schema)`,
`list_indexes(name, schema, max_results)`,
`explain_query(sql, analyze)`, `server_version()`,
`sample_table(name, schema, limit)`, `count_rows(name, schema)`,
`run_query(sql, parameters, row_limit)`.

`run_query` only accepts statements whose first keyword is `SELECT`,
`WITH`, `EXPLAIN`, `DESCRIBE`, `DESC`, or `SHOW`. Compound statements
and a denylist of mutation keywords are rejected.

### Agent-ready behavior

- `list_databases`, `list_tables`, and `list_indexes` return envelopes
  with `database_ref` / `table_ref` / `index_ref` plus the user-facing
  MySQL column names (`Database`, `name`, `type`, plus `SHOW INDEXES`
  columns like `Key_name`, `Column_name`, `Non_unique`). Default
  `max_results` is **25**.
- `describe_table` returns `{"schema", "name", "columns", "primary_key"}`
  with the MySQL column `key` flag (`PRI`, `MUL`, ...).
- `sample_table(name)` defaults to **5 rows**.
- `run_query` defaults to **100 rows** per call.

## SQLServerToolSet

`SQLServerToolSet` is a read-only DB-API 2.0 connector for Microsoft
SQL Server. Pass `connection_string` to use `pyodbc`, `connect_kwargs`
to use `pymssql`, or a custom `connection_factory` for tests.

```python
from maivn_tools import SQLServerToolSet

connector = SQLServerToolSet(connection_string="DRIVER=ODBC Driver 18 ...")
```

Tools: `list_databases(max_results)`, `list_schemas(max_results)`,
`list_tables(schema="dbo", max_results)`,
`describe_table(name, schema="dbo")`,
`list_views(schema="dbo", max_results)`, `server_version()`,
`sample_table(name, schema, limit)`, `count_rows(name, schema)`,
`run_query(sql, parameters, row_limit)`.

`run_query` accepts only `SELECT` and `WITH` statements; compound
statements and a denylist of mutation keywords (including `EXEC` /
`EXECUTE` / `MERGE`) are rejected.

### Agent-ready behavior

- `list_databases`, `list_schemas`, `list_tables`, and `list_views`
  return envelopes with ordinal refs plus user-facing `name` / `schema`
  / `type` columns. Default `max_results` is **25**.
- `describe_table` returns `{"schema", "name", "columns", "primary_key"}`.
- `sample_table(name)` defaults to **5 rows** and uses `SELECT TOP`.
- `run_query` defaults to **100 rows** per call.

## SupabaseToolSet

`SupabaseToolSet` is a single connector spanning Supabase Platform's
public surfaces: PostgREST data access (incl. RPC and pgvector
matching), GoTrue auth admin, Storage objects, and Edge Functions.
Authentication uses the project's `anon` or `service_role` key (passed
as `apikey`) plus an optional separate access token for end-user
impersonation.

```python
from maivn_tools import SupabaseToolSet

connector = SupabaseToolSet(
    project_url="https://abcd.supabase.co",
    api_key=secrets["SUPABASE_SERVICE_ROLE"],
)
```

> Service-role keys grant unrestricted access; treat them as
> destructive credentials.

PostgREST data tools: `select(table, ...)`, `insert(table, rows, ...)`,
`update(table, filter, values, ...)`, `delete(table, filter, ...)`
(destructive), `rpc(function_name, args, ...)`,
`match_vectors(function_name, embedding, ...)`.

Auth admin tools: `list_users(include_metadata, include_ids)`,
`get_user(user_id)`, `create_user(...)`, `update_user(user_id, fields)`,
`delete_user(user_id)` (destructive), `invite_user(email, ...)`.

Storage tools: `list_buckets(include_metadata)`, `create_bucket(...)`,
`delete_bucket(bucket_id)` (destructive),
`list_objects(bucket_id, include_metadata, ...)`,
`create_signed_url(bucket_id, path, ...)`,
`delete_object(bucket_id, path)` (destructive).

Edge Functions: `invoke_function(function_name, body, ...)`.

### Agent-ready behavior

- `list_users`, `list_buckets`, and `list_objects` return compact
  summaries by default with stable refs (`user_ref`, `bucket_ref`,
  `object_ref`). User-facing fields always shown: user `email` /
  `phone` / `role`, bucket `name`, object `name` (the bucket-relative
  path), `size`, `content_type`. Pass `include_metadata=False` for the
  raw GoTrue / Supabase response.
- For `list_users`, raw UUIDs are hidden by default -- set
  `include_ids=True` to expose `user_id`. `update_user`, `delete_user`,
  and `get_user` accept either the raw UUID string or the dict from
  `list_users(include_ids=True)`.
- `list_buckets` / `list_objects` always show the bucket / object names
  (those are the user-facing identifiers -- not internal handles).
  `delete_bucket`, `delete_object`, and `create_signed_url` accept
  either the raw ID / path string or the dict returned by the
  corresponding list.
- Default `per_page` for `list_users` is **25**; default `limit` for
  `list_objects` is **25**; default PostgREST `select` `limit` is
  **100**.
- Destructive tools: `delete` (PostgREST row delete), `delete_user`,
  `delete_bucket`, `delete_object`. `delete` and `update` require a
  non-empty `filter` so a full-table mutation is rejected up front.

Example:

```python
users = connector.list_users()
# {"users": [{"user_ref": "user_1", "email": "alice@example.com", "role": "authenticated", ...}, ...], "page": 1, "per_page": 25}
users_with_ids = connector.list_users(include_ids=True)
connector.update_user(users_with_ids["users"][0], {"banned_until": "..."})
```
