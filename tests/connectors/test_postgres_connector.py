# pyright: strict
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from maivn_tools.connectors.databases import PostgresToolSet


class FakeCursor:
    def __init__(self, plan: list[dict[str, Any]]) -> None:
        self._plan = list(plan)
        self.description: list[tuple[str, ...]] | None = None
        self.executed: list[tuple[str, Any]] = []
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))
        if "SET TRANSACTION" in query.upper():
            return
        if not self._plan:
            self.description = None
            self._rows = []
            return
        match = self._plan.pop(0)
        self.description = [(name,) for name in match["columns"]]
        self._rows = list(match["rows"])

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        if not self._rows:
            return []
        head = self._rows[:size]
        self._rows = self._rows[size:]
        return head

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, plan: list[dict[str, Any]]) -> None:
        # Plan is shared across cursors AND across connections via the
        # outer factory closure so successive _run_select calls consume
        # the next queued response.
        self._plan = plan
        self.closed = False

    def cursor(self) -> FakeCursor:
        return _SharedCursor(self._plan)

    def close(self) -> None:
        self.closed = True


class _SharedCursor(FakeCursor):
    def __init__(self, shared_plan: list[dict[str, Any]]) -> None:
        self._shared = shared_plan
        self.description = None
        self.executed = []
        self._rows = []

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))
        if "SET TRANSACTION" in query.upper():
            return
        if not self._shared:
            self.description = None
            self._rows = []
            return
        match = self._shared.pop(0)
        self.description = [(name,) for name in match["columns"]]
        self._rows = list(match["rows"])


def make_factory(plan: list[dict[str, Any]]) -> Callable[[], FakeConnection]:
    return lambda: FakeConnection(plan)


def test_postgres_connector_requires_dsn_or_factory() -> None:
    with pytest.raises(ValueError):
        PostgresToolSet()


def test_postgres_connector_validates_row_limit() -> None:
    with pytest.raises(ValueError):
        PostgresToolSet(dsn="x", row_limit=0)


