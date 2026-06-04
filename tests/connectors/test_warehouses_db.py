# pyright: strict
from __future__ import annotations

from typing import Any

import pytest

from maivn_tools.connectors.bigquery import BigQueryToolSet
from maivn_tools.connectors.databases import MySQLToolSet, SQLServerToolSet
from maivn_tools.connectors.snowflake import SnowflakeToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Fake DB-API


class _FakeCursor:
    description: Any

    def __init__(self, rows: list[Any], columns: list[str]) -> None:
        self._rows = rows
        self.description = [(c,) for c in columns]
        self.last_sql: str | None = None
        self.last_params: Any = None

    def execute(self, query: str, params: Any = ...) -> Any:
        self.last_sql = query
        self.last_params = params
        return None

    def fetchmany(self, size: int) -> list[Any]:
        out = self._rows[:size]
        self._rows = self._rows[size:]
        return out

    def close(self) -> None:
        pass


class _FakeConnection:
    def __init__(self, rows: list[Any] | None = None, columns: list[str] | None = None) -> None:
        self._cursor = _FakeCursor(rows or [], columns or [])
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


# MARK: - MySQL


def test_mysql_requires_dsn_or_factory() -> None:
    with pytest.raises(ValueError):
        MySQLToolSet()
    with pytest.raises(ValueError):
        MySQLToolSet(row_limit=0, connection_factory=lambda: _FakeConnection())


def test_mysql_list_tables_and_describe() -> None:
    tables_conn = _FakeConnection(rows=[("users", "BASE TABLE")], columns=["name", "type"])
    desc_conn = _FakeConnection(
        rows=[("id", "int", False, None, "PRI"), ("name", "varchar", True, None, "")],
        columns=["name", "type", "nullable", "default", "key"],
    )
    connector = MySQLToolSet(
        connection_factory=lambda: tables_conn if not desc_conn.closed else desc_conn,
    )
    result = connector.list_tables()
    assert result["tables"][0]["name"] == "users"
    assert result["tables"][0]["table_ref"] == "table_1"
    # next call uses describe
    connector_describe = MySQLToolSet(connection_factory=lambda: desc_conn)
    described = connector_describe.describe_table("users")
    assert described["primary_key"] == ["id"]


def test_mysql_run_query_validation() -> None:
    connector = MySQLToolSet(connection_factory=lambda: _FakeConnection())
    with pytest.raises(ValueError):
        connector.run_query("INSERT INTO users VALUES (1)")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1; SELECT 2")
    with pytest.raises(ValueError):
        connector.run_query("")


def test_mysql_run_query_parameters() -> None:
    conn = _FakeConnection(rows=[(1, "a")], columns=["id", "name"])
    connector = MySQLToolSet(connection_factory=lambda: conn)
    result = connector.run_query("SELECT id, name FROM users WHERE id = %s", [1])
    assert result["rows"] == [{"id": 1, "name": "a"}]


def test_mysql_sample_and_count() -> None:
    conn1 = _FakeConnection(rows=[(1, "a")], columns=["id", "name"])
    conn2 = _FakeConnection(rows=[(42,)], columns=["row_count"])
    connector = MySQLToolSet(connection_factory=lambda: conn1)
    result = connector.sample_table("users", limit=5)
    assert result["rows"][0]["name"] == "a"
    connector2 = MySQLToolSet(connection_factory=lambda: conn2)
    cnt = connector2.count_rows("users")
    assert cnt["row_count"] == 42
    with pytest.raises(ValueError):
        connector.sample_table("users", limit=0)


def test_mysql_list_indexes_and_databases_and_version() -> None:
    conn1 = _FakeConnection(rows=[("idx_name", 1)], columns=["index_name", "non_unique"])
    conn2 = _FakeConnection(rows=[("dbname",)], columns=["Database"])
    conn3 = _FakeConnection(rows=[("8.0.30", "dbname")], columns=["version", "database"])
    connector = MySQLToolSet(connection_factory=lambda: conn1)
    connector.list_indexes("users")
    connector2 = MySQLToolSet(connection_factory=lambda: conn2)
    connector2.list_databases()
    connector3 = MySQLToolSet(connection_factory=lambda: conn3)
    v = connector3.server_version()
    assert v["version"] == "8.0.30"


