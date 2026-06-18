"""Read-only PostgreSQL connector.

The connector wraps any DB-API 2.0 compatible PostgreSQL driver (such as
``psycopg`` or ``psycopg2``) behind a small connection-factory protocol so
tests can inject fakes. The driver itself is **not** a required dependency
of ``maivn-tools``; callers either pass a custom factory or install one of
the supported drivers and use the default factory.

Default behavior:

* Each tool call opens a new connection and closes it on exit.
* Queries run in a read-only transaction (``SET TRANSACTION READ ONLY``).
* Only ``SELECT``, ``WITH``, and ``EXPLAIN`` statements are accepted.

Mutating tools should live in a separate, explicitly destructive connector.
"""

# pyright: strict

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import closing
from typing import Any, Protocol, cast

from maivn import tool_output, toolify, toolset

from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from .output_schemas import (
    PG_COUNT_ROWS_OUTPUT,
    PG_DESCRIBE_TABLE_OUTPUT,
    PG_EXPLAIN_QUERY_OUTPUT,
    PG_GET_TABLE_SIZE_OUTPUT,
    PG_LIST_EXTENSIONS_OUTPUT,
    PG_LIST_FOREIGN_KEYS_OUTPUT,
    PG_LIST_INDEXES_OUTPUT,
    PG_LIST_SCHEMAS_OUTPUT,
    PG_LIST_TABLES_OUTPUT,
    PG_LIST_VIEWS_OUTPUT,
    PG_RUN_QUERY_OUTPUT,
    PG_SAMPLE_TABLE_OUTPUT,
    PG_SERVER_VERSION_OUTPUT,
)

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|grant|revoke|comment|vacuum|analyze|copy)\b",
    re.IGNORECASE,
)

# Smaller defaults keep agent context windows tidy. Callers can override.
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_SAMPLE_LIMIT = 5
_DEFAULT_QUERY_LIMIT = 100


class PostgresCursor(Protocol):
    """Minimum DB-API cursor surface the connector requires."""

    description: Any

    def execute(self, query: str, params: Any = ...) -> Any: ...

    def fetchmany(self, size: int) -> list[Any]: ...

    def close(self) -> None: ...


class PostgresConnection(Protocol):
    """Minimum DB-API connection surface the connector requires."""

    def cursor(self) -> PostgresCursor: ...

    def close(self) -> None: ...


PostgresConnectionFactory = Callable[[], PostgresConnection]


def _paginate_summary(
    rows: list[dict[str, Any]],
    *,
    key: str,
    ref_prefix: str,
    max_results: int,
) -> dict[str, Any]:
    """Wrap a row list into the standard summary envelope."""
    total = len(rows)
    slice_ = rows[:max_results]
    summaries: list[dict[str, Any]] = []
    for index, row in enumerate(slice_, start=1):
        summary = {f"{ref_prefix}_ref": f"{ref_prefix}_{index}", **row}
        summaries.append(summary)
    return {
        key: summaries,
        "returned": len(summaries),
        "total": total,
        "truncated": total > len(summaries),
    }


