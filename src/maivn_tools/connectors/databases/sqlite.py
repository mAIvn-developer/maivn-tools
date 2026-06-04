"""Read-only SQLite connector.

``SQLiteToolSet`` exposes schema introspection and parameterized read-only
query tools over a local SQLite database. Write operations are intentionally
not included: hosts that need to mutate a SQLite database should mount a
separate, explicitly destructive connector that opts in to
``PermissionFlag.WRITE``.

The connector uses the standard-library :mod:`sqlite3` module and has no
third-party dependencies. Connections are short-lived: each tool call opens
the database, runs its query, and closes the connection. That keeps the
connector usable from multiple threads without sharing handles.
"""

# pyright: strict

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from maivn import toolify, toolset

from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex|pragma)\b",
    re.IGNORECASE,
)

# Default for broad list/sample tools. Smaller defaults keep agent
# context windows tidy; callers can override per-call.
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_SAMPLE_LIMIT = 5
_DEFAULT_QUERY_LIMIT = 100


@toolset(prefix="sqlite")
class SQLiteToolSet:
    """A connector that exposes read-only SQLite tools.

    Args:
        database: Path to the SQLite database file, or ``":memory:"`` for an
            in-memory database. In-memory databases are useful for tests but
            do not persist across calls because each tool call opens a fresh
            connection.
        row_limit: Hard upper bound on rows returned by ``run_query``.
            Queries that try to return more rows are truncated and the
            response sets ``truncated=True``. The per-call default is the
            smaller of this value and :data:`_DEFAULT_QUERY_LIMIT`.
        query_timeout_seconds: Maximum time a single query may run before
            SQLite aborts it.
    """

    metadata = ProviderMetadata(
        name="sqlite",
        display_name="SQLite",
        version="0.1.0",
        description="Read-only access to a local SQLite database file.",
        auth_modes=(AuthMode.NONE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        tags=("database", "sqlite", "sql"),
    )

    def __init__(
        self,
        database: str | Path,
        *,
        row_limit: int = 500,
        query_timeout_seconds: float = 5.0,
    ) -> None:
        if row_limit < 1:
            raise ValueError("row_limit must be at least 1")
        if query_timeout_seconds <= 0:
            raise ValueError("query_timeout_seconds must be positive")
        self._database = str(database)
        self._row_limit = row_limit
        self._timeout = query_timeout_seconds
        self.connection = None

    @property
    def database(self) -> str:
        """Return the configured database path."""
        return self._database

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tables(
        self,
        *,
        include_views: bool = True,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List user-defined tables (and optionally views).

        Best first tool for schema exploration. Returns compact summaries
        with a stable ``table_ref`` (``table_1``, ``table_2``, ...) plus the
        human-readable ``name`` and ``type`` (``"table"`` or ``"view"``).
        Internal ``sqlite_*`` tables are always filtered out.

        Pass ``name`` from one of the entries to :meth:`describe_table`,
        :meth:`sample_table`, or :meth:`count_rows` to drill in. Use
        ``max_results`` to widen the page; the next page is computed
        client-side because SQLite catalogs are small.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        types = ("table", "view") if include_views else ("table",)
        placeholders = ",".join("?" * len(types))
        sql = (
            "SELECT name, type FROM sqlite_master "
            f"WHERE type IN ({placeholders}) AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            cur.execute(sql, types)
            rows = cur.fetchall()
        total = len(rows)
        slice_ = rows[:max_results]
        summaries = [
            {
                "table_ref": f"table_{index}",
                "name": row["name"],
                "type": row["type"],
            }
            for index, row in enumerate(slice_, start=1)
        ]
        return {
            "tables": summaries,
            "returned": len(summaries),
            "total": total,
            "truncated": total > len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_table(self, name: str) -> dict[str, Any]:
        """Return column metadata, primary keys, and indexes for ``name``.

        Run after :meth:`list_tables` to understand a table's shape before
        writing a query. Returns ``{"name", "columns", "indexes",
        "foreign_keys"}``. Each ``columns`` entry has ``name``, ``type``,
        ``notnull``, ``default``, and ``primary_key`` (bool) — those are the
        SQLite column attributes a SELECT typically needs.
        """
        if not _is_safe_identifier(name):
            raise ValueError(f"Invalid table name: {name!r}")
        with closing(self._connect()) as conn:
            columns = [
                {
                    "cid": row["cid"],
                    "name": row["name"],
                    "type": row["type"],
                    "notnull": bool(row["notnull"]),
                    "default": row["dflt_value"],
                    "primary_key": bool(row["pk"]),
                }
                for row in conn.execute(f"PRAGMA table_info({name})")
            ]
            if not columns:
                raise LookupError(f"Table {name!r} does not exist")
            indexes = [
                {
                    "name": row["name"],
                    "unique": bool(row["unique"]),
                    "origin": row["origin"],
                    "partial": bool(row["partial"]),
                }
                for row in conn.execute(f"PRAGMA index_list({name})")
            ]
            foreign_keys = [
                {
                    "id": row["id"],
                    "table": row["table"],
                    "from": row["from"],
                    "to": row["to"],
                    "on_delete": row["on_delete"],
                    "on_update": row["on_update"],
                }
                for row in conn.execute(f"PRAGMA foreign_key_list({name})")
            ]
        return {
            "name": name,
            "columns": columns,
            "indexes": indexes,
            "foreign_keys": foreign_keys,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_query(
        self,
        sql: str,
        parameters: list[Any] | dict[str, Any] | None = None,
        *,
        row_limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute a read-only ``SELECT`` / ``WITH`` query and return rows.

        Use this once :meth:`describe_table` has clarified the schema.
        Returns ``{"columns", "rows", "row_count", "truncated"}``. Each
        entry in ``rows`` is a dict keyed by column name (natural SQL row
        shape), so it can be shown back to the user without remapping.

        Args:
            sql: SQL statement. Only ``SELECT``/``WITH``/``EXPLAIN``
                statements are accepted. Compound statements (multiple
                semicolons) are rejected.
            parameters: Positional list (``[1, 'x']`` for ``?`` placeholders)
                or named-dict (``{"uid": 1}`` for ``:uid`` placeholders)
                bound into the query. Always parameterize untrusted values.
            row_limit: Per-call override for the row cap. Defaults to 100
                rows (or the configured ``row_limit``, whichever is
                smaller). Set explicitly to widen up to the configured
                ceiling.

        Safety: the connector enforces ``PRAGMA query_only = ON`` and
        rejects mutating keywords as a defense-in-depth measure. Writes
        belong on a separate destructive connector.
        """
        _validate_read_only_sql(sql)
        effective_limit = min(self._row_limit, _DEFAULT_QUERY_LIMIT)
        limit = effective_limit if row_limit is None else int(row_limit)
        if limit < 1:
            raise ValueError("row_limit must be at least 1")
        if limit > self._row_limit:
            limit = self._row_limit
        params: Any
        if parameters is None:
            params = ()
        elif isinstance(parameters, dict):
            params = parameters
        else:
            params = tuple(parameters)
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            cur.execute(sql, params)
            fetched = cur.fetchmany(limit + 1)
            truncated = len(fetched) > limit
            rows = [dict(row) for row in fetched[:limit]]
            columns = [desc[0] for desc in cur.description] if cur.description else []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_views(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List user-defined views.

        Returns ``{"views", "returned", "total", "truncated"}``. Each
        entry in ``views`` carries a ``view_ref``, the view ``name``, and
        the ``sql`` DDL that defines it. Pass ``name`` to
        :meth:`describe_table` or :meth:`sample_table` to inspect rows.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            cur.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'view' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
            rows = cur.fetchall()
        total = len(rows)
        slice_ = rows[:max_results]
        summaries = [
            {
                "view_ref": f"view_{index}",
                "name": row["name"],
                "sql": row["sql"],
            }
            for index, row in enumerate(slice_, start=1)
        ]
        return {
            "views": summaries,
            "returned": len(summaries),
            "total": total,
            "truncated": total > len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_indexes(
        self,
        table: str | None = None,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List indexes, optionally narrowed to one ``table``.

        Returns ``{"indexes", "returned", "total", "truncated"}``. Each
        entry in ``indexes`` carries an ``index_ref``, the index ``name``,
        the parent ``table`` name, and the ``sql`` DDL that created it.
        Auto-indexes created by SQLite (``sqlite_*``) are filtered out.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            if table is None:
                cur.execute(
                    "SELECT name, tbl_name, sql FROM sqlite_master "
                    "WHERE type = 'index' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY tbl_name, name"
                )
            else:
                if not _is_safe_identifier(table):
                    raise ValueError(f"Invalid table name: {table!r}")
                cur.execute(
                    "SELECT name, tbl_name, sql FROM sqlite_master "
                    "WHERE type = 'index' AND name NOT LIKE 'sqlite_%' AND tbl_name = ? "
                    "ORDER BY name",
                    (table,),
                )
            rows = cur.fetchall()
        total = len(rows)
        slice_ = rows[:max_results]
        summaries = [
            {
                "index_ref": f"index_{index}",
                "name": row["name"],
                "table": row["tbl_name"],
                "sql": row["sql"],
            }
            for index, row in enumerate(slice_, start=1)
        ]
        return {
            "indexes": summaries,
            "returned": len(summaries),
            "total": total,
            "truncated": total > len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_foreign_keys(self, table: str) -> list[dict[str, Any]]:
        """Return foreign-key definitions for ``table``.

        Returns a list of FK records — each dict carries the source
        ``from`` column, the referenced ``table`` and ``to`` column, plus
        the ``on_update`` / ``on_delete`` actions. Useful for following
        joins before composing a query.
        """
        if not _is_safe_identifier(table):
            raise ValueError(f"Invalid table name: {table!r}")
        with closing(self._connect()) as conn:
            return [
                {
                    "id": row["id"],
                    "seq": row["seq"],
                    "table": row["table"],
                    "from": row["from"],
                    "to": row["to"],
                    "on_update": row["on_update"],
                    "on_delete": row["on_delete"],
                    "match": row["match"],
                }
                for row in conn.execute(f"PRAGMA foreign_key_list({table})")
            ]

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def explain_query(self, sql: str, *, plan: bool = False) -> dict[str, Any]:
        """Return ``EXPLAIN`` (or ``EXPLAIN QUERY PLAN``) output for ``sql``.

        Use this to diagnose slow queries before running them at scale.
        Returns ``{"plan", "columns", "rows"}``. With ``plan=True`` the
        rows describe the high-level query plan tree; with the default
        ``plan=False`` they describe the low-level VDBE program.
        """
        _validate_read_only_sql(sql)
        prefix = "EXPLAIN QUERY PLAN" if plan else "EXPLAIN"
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            cur.execute(f"{prefix} {sql}")
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(row) for row in cur.fetchall()]
        return {"plan": plan, "columns": columns, "rows": rows}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_schema_dump(self) -> list[dict[str, Any]]:
        """Return DDL statements for every object in ``sqlite_master``.

        Returns a list of dicts: ``type`` (``"table"``, ``"view"``,
        ``"index"``, ``"trigger"``), ``name``, ``table`` (parent table for
        indexes/triggers), and ``sql`` (the original DDL). Useful for full
        schema documentation but verbose — prefer :meth:`list_tables` for
        casual exploration.
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            cur.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
                "ORDER BY type, name"
            )
            return [
                {
                    "type": row["type"],
                    "name": row["name"],
                    "table": row["tbl_name"],
                    "sql": row["sql"],
                }
                for row in cur.fetchall()
            ]

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def sample_table(
        self,
        name: str,
        *,
        limit: int = _DEFAULT_SAMPLE_LIMIT,
    ) -> dict[str, Any]:
        """Return up to ``limit`` rows from ``name`` for quick inspection.

        Defaults to 5 rows — enough to recognize the columns and data
        without flooding context. Returns the same shape as
        :meth:`run_query` (``columns``, ``rows``, ``row_count``,
        ``truncated``). For paginated reads, use :meth:`run_query` with an
        explicit ``LIMIT``/``OFFSET``.
        """
        if not _is_safe_identifier(name):
            raise ValueError(f"Invalid table name: {name!r}")
        if limit < 1 or limit > self._row_limit:
            raise ValueError(f"limit must be between 1 and {self._row_limit}")
        return self.run_query(f"SELECT * FROM {name} LIMIT {int(limit)}", row_limit=limit)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def count_rows(self, name: str) -> dict[str, Any]:
        """Return ``COUNT(*)`` for ``name``.

        Returns ``{"table": <name>, "row_count": <int>}``. Cheap on small
        tables; expensive on huge tables (SQLite has no row-count cache).
        """
        if not _is_safe_identifier(name):
            raise ValueError(f"Invalid table name: {name!r}")
        with closing(self._connect()) as conn, closing(conn.cursor()) as cur:
            cur.execute(f"SELECT COUNT(*) AS row_count FROM {name}")
            row = cur.fetchone()
            return {"table": name, "row_count": row["row_count"] if row else 0}

    # MARK: - Internal helpers

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._database,
            timeout=self._timeout,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        # Defense-in-depth: the connector never issues writes, but enforcing
        # query_only at the SQLite level rejects accidental mutations too.
        conn.execute("PRAGMA query_only = ON;")
        return conn


def _is_safe_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _validate_read_only_sql(sql: object) -> None:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Compound statements are not allowed")
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in {"select", "with", "explain"}:
        raise ValueError("Only SELECT, WITH, and EXPLAIN statements are allowed in run_query")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise ValueError("Query contains a forbidden mutation keyword")