def test_mysql_explain_disallows_analyze() -> None:
    conn = _FakeConnection(rows=[], columns=[])
    connector = MySQLToolSet(connection_factory=lambda: conn)
    with pytest.raises(ValueError):
        connector.explain_query("SELECT 1", analyze=True)


# MARK: - SQL Server


def test_sqlserver_requires_conn() -> None:
    with pytest.raises(ValueError):
        SQLServerToolSet()


def test_sqlserver_run_query_validation() -> None:
    connector = SQLServerToolSet(connection_factory=lambda: _FakeConnection())
    with pytest.raises(ValueError):
        connector.run_query("EXEC sp_who")
    with pytest.raises(ValueError):
        connector.run_query("DROP TABLE users")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1; SELECT 2")


def test_sqlserver_listing_and_describe() -> None:
    list_conn = _FakeConnection(rows=[("users", "BASE TABLE")], columns=["name", "type"])
    desc_cols = _FakeConnection(
        rows=[("id", "int", False, None)],
        columns=["name", "type", "nullable", "default"],
    )
    pk = _FakeConnection(rows=[("id",)], columns=["name"])
    connector = SQLServerToolSet(connection_factory=lambda: list_conn)
    connector.list_tables()
    # describe_table opens 2 connections; emulate with a counter
    state = {"calls": 0}

    def factory() -> Any:
        state["calls"] += 1
        return desc_cols if state["calls"] == 1 else pk

    connector_describe = SQLServerToolSet(connection_factory=factory)
    described = connector_describe.describe_table("users")
    assert described["primary_key"] == ["id"]


def test_sqlserver_sample_count_version_views() -> None:
    sample_conn = _FakeConnection(rows=[(1,)], columns=["id"])
    count_conn = _FakeConnection(rows=[(5,)], columns=["row_count"])
    version_conn = _FakeConnection(rows=[("v", "db")], columns=["version", "database"])
    views_conn = _FakeConnection(rows=[("vw",)], columns=["name"])
    schemas_conn = _FakeConnection(rows=[("dbo",)], columns=["name"])
    dbs_conn = _FakeConnection(rows=[("main",)], columns=["name"])
    SQLServerToolSet(connection_factory=lambda: sample_conn).sample_table("users", limit=1)
    SQLServerToolSet(connection_factory=lambda: count_conn).count_rows("users")
    SQLServerToolSet(connection_factory=lambda: version_conn).server_version()
    SQLServerToolSet(connection_factory=lambda: views_conn).list_views()
    SQLServerToolSet(connection_factory=lambda: schemas_conn).list_schemas()
    SQLServerToolSet(connection_factory=lambda: dbs_conn).list_databases()


# MARK: - Snowflake


def _snowflake() -> tuple[SnowflakeToolSet, MockTransport]:
    transport = MockTransport()
    return (
        SnowflakeToolSet(
            account="acme.us-east-1",
            token="t",
            warehouse="WH",
            database="DB",
            schema="PUBLIC",
            role="ANALYST",
            transport=transport,
        ),
        transport,
    )


def test_snowflake_validates_inputs() -> None:
    with pytest.raises(ValueError):
        SnowflakeToolSet(account="", token="t")
    with pytest.raises(ValueError):
        SnowflakeToolSet(account="a", token="")


def test_snowflake_run_query_validates() -> None:
    connector, _ = _snowflake()
    with pytest.raises(ValueError):
        connector.run_query("DROP TABLE x")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1; SELECT 2")
    with pytest.raises(ValueError):
        connector.run_query("")


def test_snowflake_run_query_sets_defaults() -> None:
    connector, transport = _snowflake()
    transport.enqueue(json_response({"data": []}))
    connector.run_query("SELECT 1")
    body = transport.requests[0].json_body
    assert body["statement"] == "SELECT 1"
    assert body["warehouse"] == "WH"
    assert body["database"] == "DB"
    assert body["role"] == "ANALYST"
    assert transport.requests[0].headers["X-Snowflake-Authorization-Token-Type"] == "OAUTH"


