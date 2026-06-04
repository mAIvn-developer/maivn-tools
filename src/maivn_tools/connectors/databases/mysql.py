"""Read-only MySQL / MariaDB connector built on DB-API 2.0."""

# pyright: strict

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from contextlib import closing
from typing import Any, Protocol, cast

from maivn import toolify, toolset

from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet

# MARK: Constants

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|grant|revoke|rename|set)\b",
    re.IGNORECASE,
)

# Smaller defaults keep agent context windows tidy. Callers can override.
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_SAMPLE_LIMIT = 5
_DEFAULT_QUERY_LIMIT = 100


# MARK: DB-API protocols


class MySQLCursor(Protocol):
    description: Sequence[Sequence[Any]] | None

    def execute(self, query: str, params: Any = ...) -> Any: ...

    def fetchmany(self, size: int) -> list[Any]: ...

    def close(self) -> None: ...


class MySQLConnection(Protocol):
    def cursor(self) -> MySQLCursor: ...

    def close(self) -> None: ...


MySQLConnectionFactory = Callable[[], MySQLConnection]


# MARK: SQL helpers


def _validate_read_only_sql(sql: str) -> None:
    if not sql or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Compound statements are not allowed")
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in {"select", "with", "explain", "describe", "desc", "show"}:
        raise ValueError("Only read statements (SELECT/WITH/EXPLAIN/DESCRIBE/SHOW) are allowed")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise ValueError("Query contains a forbidden mutation keyword")


def _row_as_tuple(row: Any) -> tuple[Any, ...]:
    if isinstance(row, tuple):
        return cast(tuple[Any, ...], row)
    if isinstance(row, list):
        return tuple(cast(list[Any], row))
    if isinstance(row, dict):
        return tuple(cast(dict[Any, Any], row).values())
    return tuple(row)


def _run_select(
    connection: MySQLConnection,
    sql: str,
    params: Any,
    row_limit: int,
) -> dict[str, Any]:
    with closing(connection) as conn, closing(conn.cursor()) as cur:
        try:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
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