@toolset(prefix="postgres")
class PostgresToolSet:
    """A read-only PostgreSQL connector built on DB-API 2.0.

    Args:
        dsn: PostgreSQL DSN passed to ``psycopg.connect`` when the default
            factory is used.
        connection_factory: Optional zero-argument factory returning a fresh
            DB-API connection. Required when the user does not want the
            connector to import ``psycopg`` directly.
        row_limit: Hard upper bound on rows returned by ``run_query``.
            Queries that try to return more rows are truncated and the
            response sets ``truncated=True``. ``run_query`` defaults to
            100 rows per call unless callers pass a larger ``row_limit``
            override.
    """

    metadata = ProviderMetadata(
        name="postgres",
        display_name="PostgreSQL",
        version="0.1.0",
        description="Read-only access to a PostgreSQL database.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        tags=("database", "postgres", "sql"),
    )

    def __init__(
        self,
        *,
        dsn: str | None = None,
        connection_factory: PostgresConnectionFactory | None = None,
        row_limit: int = 500,
    ) -> None:
        if row_limit < 1:
            raise ValueError("row_limit must be at least 1")
        if connection_factory is None and not dsn:
            raise ValueError("Either dsn or connection_factory must be supplied")
        self._dsn = dsn
        self._connection_factory = connection_factory
        self._row_limit = row_limit
        self.connection = None

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_LIST_TABLES_OUTPUT)
    def list_tables(
        self,
        schema: str = "public",
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List tables and views in ``schema``.

        Best first tool for schema exploration. Returns a summary envelope
        with ``tables``, ``returned``, ``total``, and ``truncated``. Each
        entry carries a stable ``table_ref`` (``table_1``, ``table_2``,
        ...), the user-facing ``schema`` and ``name``, plus a ``type``
        (``"BASE TABLE"`` or ``"VIEW"``) so callers can decide whether to
        sample it. Pass ``name`` + ``schema`` to :meth:`describe_table` or
        :meth:`sample_table`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        sql = (
            "SELECT table_name AS name, table_type AS type "
            "FROM information_schema.tables "
            "WHERE table_schema = %s "
            "ORDER BY table_name"
        )
        rows = _run_select(self._open(), sql, (schema,), self._row_limit)["rows"]
        for row in rows:
            row["schema"] = schema
        return _paginate_summary(rows, key="tables", ref_prefix="table", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_DESCRIBE_TABLE_OUTPUT)
    def describe_table(self, name: str, schema: str = "public") -> dict[str, Any]:
        """Return columns and primary-key columns for ``schema.name``.

        Run after :meth:`list_tables` to understand a table before writing
        a query. Returns ``{"name", "schema", "columns", "primary_key"}``.
        Each ``columns`` entry has ``name``, ``type``, ``nullable``, and
        ``default``.
        """
        columns_sql = (
            "SELECT column_name AS name, data_type AS type, "
            "       is_nullable = 'YES' AS nullable, column_default AS default "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position"
        )
        pk_sql = (
            "SELECT kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            " AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_schema = %s AND tc.table_name = %s "
            "ORDER BY kcu.ordinal_position"
        )
        cols = _run_select(self._open(), columns_sql, (schema, name), self._row_limit)
        if not cols["rows"]:
            raise LookupError(f"Table {schema!r}.{name!r} does not exist")
        pks = _run_select(self._open(), pk_sql, (schema, name), self._row_limit)
        return {
            "name": name,
            "schema": schema,
            "columns": cols["rows"],
            "primary_key": [row["column_name"] for row in pks["rows"]],
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_LIST_SCHEMAS_OUTPUT)
    def list_schemas(self, *, max_results: int = _DEFAULT_LIST_LIMIT) -> dict[str, Any]:
        """List non-system schemas in the current database.

        Returns a summary envelope with ``schemas``, ``returned``,
        ``total``, ``truncated``. Each entry has ``schema_ref`` and the
        user-facing ``name``. Pass ``name`` as the ``schema`` argument of
        :meth:`list_tables` to drill in.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        sql = (
            "SELECT schema_name AS name "
            "FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog', 'information_schema') "
            "  AND schema_name NOT LIKE 'pg_toast%' "
            "  AND schema_name NOT LIKE 'pg_temp%' "
            "ORDER BY schema_name"
        )
        rows = _run_select(self._open(), sql, None, self._row_limit)["rows"]
        return _paginate_summary(rows, key="schemas", ref_prefix="schema", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_LIST_VIEWS_OUTPUT)
    def list_views(
        self,
        schema: str = "public",
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List views and materialized views in ``schema``.

        Returns a summary envelope with ``views``, ``returned``, ``total``,
        ``truncated``. Each entry carries ``view_ref``, the user-facing
        ``schema`` and ``name``. Views can be sampled with
        :meth:`sample_table` just like base tables.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        sql = (
            "SELECT table_name AS name "
            "FROM information_schema.views "
            "WHERE table_schema = %s "
            "UNION ALL "
            "SELECT matviewname AS name "
            "FROM pg_matviews "
            "WHERE schemaname = %s "
            "ORDER BY name"
        )
        rows = _run_select(self._open(), sql, (schema, schema), self._row_limit)["rows"]
        for row in rows:
            row["schema"] = schema
        return _paginate_summary(rows, key="views", ref_prefix="view", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_LIST_INDEXES_OUTPUT)
    def list_indexes(
        self,
        *,
        schema: str = "public",
        table: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List indexes for ``schema`` (optionally narrowed by ``table``).

        Returns a summary envelope with ``indexes``, ``returned``,
        ``total``, ``truncated``. Each entry carries ``index_ref`` and the
        index ``name``, parent ``schema``/``table``, plus the full
        ``definition`` DDL.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        if table is None:
            sql = (
                "SELECT schemaname AS schema, tablename AS table, "
                "       indexname AS name, indexdef AS definition "
                "FROM pg_indexes "
                "WHERE schemaname = %s "
                "ORDER BY tablename, indexname"
            )
            params: Any = (schema,)
        else:
            sql = (
                "SELECT schemaname AS schema, tablename AS table, "
                "       indexname AS name, indexdef AS definition "
                "FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = %s "
                "ORDER BY indexname"
            )
            params = (schema, table)
        rows = _run_select(self._open(), sql, params, self._row_limit)["rows"]
        return _paginate_summary(rows, key="indexes", ref_prefix="index", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_LIST_FOREIGN_KEYS_OUTPUT)
    def list_foreign_keys(
        self,
        name: str,
        schema: str = "public",
    ) -> list[dict[str, Any]]:
        """Return foreign-key constraints defined on ``schema.name``.

        Each entry has ``name`` (constraint), ``column`` (local column),
        ``foreign_schema`` / ``foreign_table`` / ``foreign_column``.
        Useful for following joins when composing a query.
        """
        sql = (
            "SELECT tc.constraint_name AS name, "
            "       kcu.column_name AS column, "
            "       ccu.table_schema AS foreign_schema, "
            "       ccu.table_name AS foreign_table, "
            "       ccu.column_name AS foreign_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            " AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = tc.constraint_name "
            " AND ccu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "  AND tc.table_schema = %s AND tc.table_name = %s "
            "ORDER BY tc.constraint_name, kcu.ordinal_position"
        )
        return _run_select(self._open(), sql, (schema, name), self._row_limit)["rows"]

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_LIST_EXTENSIONS_OUTPUT)
    def list_extensions(self) -> list[dict[str, Any]]:
        """List installed PostgreSQL extensions.

        Each entry has ``name`` and ``version``. Useful before issuing
        extension-specific queries (e.g. ``pg_trgm`` similarity,
        ``postgis`` geometry, ``vector`` embeddings).
        """
        sql = "SELECT extname AS name, extversion AS version FROM pg_extension ORDER BY extname"
        return _run_select(self._open(), sql, None, self._row_limit)["rows"]

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_GET_TABLE_SIZE_OUTPUT)
    def get_table_size(self, name: str, schema: str = "public") -> dict[str, Any]:
        """Return total and table sizes (in bytes) for ``schema.name``.

        Returns ``{"schema", "name", "total_bytes", "table_bytes"}``.
        ``total_bytes`` includes indexes and TOAST; ``table_bytes`` is the
        heap only. Use this before sampling a massive table.
        """
        qualified = f"{schema}.{name}"
        sql = (
            "SELECT pg_total_relation_size(%s) AS total_bytes, "
            "       pg_relation_size(%s) AS table_bytes"
        )
        rows = _run_select(self._open(), sql, (qualified, qualified), 1)["rows"]
        if not rows:
            raise LookupError(f"Table {qualified!r} does not exist")
        first = rows[0]
        return {
            "schema": schema,
            "name": name,
            "total_bytes": first.get("total_bytes"),
            "table_bytes": first.get("table_bytes"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_EXPLAIN_QUERY_OUTPUT)
    def explain_query(
        self,
        sql: str,
        *,
        analyze: bool = False,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Return ``EXPLAIN`` (JSON) output for ``sql``.

        Use this to diagnose plan choice before running an expensive
        query. ``analyze=True`` is rejected because it actually executes
        the query — that belongs on a separate destructive connector.
        """
        _validate_read_only_sql(sql)
        if analyze:
            raise ValueError(
                "EXPLAIN ANALYZE executes the query and may have side effects; "
                "not allowed on a read-only connector."
            )
        opts: list[str] = ["FORMAT JSON"]
        if verbose:
            opts.append("VERBOSE")
        prefix = "EXPLAIN (" + ", ".join(opts) + ")"
        return _run_select(self._open(), f"{prefix} {sql}", None, self._row_limit)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_SERVER_VERSION_OUTPUT)
    def server_version(self) -> dict[str, Any]:
        """Return ``version()`` and ``current_database()`` of the server.

        Returns ``{"version": <server version string>, "database":
        <current database name>}``.
        """
        sql = "SELECT version() AS version, current_database() AS database"
        rows = _run_select(self._open(), sql, None, 1)["rows"]
        return rows[0] if rows else {"version": None, "database": None}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_SAMPLE_TABLE_OUTPUT)
    def sample_table(
        self,
        name: str,
        *,
        schema: str = "public",
        limit: int = _DEFAULT_SAMPLE_LIMIT,
    ) -> dict[str, Any]:
        """Return up to ``limit`` rows from ``schema.name`` for quick inspection.

        Defaults to 5 rows — enough to recognize columns without flooding
        context. Returns the same shape as :meth:`run_query`: ``columns``,
        ``rows`` (list of column-keyed dicts), ``row_count``, ``truncated``.
        """
        if limit < 1 or limit > self._row_limit:
            raise ValueError(f"limit must be between 1 and {self._row_limit}")
        if not _is_safe_identifier(schema) or not _is_safe_identifier(name):
            raise ValueError(f"Invalid table reference: {schema!r}.{name!r}")
        return self.run_query(
            f'SELECT * FROM "{schema}"."{name}" LIMIT %s',
            [limit],
            row_limit=limit,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_COUNT_ROWS_OUTPUT)
    def count_rows(self, name: str, schema: str = "public") -> dict[str, Any]:
        """Return ``COUNT(*)`` for ``schema.name``.

        Returns ``{"schema", "name", "row_count"}``. Cheap on small or
        well-indexed tables; for huge tables consider
        :meth:`get_table_size` to estimate via reltuples instead.
        """
        if not _is_safe_identifier(schema) or not _is_safe_identifier(name):
            raise ValueError(f"Invalid table reference: {schema!r}.{name!r}")
        rows = _run_select(
            self._open(),
            f'SELECT COUNT(*) AS row_count FROM "{schema}"."{name}"',
            None,
            1,
        )["rows"]
        return {"schema": schema, "name": name, "row_count": rows[0]["row_count"] if rows else 0}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PG_RUN_QUERY_OUTPUT)
    def run_query(
        self,
        sql: str,
        parameters: list[Any] | dict[str, Any] | None = None,
        *,
        row_limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute a read-only query and return the rows it produced.

        Use this once :meth:`describe_table` has clarified the schema.
        Returns ``{"columns", "rows", "row_count", "truncated"}``. Each
        entry in ``rows`` is a dict keyed by column name (natural SQL row
        shape) — safe to show to the user without remapping.

        Args:
            sql: ``SELECT``/``WITH``/``EXPLAIN`` statement. Compound
                statements (multiple semicolons) and mutation keywords
                are rejected.
            parameters: Positional list (``[1, 'x']`` for ``%s``) or named
                dict (``{"uid": 1}`` for ``%(uid)s``). Always parameterize
                untrusted values.
            row_limit: Per-call override. Defaults to 100 rows or the
                configured connector ceiling, whichever is smaller. Set
                explicitly to widen up to the configured ceiling.
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
            params = None
        elif isinstance(parameters, dict):
            params = parameters
        else:
            params = tuple(parameters)
        return _run_select(self._open(), sql, params, limit)

    # MARK: - Internal

    def _open(self) -> PostgresConnection:
        if self._connection_factory is not None:
            return self._connection_factory()
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError:
            try:
                import psycopg2 as psycopg  # type: ignore[import-not-found, no-redef]
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError(
                    "PostgresToolSet requires 'psycopg' or 'psycopg2' "
                    "to be installed, or a custom connection_factory."
                ) from exc
        return psycopg.connect(self._dsn)  # type: ignore[return-value]


def _is_safe_identifier(name: str) -> bool:
    """Allow only plain SQL identifiers (no quotes/dots/whitespace).

    ``sample_table``/``count_rows`` interpolate ``schema``/``name`` straight
    into quoted identifiers, so an embedded quote could break out of the
    identifier and inject arbitrary SQL. Restrict to the same strict shape the
    sqlite connector enforces; callers needing exotic identifiers can use
    ``run_query`` with proper quoting.
    """
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


def _run_select(
    connection: PostgresConnection,
    sql: str,
    params: Any,
    row_limit: int,
) -> dict[str, Any]:
    with closing(connection) as conn, closing(conn.cursor()) as cur:
        try:
            cur.execute("SET TRANSACTION READ ONLY")
        except Exception:  # noqa: BLE001 - some fake drivers do not support it
            pass
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        fetched = cur.fetchmany(row_limit + 1)
        truncated = len(fetched) > row_limit
        rows_slice = fetched[:row_limit]
        columns = [desc[0] for desc in cur.description] if cur.description else []
        if columns:
            rows = [dict(zip(columns, _row_as_tuple(row), strict=False)) for row in rows_slice]
        else:
            rows = []
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


def _row_as_tuple(row: Any) -> tuple[Any, ...]:
    if isinstance(row, tuple):
        return cast("tuple[Any, ...]", row)
    if isinstance(row, list):
        return tuple(cast("list[Any]", row))
    if isinstance(row, dict):
        return tuple(cast("dict[Any, Any]", row).values())
    return tuple(row)