def test_snowflake_async_and_get_statement() -> None:
    connector, transport = _snowflake()
    transport.enqueue(json_response({"statementHandle": "abc"}))
    transport.enqueue(json_response({"status": "running"}))
    transport.enqueue(json_response({"cancelled": True}))
    connector.submit_async_query("SELECT 1")
    connector.get_statement("abc", partition=2)
    connector.cancel_statement("abc")
    assert transport.requests[0].params == {"async": "true"}
    assert transport.requests[1].params == {"partition": 2}
    assert transport.requests[2].url.endswith("/cancel")
    with pytest.raises(ValueError):
        connector.get_statement("")
    with pytest.raises(ValueError):
        connector.cancel_statement("")


def test_snowflake_catalog_queries() -> None:
    connector, transport = _snowflake()
    for _ in range(8):
        transport.enqueue(json_response({"data": []}))
    connector.list_databases()
    connector.list_schemas(database="DB")
    connector.list_tables(database="DB", schema="PUBLIC")
    connector.list_views(database="DB", schema="PUBLIC")
    connector.describe_table("USERS", database="DB", schema="PUBLIC")
    connector.list_warehouses()
    connector.server_version()
    connector.list_tables()
    sqls = [r.json_body["statement"] for r in transport.requests]
    assert sqls[0] == "SHOW DATABASES"
    assert sqls[1] == "SHOW SCHEMAS IN DATABASE DB"
    assert "SHOW TABLES IN SCHEMA DB.PUBLIC" in sqls[2]
    assert "DESCRIBE TABLE DB.PUBLIC.USERS" in sqls[4]
    with pytest.raises(ValueError):
        connector.list_schemas(database="")
    with pytest.raises(ValueError):
        connector.describe_table("bogus name", database="DB", schema="PUBLIC")


# MARK: - BigQuery


def _bigquery() -> tuple[BigQueryToolSet, MockTransport]:
    transport = MockTransport()
    return (
        BigQueryToolSet(token="t", project_id="my-proj", transport=transport),
        transport,
    )


def test_bigquery_validates_project_id() -> None:
    with pytest.raises(ValueError):
        BigQueryToolSet(token="t", project_id="")
    with pytest.raises(ValueError):
        BigQueryToolSet(token="t", project_id="bad name!")


def test_bigquery_datasets_and_tables() -> None:
    connector, transport = _bigquery()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.list_datasets(all_datasets=True, filter="labels.env:prod")
    connector.get_dataset("sales")
    connector.list_tables("sales")
    connector.get_table("sales", "orders")
    assert transport.requests[0].params["all"] == "true"
    assert transport.requests[2].url.endswith("/datasets/sales/tables")
    with pytest.raises(ValueError):
        connector.get_dataset("")
    with pytest.raises(ValueError):
        connector.list_tables("")
    with pytest.raises(ValueError):
        connector.get_table("ok", "bad name")


def test_bigquery_query_and_jobs() -> None:
    connector, transport = _bigquery()
    for _ in range(6):
        transport.enqueue(json_response({"jobReference": {"jobId": "j1"}}))
    connector.run_query(
        "SELECT 1 AS x",
        location="US",
        parameters=[{"name": "p", "parameterValue": {"value": "1"}}],
    )
    connector.run_query("SELECT 2", dry_run=True)
    connector.get_query_results("j1", location="US", page_token="t")
    connector.get_job("j1", location="US")
    connector.list_jobs(all_users=True, state_filter=["running", "pending"])
    connector.cancel_job("j1", location="US")
    body0 = transport.requests[0].json_body
    assert body0["query"] == "SELECT 1 AS x"
    assert body0["location"] == "US"
    assert body0["queryParameters"]
    assert transport.requests[1].json_body["dryRun"] is True
    assert transport.requests[4].params["stateFilter"] == "running,pending"
    with pytest.raises(ValueError):
        connector.run_query("INSERT INTO t VALUES (1)")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1", max_results=0)
    with pytest.raises(ValueError):
        connector.get_query_results("")
    with pytest.raises(ValueError):
        connector.get_job("")
    with pytest.raises(ValueError):
        connector.cancel_job("")