@toolset(prefix="mysql")
class MySQLToolSet:
    """A read-only MySQL/MariaDB connector built on DB-API 2.0.

    Args:
        dsn: Optional connection-string passed to the driver's ``connect`` call.
        connection_factory: Optional zero-arg factory returning a fresh
            DB-API connection. Useful for tests and custom drivers.
        row_limit: Hard upper bound on rows returned by ``run_query``.
            Queries that try to return more rows are truncated and the
            response sets ``truncated=True``. ``run_query`` defaults to
            100 rows per call unless callers pass a larger ``row_limit``
            override.
        connect_kwargs: Optional kwargs passed to ``mysql.connector.connect``
            when the default factory is used.
    """

    metadata = ProviderMetadata(
        name="mysql",
        display_name="MySQL / MariaDB",
        version="0.1.0",
        description="Read-only access to a MySQL or MariaDB database.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        tags=("database", "mysql", "mariadb", "sql"),
    )

    def __init__(
        self,
        *,
        dsn: str | None = None,
        connection_factory: MySQLConnectionFactory | None = None,
        row_limit: int = 500,
        connect_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if row_limit < 1:
            raise ValueError("row_limit must be at least 1")
        if connection_factory is None and not dsn and not connect_kwargs:
            raise ValueError("Provide dsn, connect_kwargs, or connection_factory")
        self._dsn = dsn
        self._factory = connection_factory
        self._connect_kwargs = connect_kwargs or {}
        self._row_limit = row_limit
        self.connection = None

    def _open(self) -> MySQLConnection:
        if self._factory is not None:
            return self._factory()
        try:
            import mysql.connector  # type: ignore[import-not-found]
        except ImportError:
            try:
                import pymysql  # type: ignore[import-not-found, no-redef]
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "MySQLToolSet requires 'mysql-connector-python' or 'pymysql'."
                ) from exc
            # Third-party driver has no type stubs; coerce to our protocol.
            return cast(MySQLConnection, cast(object, pymysql.connect(**self._connect_kwargs)))
        # Third-party driver exposes no type stubs; treat connect as Any.
        connect: Any = cast(Any, mysql.connector).connect
        if self._dsn:
            conn = connect(uri=self._dsn, **self._connect_kwargs)
        else:
            conn = connect(**self._connect_kwargs)
        return cast(MySQLConnection, cast(object, conn))

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_databases(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List databases (schemas) on the server.

        Best first tool when the active database is not yet known. Returns
        a summary envelope with ``databases``, ``returned``, ``total``,
        ``truncated``. Each entry has ``database_ref`` and a ``Database``
        key (MySQL's column name for the database list). Pass that value
        as the ``schema`` argument of :meth:`list_tables`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        rows = _run_select(
            self._open(),
            "SHOW DATABASES",
            None,
            self._row_limit,
        )["rows"]
        return _paginate_summary(
            rows, key="databases", ref_prefix="database", max_results=max_results
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tables(
        self,
        schema: str | None = None,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List tables in ``schema`` (defaults to the current ``DATABASE()``).

        Best first tool for schema exploration. Returns a summary envelope
        with ``tables``, ``returned``, ``total``, ``truncated``. Each
        entry carries ``table_ref``, the user-facing ``name``, plus
        ``type`` (``"BASE TABLE"`` or ``"VIEW"``). Pass ``name`` (and
        ``schema``) to :meth:`describe_table` or :meth:`sample_table`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        if schema is not None:
            sql = (
                "SELECT table_name AS name, table_type AS type "
                "FROM information_schema.tables WHERE table_schema = %s "
                "ORDER BY table_name"
            )
            params: Any = (schema,)
        else:
            sql = (
                "SELECT table_name AS name, table_type AS type "
                "FROM information_schema.tables "
                "WHERE table_schema = DATABASE() ORDER BY table_name"
            )
            params = None
        rows = _run_select(self._open(), sql, params, self._row_limit)["rows"]
        if schema is not None:
            for row in rows:
                row["schema"] = schema
        return _paginate_summary(rows, key="tables", ref_prefix="table", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_table(
        self,
        name: str,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Return column metadata for a table.

        Run after :meth:`list_tables` to understand a table before writing
        a query. Returns ``{"schema", "name", "columns", "primary_key"}``.
        Each ``columns`` entry has ``name``, ``type``, ``nullable``,
        ``default``, and MySQL ``key`` flag (``"PRI"``, ``"MUL"``, ...).
        """
        if schema is None:
            sql = (
                "SELECT column_name AS name, data_type AS type, "
                "       is_nullable = 'YES' AS nullable, column_default AS `default`, "
                "       column_key AS `key` "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s "
                "ORDER BY ordinal_position"
            )
            params: Any = (name,)
        else:
            sql = (
                "SELECT column_name AS name, data_type AS type, "
                "       is_nullable = 'YES' AS nullable, column_default AS `default`, "
                "       column_key AS `key` "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position"
            )
            params = (schema, name)
        cols = _run_select(self._open(), sql, params, self._row_limit)
        if not cols["rows"]:
            raise LookupError(f"Table {schema!r}.{name!r} does not exist")
        return {
            "schema": schema,
            "name": name,
            "columns": cols["rows"],
            "primary_key": [r["name"] for r in cols["rows"] if r.get("key") == "PRI"],
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_indexes(
        self,
        name: str,
        schema: str | None = None,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List indexes for ``name`` (in ``schema`` if given).

        Returns a summary envelope with ``indexes``, ``returned``,
        ``total``, ``truncated``. Each entry carries ``index_ref`` and the
        ``SHOW INDEXES`` row columns (``Key_name``, ``Column_name``,
        ``Non_unique``, ``Seq_in_index``, ...).
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        safe_name = name.replace("`", "")
        params: Any = None
        if schema is None:
            sql = f"SHOW INDEXES FROM `{safe_name}`"
        else:
            safe_schema = schema.replace("`", "")
            sql = f"SHOW INDEXES FROM `{safe_schema}`.`{safe_name}`"
        rows = _run_select(self._open(), sql, params, self._row_limit)["rows"]
        return _paginate_summary(rows, key="indexes", ref_prefix="index", max_results=max_results)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def explain_query(self, sql: str, *, analyze: bool = False) -> dict[str, Any]:
        """Return ``EXPLAIN FORMAT=JSON`` output for ``sql``.

        Use this to diagnose plan choice before running an expensive
        query. ``analyze=True`` is rejected because it actually executes
        the query — that belongs on a separate destructive connector.
        """
        _validate_read_only_sql(sql)
        if analyze:
            raise ValueError("EXPLAIN ANALYZE executes the query and is not allowed")
        return _run_select(
            self._open(),
            f"EXPLAIN FORMAT=JSON {sql}",
            None,
            self._row_limit,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def server_version(self) -> dict[str, Any]:
        """Return ``VERSION()`` and ``DATABASE()`` of the server.

        Returns ``{"version", "database"}``. Useful as a sanity check
        before issuing version-specific SQL.
        """
        rows = _run_select(
            self._open(),
            "SELECT VERSION() AS version, DATABASE() AS `database`",
            None,
            1,
        )["rows"]
        return rows[0] if rows else {"version": None, "database": None}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def sample_table(
        self,
        name: str,
        *,
        schema: str | None = None,
        limit: int = _DEFAULT_SAMPLE_LIMIT,
    ) -> dict[str, Any]:
        """Return up to ``limit`` rows from a table (default 5).

        Returns the same shape as :meth:`run_query` (``columns``, ``rows``
        as column-keyed dicts, ``row_count``, ``truncated``). For
        paginated reads, use :meth:`run_query` with explicit
        ``LIMIT``/``OFFSET``.
        """
        if limit < 1 or limit > self._row_limit:
            raise ValueError(f"limit must be between 1 and {self._row_limit}")
        qualified = f"`{schema}`.`{name}`" if schema else f"`{name}`"
        return self.run_query(f"SELECT * FROM {qualified} LIMIT %s", [limit], row_limit=limit)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def count_rows(self, name: str, schema: str | None = None) -> dict[str, Any]:
        """Return ``COUNT(*)`` for a table.

        Returns ``{"schema", "name", "row_count"}``. Cheap on small or
        well-indexed tables; an exact count over a huge table will scan
        the index.
        """
        qualified = f"`{schema}`.`{name}`" if schema else f"`{name}`"
        rows = _run_select(
            self._open(),
            f"SELECT COUNT(*) AS row_count FROM {qualified}",
            None,
            1,
        )["rows"]
        return {
            "schema": schema,
            "name": name,
            "row_count": rows[0]["row_count"] if rows else 0,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
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
            sql: ``SELECT``/``WITH``/``EXPLAIN``/``SHOW``/``DESCRIBE``
                statement. Compound statements and mutation keywords are
                rejected.
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
