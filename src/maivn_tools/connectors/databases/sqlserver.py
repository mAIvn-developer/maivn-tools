"""Read-only Microsoft SQL Server connector built on DB-API 2.0."""

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
    SQLSERVER_COUNT_ROWS_OUTPUT,
    SQLSERVER_DESCRIBE_TABLE_OUTPUT,
    SQLSERVER_LIST_DATABASES_OUTPUT,
    SQLSERVER_LIST_SCHEMAS_OUTPUT,
    SQLSERVER_LIST_TABLES_OUTPUT,
    SQLSERVER_LIST_VIEWS_OUTPUT,
    SQLSERVER_RUN_QUERY_OUTPUT,
    SQLSERVER_SAMPLE_TABLE_OUTPUT,
    SQLSERVER_SERVER_VERSION_OUTPUT,
)

# MARK: Constants

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|exec|execute)\b",
    re.IGNORECASE,
)

# Smaller defaults keep agent context windows tidy. Callers can override.
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_SAMPLE_LIMIT = 5
_DEFAULT_QUERY_LIMIT = 100


# MARK: Protocols


class SQLServerCursor(Protocol):
    description: Any

    def execute(self, query: str, params: Any = ...) -> Any: ...

    def fetchmany(self, size: int) -> list[Any]: ...

    def close(self) -> None: ...


class SQLServerConnection(Protocol):
    def cursor(self) -> SQLServerCursor: ...

    def close(self) -> None: ...


SQLServerConnectionFactory = Callable[[], SQLServerConnection]


# MARK: Helpers


def _is_safe_identifier(name: str) -> bool:
    """Allow only plain SQL identifiers (no brackets/dots/whitespace).

    ``sample_table``/``count_rows`` interpolate ``schema``/``name`` into
    bracket-quoted identifiers; an embedded ``]`` could break out and inject
    SQL. Restrict to the same strict shape the sqlite connector enforces;
    exotic identifiers can go through ``run_query`` with proper quoting.
    """
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _validate_read_only_sql(sql: object) -> None:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Compound statements are not allowed")
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in {"select", "with"}:
        raise ValueError("Only SELECT and WITH statements are allowed")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise ValueError("Query contains a forbidden mutation keyword")


def _row_as_tuple(row: Any) -> tuple[Any, ...]:
    if isinstance(row, tuple):
        return cast("tuple[Any, ...]", row)
    if isinstance(row, list):
        return tuple(cast("list[Any]", row))
    if isinstance(row, dict):
        return tuple(cast("dict[Any, Any]", row).values())
    return tuple(row)


def _run_select(
    connection: SQLServerConnection,
    sql: str,
    params: Any,
    row_limit: int,
) -> dict[str, Any]:
    with closing(connection) as conn, closing(conn.cursor()) as cur:
        try:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        except Exception:  # noqa: BLE001
            pass
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        fetched = cur.fetchmany(row_limit + 1)
        truncated = len(fetched) > row_limit
        rows_slice = fetched[:row_limit]
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = (
            [dict(zip(columns, _row_as_tuple(row), strict=False)) for row in rows_slice]
            if columns
            else []
        )
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


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
        summary: dict[str, Any] = {f"{ref_prefix}_ref": f"{ref_prefix}_{index}", **row}
        summaries.append(summary)
    return {
        key: summaries,
        "returned": len(summaries),
        "total": total,
        "truncated": total > len(summaries),
    }


# MARK: ToolSet