def test_bigquery_table_data_and_routines() -> None:
    connector, transport = _bigquery()
    for _ in range(3):
        transport.enqueue(json_response({}))
    connector.get_table_data(
        "sales",
        "orders",
        max_results=20,
        page_token="t",
        selected_fields=["id", "amount"],
    )
    connector.list_routines("sales")
    connector.list_models("sales")
    assert transport.requests[0].params["selectedFields"] == "id,amount"


# MARK: - Agent-ready summary defaults


def test_mysql_list_tables_concise_summaries() -> None:
    """Agent-ready: list_tables returns table_ref + user-facing name."""
    conn = _FakeConnection(
        rows=[("users", "BASE TABLE"), ("orders", "BASE TABLE")],
        columns=["name", "type"],
    )
    connector = MySQLToolSet(connection_factory=lambda: conn)
    result = connector.list_tables()
    assert set(result) == {"tables", "returned", "total", "truncated"}
    assert result["tables"][0]["table_ref"] == "table_1"
    # Schema/table names are user-facing — always keep them.
    assert result["tables"][0]["name"] == "users"


def test_mysql_list_databases_concise_summaries() -> None:
    conn = _FakeConnection(rows=[("information_schema",), ("app",)], columns=["Database"])
    connector = MySQLToolSet(connection_factory=lambda: conn)
    result = connector.list_databases()
    assert set(result) == {"databases", "returned", "total", "truncated"}
    assert result["databases"][0]["database_ref"] == "database_1"


def test_mysql_sample_table_default_is_small_n() -> None:
    conn = _FakeConnection(rows=[(i, str(i)) for i in range(10)], columns=["id", "name"])
    connector = MySQLToolSet(connection_factory=lambda: conn)
    result = connector.sample_table("users")
    # Default sample is 5 rows.
    assert result["row_count"] <= 5


def test_sqlserver_list_tables_concise_summaries() -> None:
    conn = _FakeConnection(
        rows=[("users", "BASE TABLE"), ("orders", "BASE TABLE")],
        columns=["name", "type"],
    )
    connector = SQLServerToolSet(connection_factory=lambda: conn)
    result = connector.list_tables()
    assert set(result) == {"tables", "returned", "total", "truncated"}
    assert result["tables"][0]["table_ref"] == "table_1"
    # Schema/table names are user-facing — always keep them.
    assert result["tables"][0]["name"] == "users"
    assert result["tables"][0]["schema"] == "dbo"


def test_sqlserver_list_databases_concise_summaries() -> None:
    conn = _FakeConnection(rows=[("master",), ("appdb",)], columns=["name"])
    connector = SQLServerToolSet(connection_factory=lambda: conn)
    result = connector.list_databases()
    assert set(result) == {"databases", "returned", "total", "truncated"}
    assert result["databases"][0]["database_ref"] == "database_1"


def test_sqlserver_sample_table_default_is_small_n() -> None:
    conn = _FakeConnection(rows=[(i,) for i in range(10)], columns=["id"])
    connector = SQLServerToolSet(connection_factory=lambda: conn)
    result = connector.sample_table("users")
    # Default sample is 5 rows.
    assert result["row_count"] <= 5


def test_snowflake_list_tables_concise_summaries() -> None:
    """Agent-ready: list_tables wraps Snowflake SHOW output in a summary envelope."""
    connector, transport = _snowflake()
    transport.enqueue(
        json_response(
            {
                "resultSetMetaData": {
                    "rowType": [
                        {"name": "name"},
                        {"name": "database_name"},
                        {"name": "schema_name"},
                        {"name": "kind"},
                        {"name": "rows"},
                        {"name": "bytes"},
                    ]
                },
                "data": [
                    ["USERS", "DB", "PUBLIC", "TABLE", 100, 1024],
                    ["ORDERS", "DB", "PUBLIC", "TABLE", 200, 2048],
                ],
            }
        )
    )
    result = connector.list_tables(database="DB", schema="PUBLIC")
    assert set(result) == {"tables", "returned", "total", "truncated"}
    assert result["tables"][0]["table_ref"] == "table_1"
    # User-facing identifier kept.
    assert result["tables"][0]["name"] == "USERS"
    assert result["tables"][0]["database_name"] == "DB"


