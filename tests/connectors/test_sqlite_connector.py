# pyright: strict
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from maivn_tools.connectors.databases import SQLiteToolSet


@pytest.fixture
def sample_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        );
        CREATE INDEX idx_users_email ON users(email);
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            total REAL
        );
        INSERT INTO users (id, name, email) VALUES
            (1, 'Alice', 'alice@example.test'),
            (2, 'Bob', 'bob@example.test'),
            (3, 'Carol', NULL);
        INSERT INTO orders (id, user_id, total) VALUES
            (1, 1, 9.99),
            (2, 2, 19.99);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_sqlite_connector_metadata_and_validation(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    assert connector.metadata.name == "sqlite"
    assert connector.database == str(sample_db)
    with pytest.raises(ValueError):
        SQLiteToolSet(sample_db, row_limit=0)
    with pytest.raises(ValueError):
        SQLiteToolSet(sample_db, query_timeout_seconds=0)


def test_sqlite_connector_is_a_toolset(sample_db: Path) -> None:
    from maivn._internal.utils.toolset import get_toolify_options, get_toolset_options

    opts = get_toolset_options(SQLiteToolSet)
    assert opts is not None
    assert opts.prefix == "sqlite"

    connector = SQLiteToolSet(sample_db)
    assert get_toolify_options(connector.list_tables) is not None
    assert get_toolify_options(connector.describe_table) is not None
    assert get_toolify_options(connector.run_query) is not None


def test_list_tables_filters_internal_tables(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    result = connector.list_tables()
    names = {table["name"] for table in result["tables"]}
    assert names == {"users", "orders"}
    # Agent-ready summary envelope: refs, totals, truncated.
    refs = {table["table_ref"] for table in result["tables"]}
    assert refs == {"table_1", "table_2"}
    assert result["returned"] == 2
    assert result["total"] == 2
    assert result["truncated"] is False


def test_list_tables_paginates_with_max_results(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    result = connector.list_tables(max_results=1)
    assert result["returned"] == 1
    assert result["total"] == 2
    assert result["truncated"] is True
    assert result["tables"][0]["table_ref"] == "table_1"


def test_describe_table_returns_columns_and_indexes(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    info = connector.describe_table(name="users")
    column_names = {column["name"] for column in info["columns"]}
    assert column_names == {"id", "name", "email"}
    pks = {column["name"] for column in info["columns"] if column["primary_key"]}
    assert pks == {"id"}
    index_names = {index["name"] for index in info["indexes"]}
    assert "idx_users_email" in index_names


def test_describe_table_rejects_bad_identifiers_and_missing_tables(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    with pytest.raises(ValueError):
        connector.describe_table(name="users; drop")
    with pytest.raises(LookupError):
        connector.describe_table(name="missing")


def test_run_query_returns_rows_and_columns(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    result = connector.run_query("SELECT id, name FROM users ORDER BY id")
    assert result["columns"] == ["id", "name"]
    assert [row["name"] for row in result["rows"]] == ["Alice", "Bob", "Carol"]
    assert result["truncated"] is False


def test_run_query_respects_row_limit(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db, row_limit=2)
    result = connector.run_query("SELECT id FROM users ORDER BY id")
    assert result["row_count"] == 2
    assert result["truncated"] is True
    # An override above the configured ceiling is clamped to the ceiling.
    override = connector.run_query("SELECT id FROM users ORDER BY id", row_limit=10)
    assert override["row_count"] == 2
    assert override["truncated"] is True


def test_run_query_per_call_override_can_widen_within_ceiling(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db, row_limit=500)
    # Default per-call cap is 100 rows even though ceiling is 500.
    result = connector.run_query("SELECT id FROM users ORDER BY id", row_limit=10)
    assert result["row_count"] == 3
    assert result["truncated"] is False


def test_run_query_supports_positional_and_named_params(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    pos = connector.run_query("SELECT name FROM users WHERE id = ?", [2])
    assert pos["rows"] == [{"name": "Bob"}]
    named = connector.run_query(
        "SELECT name FROM users WHERE id = :uid",
        {"uid": 1},
    )
    assert named["rows"] == [{"name": "Alice"}]


def test_run_query_rejects_writes_and_compound_statements(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    with pytest.raises(ValueError):
        connector.run_query("UPDATE users SET name = 'x'")
    with pytest.raises(ValueError):
        connector.run_query("DELETE FROM users")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1; SELECT 2")
    with pytest.raises(ValueError):
        connector.run_query("")
    with pytest.raises(ValueError):
        connector.run_query("SELECT 1", row_limit=0)


def test_pragma_query_only_blocks_runtime_mutation(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    with pytest.raises(ValueError):
        # Forbidden keyword check trips first.
        connector.run_query("PRAGMA wal_checkpoint")


@pytest.fixture
def view_db(sample_db: Path) -> Path:
    conn = sqlite3.connect(sample_db)
    conn.execute(
        "CREATE VIEW v_user_orders AS SELECT * FROM users u JOIN orders o ON o.user_id = u.id"
    )
    conn.commit()
    conn.close()
    return sample_db


def test_list_views_returns_user_views(view_db: Path) -> None:
    connector = SQLiteToolSet(view_db)
    result = connector.list_views()
    assert {v["name"] for v in result["views"]} == {"v_user_orders"}
    assert result["views"][0]["view_ref"] == "view_1"
    assert result["returned"] == 1
    assert result["total"] == 1


def test_list_indexes_unfiltered_and_filtered(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    all_indexes = connector.list_indexes()
    user_indexes = connector.list_indexes(table="users")
    assert "idx_users_email" in {i["name"] for i in all_indexes["indexes"]}
    assert all(i["table"] == "users" for i in user_indexes["indexes"])
    assert all_indexes["indexes"][0]["index_ref"].startswith("index_")


def test_list_indexes_rejects_bad_table(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    with pytest.raises(ValueError):
        connector.list_indexes(table="bad;name")


def test_list_foreign_keys_returns_fks(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    fks = connector.list_foreign_keys(table="orders")
    assert any(fk["table"] == "users" and fk["from"] == "user_id" for fk in fks)


def test_explain_query_returns_plan_or_program(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    program = connector.explain_query("SELECT * FROM users")
    plan = connector.explain_query("SELECT * FROM users", plan=True)
    assert program["plan"] is False
    assert plan["plan"] is True
    assert program["rows"] or plan["rows"]


def test_explain_query_rejects_writes(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    with pytest.raises(ValueError):
        connector.explain_query("UPDATE users SET name = 'x'")


def test_get_schema_dump_lists_ddl(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    dump = connector.get_schema_dump()
    names = {row["name"] for row in dump}
    assert "users" in names
    assert "orders" in names


def test_sample_table_returns_rows(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    result = connector.sample_table("users", limit=2)
    assert result["row_count"] == 2


def test_sample_table_validates(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    with pytest.raises(ValueError):
        connector.sample_table("bad;name")
    with pytest.raises(ValueError):
        connector.sample_table("users", limit=0)


def test_count_rows_returns_count(sample_db: Path) -> None:
    connector = SQLiteToolSet(sample_db)
    assert connector.count_rows("users")["row_count"] == 3
    with pytest.raises(ValueError):
        connector.count_rows("bad;name")


def test_sample_table_defaults_to_small_n(sample_db: Path) -> None:
    """Agent-ready default: sample_table returns at most 5 rows by default."""
    connector = SQLiteToolSet(sample_db)
    result = connector.sample_table("users")
    # Sample table has 3 rows; default cap of 5 should not truncate.
    assert result["row_count"] <= 5
    assert result["row_count"] == 3
    assert result["truncated"] is False


def test_list_tables_returns_concise_summaries(sample_db: Path) -> None:
    """Agent-ready: list_tables returns a tidy summary envelope."""
    connector = SQLiteToolSet(sample_db)
    result = connector.list_tables()
    assert set(result) == {"tables", "returned", "total", "truncated"}
    for entry in result["tables"]:
        assert entry["table_ref"].startswith("table_")
        # Schema/table names are user-facing — always keep them.
        assert entry["name"]
        assert entry["type"] in {"table", "view"}


def test_sqlite_toolset_destructive_tag_absent() -> None:
    """SQLite connector is read-only: no destructive tools registered."""
    from maivn._internal.utils.toolset import get_toolify_options

    connector = SQLiteToolSet(":memory:")
    tool_methods = [
        connector.list_tables,
        connector.describe_table,
        connector.run_query,
        connector.list_views,
        connector.list_indexes,
        connector.list_foreign_keys,
        connector.explain_query,
        connector.get_schema_dump,
        connector.sample_table,
        connector.count_rows,
    ]
    for method in tool_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False