@toolset(prefix="sqlserver")
class SQLServerToolSet:
    """A read-only SQL Server connector built on DB-API 2.0 (pyodbc, pymssql, etc.).

    Args:
        connection_string: ODBC / pymssql connection string. Optional
            when ``connection_factory`` or ``connect_kwargs`` is provided.
        connection_factory: Zero-arg factory returning a fresh DB-API
            connection. Useful for tests and custom drivers.
        row_limit: Hard upper bound on rows returned by ``run_query``.
            Queries that try to return more rows are truncated and the
            response sets ``truncated=True``. ``run_query`` defaults to
            100 rows per call unless callers pass a larger ``row_limit``
            override.
        connect_kwargs: Optional kwargs passed to the default
            driver's ``connect`` call.
    """

    metadata = ProviderMetadata(
        name="sqlserver",
        display_name="SQL Server",
        version="0.1.0",
        description="Read-only access to a Microsoft SQL Server database.",
        auth_modes=(AuthMode.BASIC, AuthMode.CUSTOM),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        tags=("database", "mssql", "sql", "microsoft"),
    )

    def __init__(
        self,
        *,
        connection_string: str | None = None,
        connection_factory: SQLServerConnectionFactory | None = None,
        row_limit: int = 500,
        connect_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if row_limit < 1:
            raise ValueError("row_limit must be at least 1")
        if connection_factory is None and not connection_string and not connect_kwargs:
            raise ValueError("Provide connection_string, connect_kwargs, or connection_factory")
        self._connection_string = connection_string
        self._factory = connection_factory
        self._connect_kwargs = connect_kwargs or {}
        self._row_limit = row_limit
        self.connection = None

    def _open(self) -> SQLServerConnection:
        if self._factory is not None:
            return self._factory()
        try:
            import pyodbc  # type: ignore[import-not-found]
        except ImportError:
            try:
                import pymssql  # type: ignore[import-not-found, no-redef]
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("SQLServerToolSet requires 'pyodbc' or 'pymssql'.") from exc
            # Third-party drivers ship no type stubs; connect is an untyped callable.
            pymssql_connect = cast("Callable[..., object]", cast(object, pymssql.connect))
            return cast("SQLServerConnection", pymssql_connect(**self._connect_kwargs))
        pyodbc_connect = cast("Callable[..., object]", cast(object, pyodbc.connect))
        if self._connection_string:
            return cast(
                "SQLServerConnection",
                pyodbc_connect(self._connection_string, **self._connect_kwargs),
            )
        return cast("SQLServerConnection", pyodbc_connect(**self._connect_kwargs))

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_LIST_DATABASES_OUTPUT)
    def list_databases(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List databases on the server.

        Best first tool when the active database is not yet known.
        Returns ``{"databases", "returned", "total", "truncated"}``. Each
        entry has ``database_ref`` and ``name``. To list tables in one,
        switch context using the connection string or pass the database
        name in queries.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        rows = _run_select(
            self._open(),
            "SELECT name FROM sys.databases ORDER BY name",
            None,
            self._row_limit,
        )["rows"]
        return _paginate_summary(
            rows, key="databases", ref_prefix="database", max_results=max_results
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_LIST_SCHEMAS_OUTPUT)
    def list_schemas(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List schemas in the current database (excluding ``sys`` / ``INFORMATION_SCHEMA``).

        Returns ``{"schemas", "returned", "total", "truncated"}``. Each
        entry has ``schema_ref`` and the user-facing ``name``. Pass
        ``name`` as the ``schema`` argument of :meth:`list_tables`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        rows = _run_select(
            self._open(),
            "SELECT name FROM sys.schemas "
            "WHERE name NOT IN ('sys', 'INFORMATION_SCHEMA') ORDER BY name",
            None,
            self._row_limit,
        )["rows"]
        return _paginate_summary(rows, key="schemas", ref_prefix="schema", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_LIST_TABLES_OUTPUT)
    def list_tables(
        self,
        schema: str = "dbo",
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List tables and views in ``schema``.

        Best first tool for schema exploration. Returns ``{"tables",
        "returned", "total", "truncated"}``. Each entry carries
        ``table_ref``, ``schema``, ``name`` (user-facing identifier), and
        ``type`` (``"BASE TABLE"`` or ``"VIEW"``). Pass ``name`` + ``schema``
        to :meth:`describe_table` or :meth:`sample_table`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        rows = _run_select(
            self._open(),
            "SELECT table_name AS name, table_type AS type "
            "FROM information_schema.tables WHERE table_schema = ? "
            "ORDER BY table_name",
            (schema,),
            self._row_limit,
        )["rows"]
        for row in rows:
            row["schema"] = schema
        return _paginate_summary(rows, key="tables", ref_prefix="table", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_DESCRIBE_TABLE_OUTPUT)
    def describe_table(
        self,
        name: str,
        schema: str = "dbo",
    ) -> dict[str, Any]:
        """Return columns and primary key for a table.

        Run after :meth:`list_tables`. Returns ``{"schema", "name",
        "columns", "primary_key"}``. Each ``columns`` entry has ``name``,
        ``type``, ``nullable``, ``default``.
        """
        cols = _run_select(
            self._open(),
            "SELECT column_name AS name, data_type AS type, "
            "       is_nullable = 'YES' AS nullable, column_default AS [default] "
            "FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? "
            "ORDER BY ordinal_position",
            (schema, name),
            self._row_limit,
        )
        if not cols["rows"]:
            raise LookupError(f"Table {schema!r}.{name!r} does not exist")
        pks = _run_select(
            self._open(),
            "SELECT kcu.column_name AS name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_schema = ? AND tc.table_name = ? "
            "ORDER BY kcu.ordinal_position",
            (schema, name),
            self._row_limit,
        )
        return {
            "schema": schema,
            "name": name,
            "columns": cols["rows"],
            "primary_key": [r["name"] for r in pks["rows"]],
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_LIST_VIEWS_OUTPUT)
    def list_views(
        self,
        schema: str = "dbo",
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List views in ``schema``.

        Returns ``{"views", "returned", "total", "truncated"}``. Each
        entry carries ``view_ref``, ``schema``, and ``name``. Views can
        be sampled with :meth:`sample_table`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        rows = _run_select(
            self._open(),
            "SELECT table_name AS name FROM information_schema.views "
            "WHERE table_schema = ? ORDER BY table_name",
            (schema,),
            self._row_limit,
        )["rows"]
        for row in rows:
            row["schema"] = schema
        return _paginate_summary(rows, key="views", ref_prefix="view", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_SERVER_VERSION_OUTPUT)
    def server_version(self) -> dict[str, Any]:
        """Return SQL Server ``@@VERSION`` and current ``DB_NAME()``.

        Returns ``{"version", "database"}``. Useful as a sanity check
        before issuing version-specific SQL.
        """
        rows = _run_select(
            self._open(),
            "SELECT @@VERSION AS version, DB_NAME() AS [database]",
            None,
            1,
        )["rows"]
        return rows[0] if rows else {"version": None, "database": None}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_SAMPLE_TABLE_OUTPUT)
    def sample_table(
        self,
        name: str,
        *,
        schema: str = "dbo",
        limit: int = _DEFAULT_SAMPLE_LIMIT,
    ) -> dict[str, Any]:
        """Return up to ``limit`` rows (default 5) using ``SELECT TOP``.

        Returns the same shape as :meth:`run_query` (``columns``, ``rows``
        as column-keyed dicts, ``row_count``, ``truncated``).
        """
        if limit < 1 or limit > self._row_limit:
            raise ValueError(f"limit must be between 1 and {self._row_limit}")
        if not _is_safe_identifier(schema) or not _is_safe_identifier(name):
            raise ValueError(f"Invalid table reference: {schema!r}.{name!r}")
        return self.run_query(
            f"SELECT TOP {int(limit)} * FROM [{schema}].[{name}]",
            row_limit=limit,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_COUNT_ROWS_OUTPUT)
    def count_rows(self, name: str, schema: str = "dbo") -> dict[str, Any]:
        """Return ``COUNT(*)`` for a table.

        Returns ``{"schema", "name", "row_count"}``.
        """
        if not _is_safe_identifier(schema) or not _is_safe_identifier(name):
            raise ValueError(f"Invalid table reference: {schema!r}.{name!r}")
        rows = _run_select(
            self._open(),
            f"SELECT COUNT(*) AS row_count FROM [{schema}].[{name}]",
            None,
            1,
        )["rows"]
        return {
            "schema": schema,
            "name": name,
            "row_count": rows[0]["row_count"] if rows else 0,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SQLSERVER_RUN_QUERY_OUTPUT)
    def run_query(
        self,
        sql: str,
        parameters: list[Any] | dict[str, Any] | None = None,
        *,
        row_limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute a read-only query.

        Use this once :meth:`describe_table` has clarified the schema.
        Returns ``{"columns", "rows", "row_count", "truncated"}``. Each
        entry in ``rows`` is a dict keyed by column name (natural SQL row
        shape).

        Args:
            sql: ``SELECT`` or ``WITH`` statement. Compound statements,
                ``EXEC``, and mutation keywords are rejected.
            parameters: Positional list (``[1, 'x']`` for ``?``) or dict
                for named parameters. Always parameterize untrusted
                values.
            row_limit: Per-call override. Defaults to 100 rows or the
                configured connector ceiling, whichever is smaller.
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