def test_snowflake_destructive_tag_present_on_cancel_statement() -> None:
    """cancel_statement is the one destructive tool on Snowflake."""
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _snowflake()
    cancel_opts = get_toolify_options(connector.cancel_statement)
    assert cancel_opts is not None
    assert cancel_opts.destructive is True
    # All other tools are read-only.
    read_methods = [
        connector.run_query,
        connector.submit_async_query,
        connector.get_statement,
        connector.list_databases,
        connector.list_schemas,
        connector.list_tables,
        connector.list_views,
        connector.describe_table,
        connector.list_warehouses,
        connector.server_version,
    ]
    for method in read_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False


def test_bigquery_list_datasets_concise_summaries() -> None:
    """Agent-ready: list_datasets returns compact summaries by default."""
    connector, transport = _bigquery()
    transport.enqueue(
        json_response(
            {
                "datasets": [
                    {
                        "datasetReference": {"datasetId": "sales", "projectId": "p"},
                        "location": "US",
                        "friendlyName": "Sales",
                    },
                    {
                        "datasetReference": {"datasetId": "ops", "projectId": "p"},
                        "location": "US",
                    },
                ],
                "nextPageToken": "tok",
            }
        )
    )
    result = connector.list_datasets()
    assert "datasets" in result
    assert result["datasets"][0]["dataset_ref"] == "dataset_1"
    # Schema/dataset names are user-facing — always present.
    assert result["datasets"][0]["dataset_id"] == "sales"
    assert result["nextPageToken"] == "tok"


def test_bigquery_list_datasets_raw_mode() -> None:
    """include_metadata=False returns the raw BigQuery response."""
    connector, transport = _bigquery()
    raw = {
        "datasets": [{"datasetReference": {"datasetId": "sales"}}],
        "nextPageToken": "tok",
    }
    transport.enqueue(json_response(raw))
    result = connector.list_datasets(include_metadata=False)
    assert result == raw


def test_bigquery_list_tables_concise_summaries() -> None:
    connector, transport = _bigquery()
    transport.enqueue(
        json_response(
            {
                "tables": [
                    {
                        "tableReference": {
                            "tableId": "orders",
                            "datasetId": "sales",
                            "projectId": "p",
                        },
                        "type": "TABLE",
                    }
                ]
            }
        )
    )
    result = connector.list_tables("sales")
    assert "tables" in result
    assert result["tables"][0]["table_ref"] == "table_1"
    # User-facing identifiers preserved.
    assert result["tables"][0]["table_id"] == "orders"
    assert result["tables"][0]["dataset_id"] == "sales"


def test_bigquery_destructive_tag_present_on_cancel_job() -> None:
    """cancel_job is the one destructive tool on BigQuery."""
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _bigquery()
    cancel_opts = get_toolify_options(connector.cancel_job)
    assert cancel_opts is not None
    assert cancel_opts.destructive is True
    # All other tools are read-only.
    read_methods = [
        connector.list_datasets,
        connector.get_dataset,
        connector.list_tables,
        connector.get_table,
        connector.get_table_data,
        connector.run_query,
        connector.get_query_results,
        connector.get_job,
        connector.list_jobs,
        connector.list_routines,
        connector.list_models,
    ]
    for method in read_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False


def test_bigquery_get_table_data_default_small() -> None:
    """Agent-ready: get_table_data preview defaults to small N (5)."""
    connector, transport = _bigquery()
    transport.enqueue(json_response({"rows": []}))
    connector.get_table_data("sales", "orders")
    params = transport.requests[0].params
    assert params["maxResults"] == 5