def test_run_query_returns_named_rows() -> None:
    plan = [
        {
            "columns": ["id", "name"],
            "rows": [(1, "Alice"), (2, "Bob")],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.run_query("SELECT id, name FROM users")
    assert result["columns"] == ["id", "name"]
    assert result["rows"] == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    assert result["truncated"] is False


def test_run_query_truncates_to_row_limit() -> None:
    plan = [
        {
            "columns": ["id"],
            "rows": [(i,) for i in range(5)],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=2)
    result = connector.run_query("SELECT id FROM users")
    assert result["row_count"] == 2
    assert result["truncated"] is True


def test_run_query_rejects_writes() -> None:
    connector = PostgresToolSet(connection_factory=make_factory([]), row_limit=1)
    with pytest.raises(ValueError):
        connector.run_query("INSERT INTO users VALUES (1)")
    with pytest.raises(ValueError):
        connector.run_query("DROP TABLE users")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1; SELECT 2")


def test_describe_table_returns_columns_and_pk() -> None:
    plan = [
        {
            "columns": ["name", "type", "nullable", "default"],
            "rows": [
                ("id", "integer", False, None),
                ("name", "text", False, None),
            ],
        },
        {
            "columns": ["column_name"],
            "rows": [("id",)],
        },
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=20)
    info = connector.describe_table(name="users")
    assert info["primary_key"] == ["id"]
    assert {column["name"] for column in info["columns"]} == {"id", "name"}


def test_describe_table_raises_for_missing_table() -> None:
    plan = [{"columns": ["name", "type", "nullable", "default"], "rows": []}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    with pytest.raises(LookupError):
        connector.describe_table(name="ghost")


def test_list_schemas_returns_rows() -> None:
    plan = [{"columns": ["name"], "rows": [("public",), ("reporting",)]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.list_schemas()
    names = [s["name"] for s in result["schemas"]]
    assert names == ["public", "reporting"]
    assert result["schemas"][0]["schema_ref"] == "schema_1"
    assert result["returned"] == 2
    assert result["total"] == 2
    assert result["truncated"] is False


def test_list_views_unions_views_and_matviews() -> None:
    plan = [{"columns": ["name"], "rows": [("v_users",), ("mv_orders",)]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.list_views(schema="public")
    assert {r["name"] for r in result["views"]} == {"v_users", "mv_orders"}
    # User-facing schema is preserved on every entry.
    assert all(r["schema"] == "public" for r in result["views"])
    assert result["views"][0]["view_ref"] == "view_1"


def test_list_indexes_unfiltered_and_filtered() -> None:
    plan = [
        {
            "columns": ["schema", "table", "name", "definition"],
            "rows": [("public", "users", "users_pkey", "CREATE UNIQUE INDEX ...")],
        },
        {
            "columns": ["schema", "table", "name", "definition"],
            "rows": [("public", "users", "users_pkey", "CREATE UNIQUE INDEX ...")],
        },
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    all_rows = connector.list_indexes()
    table_rows = connector.list_indexes(table="users")
    assert all_rows["indexes"][0]["name"] == "users_pkey"
    assert table_rows["indexes"][0]["table"] == "users"
    assert all_rows["indexes"][0]["index_ref"].startswith("index_")


def test_list_foreign_keys_returns_rows() -> None:
    plan = [
        {
            "columns": ["name", "column", "foreign_schema", "foreign_table", "foreign_column"],
            "rows": [("orders_user_id_fkey", "user_id", "public", "users", "id")],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    rows = connector.list_foreign_keys(name="orders")
    assert rows[0]["foreign_table"] == "users"


def test_list_extensions_returns_rows() -> None:
    plan = [{"columns": ["name", "version"], "rows": [("pg_trgm", "1.6")]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    assert connector.list_extensions() == [{"name": "pg_trgm", "version": "1.6"}]


def test_get_table_size_returns_bytes() -> None:
    plan = [
        {
            "columns": ["total_bytes", "table_bytes"],
            "rows": [(2048, 1024)],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    info = connector.get_table_size(name="users")
    assert info["total_bytes"] == 2048
    assert info["table_bytes"] == 1024


def test_get_table_size_missing_raises() -> None:
    plan = [{"columns": ["total_bytes", "table_bytes"], "rows": []}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    with pytest.raises(LookupError):
        connector.get_table_size(name="ghost")


def test_explain_query_rejects_analyze() -> None:
    connector = PostgresToolSet(connection_factory=make_factory([]), row_limit=10)
    with pytest.raises(ValueError):
        connector.explain_query("SELECT 1", analyze=True)


def test_explain_query_returns_plan_rows() -> None:
    plan = [{"columns": ["QUERY PLAN"], "rows": [('[{"Plan": {...}}]',)]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.explain_query("SELECT 1")
    assert result["rows"]


def test_server_version_returns_metadata() -> None:
    plan = [{"columns": ["version", "database"], "rows": [("PG 16", "mydb")]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    info = connector.server_version()
    assert info["version"] == "PG 16"
    assert info["database"] == "mydb"


def test_sample_table_validates_limit() -> None:
    connector = PostgresToolSet(connection_factory=make_factory([]), row_limit=10)
    with pytest.raises(ValueError):
        connector.sample_table(name="users", limit=0)
    with pytest.raises(ValueError):
        connector.sample_table(name="users", limit=999)


def test_sample_table_delegates_to_run_query() -> None:
    plan = [
        {
            "columns": ["id"],
            "rows": [(1,), (2,)],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.sample_table(name="users", limit=2)
    assert result["row_count"] == 2


def test_count_rows_returns_count() -> None:
    plan = [{"columns": ["row_count"], "rows": [(42,)]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    info = connector.count_rows(name="users")
    assert info["row_count"] == 42


def test_list_tables_passes_schema_parameter() -> None:
    captured: list[tuple[str, Any]] = []

    class CapturingCursor(FakeCursor):
        def execute(self, query: str, params: Any = None) -> None:
            captured.append((query, params))
            super().execute(query, params)

    class CapturingConn(FakeConnection):
        def cursor(self) -> CapturingCursor:
            return CapturingCursor(self._plan)

    plan = [{"columns": ["name", "type"], "rows": [("users", "BASE TABLE")]}]
    connector = PostgresToolSet(connection_factory=lambda: CapturingConn(plan))
    result = connector.list_tables(schema="reporting")
    assert result["tables"] == [
        {
            "table_ref": "table_1",
            "name": "users",
            "type": "BASE TABLE",
            "schema": "reporting",
        }
    ]
    assert captured[-1][1] == ("reporting",)


def test_postgres_list_tables_concise_summaries() -> None:
    """Agent-ready: list_tables returns table_ref + user-facing schema/name."""
    plan = [
        {
            "columns": ["name", "type"],
            "rows": [("users", "BASE TABLE"), ("orders", "BASE TABLE")],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=20)
    result = connector.list_tables()
    assert set(result) == {"tables", "returned", "total", "truncated"}
    for entry in result["tables"]:
        assert entry["table_ref"].startswith("table_")
        # Schema/table names are user-facing — always keep them.
        assert entry["name"]
        assert entry["schema"] == "public"
        assert entry["type"]


def test_postgres_list_tables_paginates_with_max_results() -> None:
    plan = [
        {
            "columns": ["name", "type"],
            "rows": [("users", "BASE TABLE"), ("orders", "BASE TABLE")],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=20)
    result = connector.list_tables(max_results=1)
    assert result["returned"] == 1
    assert result["total"] == 2
    assert result["truncated"] is True


def test_postgres_sample_table_defaults_to_small_n() -> None:
    """Agent-ready: sample_table defaults to small N (5)."""
    plan = [
        {
            "columns": ["id"],
            "rows": [(i,) for i in range(10)],
        }
    ]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=500)
    result = connector.sample_table(name="users")
    # Default sample is 5 rows.
    assert result["row_count"] == 5


def test_postgres_destructive_tag_absent() -> None:
    """Postgres connector is read-only: no destructive tools registered."""
    from maivn._internal.utils.toolset import get_toolify_options

    connector = PostgresToolSet(connection_factory=make_factory([]), row_limit=1)
    tool_methods = [
        connector.list_tables,
        connector.describe_table,
        connector.run_query,
        connector.list_views,
        connector.list_indexes,
        connector.list_foreign_keys,
        connector.list_schemas,
        connector.list_extensions,
        connector.get_table_size,
        connector.explain_query,
        connector.server_version,
        connector.sample_table,
        connector.count_rows,
    ]
    for method in tool_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False


def test_postgres_sample_table_rejects_identifier_injection() -> None:
    """sample_table interpolates name/schema into quoted identifiers; a quote
    break-out must be rejected before any SQL is issued."""
    connector = PostgresToolSet(connection_factory=make_factory([]), row_limit=10)
    with pytest.raises(ValueError):
        connector.sample_table(
            name='users" UNION SELECT table_name, 1 FROM information_schema.tables --'
        )
    with pytest.raises(ValueError):
        connector.sample_table(name="users", schema='public" UNION SELECT 1 --')


def test_postgres_count_rows_rejects_identifier_injection() -> None:
    """count_rows builds its SELECT directly via _run_select, bypassing the
    read-only SQL guard; identifier validation must stop the break-out."""
    connector = PostgresToolSet(connection_factory=make_factory([]), row_limit=10)
    with pytest.raises(ValueError):
        connector.count_rows(name="users\" UNION SELECT current_setting('x'), 1 --")
    with pytest.raises(ValueError):
        connector.count_rows(name="users", schema='evil"."x')


def test_postgres_sample_table_accepts_valid_identifier_with_schema() -> None:
    """Regression: legitimate identifiers must still pass validation and run."""
    plan = [{"columns": ["id"], "rows": [(1,), (2,)]}]
    connector = PostgresToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.sample_table(name="users", schema="public", limit=2)
    assert result["row_count"] == 2
