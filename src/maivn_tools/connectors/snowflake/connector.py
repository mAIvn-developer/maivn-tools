"""Snowflake SQL API v2 connector (HTTP/REST)."""

# pyright: strict

from __future__ import annotations

import re
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_DATABASES_OUTPUT,
    LIST_SCHEMAS_OUTPUT,
    LIST_TABLES_OUTPUT,
    LIST_VIEWS_OUTPUT,
    LIST_WAREHOUSES_OUTPUT,
)

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|copy|put|get)\b",
    re.IGNORECASE,
)

# Smaller defaults keep agent context windows tidy. Callers can override.
_DEFAULT_LIST_LIMIT = 25

# Optional Snowflake header declaring the kind of bearer token being sent.
# When supplied it must match the token kind; omitting it lets Snowflake
# auto-detect. Accepted values: OAUTH, KEYPAIR_JWT, PROGRAMMATIC_ACCESS_TOKEN.
# See https://docs.snowflake.com/en/developer-guide/sql-api/authenticating.
_TOKEN_TYPE_HEADER = "X-Snowflake-Authorization-Token-Type"
_DEFAULT_TOKEN_TYPE = "OAUTH"


def _validate_read_only_sql(sql: object) -> None:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Compound statements are not allowed")
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in {"select", "with", "show", "describe", "desc", "explain", "use"}:
        raise ValueError("Only read statements are allowed")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise ValueError("Query contains a forbidden mutation keyword")


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a Snowflake SQL API response into column-keyed row dicts.

    The SQL API returns ``{"resultSetMetaData": {"rowType": [{"name": ...,
    ...}, ...]}, "data": [[v1, v2, ...], ...]}``. We map each row array
    onto a dict keyed by the user-facing column names so summaries are
    self-describing.
    """
    metadata: dict[str, Any] = payload.get("resultSetMetaData") or {}
    row_types: list[Any] = metadata.get("rowType") or []
    columns: list[str] = []
    for row_type in row_types:
        if not isinstance(row_type, dict):
            continue
        row_type_dict = cast("dict[str, Any]", row_type)
        name: Any = row_type_dict.get("name")
        if name is not None:
            columns.append(str(name))
    data: list[Any] = payload.get("data") or []
    rows: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, list):
            row_list = cast("list[Any]", row)
            rows.append(dict(zip(columns, row_list, strict=False)))
        elif isinstance(row, dict):
            row_dict = cast("dict[str, Any]", row)
            rows.append(dict(row_dict))
    return rows


def _paginate_summary(
    rows: list[dict[str, Any]],
    *,
    key: str,
    ref_prefix: str,
    max_results: int,
    summary_keys: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Wrap a row list into the standard summary envelope.

    If ``summary_keys`` is supplied, the summary only carries those keys
    from each row (plus the synthetic ``*_ref``). Otherwise the full row
    is included.
    """
    total = len(rows)
    slice_ = rows[:max_results]
    summaries: list[dict[str, Any]] = []
    for index, row in enumerate(slice_, start=1):
        if summary_keys is None:
            payload = dict(row)
        else:
            payload = {k: row.get(k) for k in summary_keys if k in row}
        summary = {f"{ref_prefix}_ref": f"{ref_prefix}_{index}", **payload}
        summaries.append(summary)
    return {
        key: summaries,
        "returned": len(summaries),
        "total": total,
        "truncated": total > len(summaries),
    }


@toolset(prefix="snowflake")
class SnowflakeToolSet:
    """A connector for the Snowflake SQL API v2.

    Args:
        account: Snowflake account identifier, e.g. ``"xy12345.us-east-1"``.
        token: OAuth bearer or key-pair JWT access token (not a password).
        token_type: Value for the ``X-Snowflake-Authorization-Token-Type``
            header. Defaults to ``"OAUTH"``; pass ``"KEYPAIR_JWT"`` (or
            ``"PROGRAMMATIC_ACCESS_TOKEN"``) to match the token kind, or
            ``None`` to omit the header and let Snowflake auto-detect.
        warehouse: Default warehouse name.
        database: Default database name.
        schema: Default schema name.
        role: Default role name.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="snowflake",
        display_name="Snowflake",
        version="0.1.0",
        description="Read-only Snowflake SQL execution via the SQL API v2.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.SERVICE_ACCOUNT, AuthMode.CUSTOM),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.snowflake.com/en/developer-guide/sql-api/index",
        homepage_url="https://www.snowflake.com/",
        tags=("database", "warehouse"),
    )

    def __init__(
        self,
        *,
        account: str,
        token: str,
        token_type: str | None = _DEFAULT_TOKEN_TYPE,
        warehouse: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        role: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
        request_timeout_seconds: int = 60,
    ) -> None:
        if not account or not token:
            raise ValueError("account and token are required")
        self.connection = connection
        self._defaults = {
            "warehouse": warehouse,
            "database": database,
            "schema": schema,
            "role": role,
        }
        self._timeout = request_timeout_seconds
        default_headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if token_type is not None:
            default_headers[_TOKEN_TYPE_HEADER] = token_type
        self._client = HttpClient(
            base_url=f"https://{account}.snowflakecomputing.com",
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers=default_headers,
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _submit_statement(
        self,
        sql: str,
        *,
        bindings: dict[str, Any] | None = None,
        async_exec: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"statement": sql, "timeout": self._timeout}
        for key, value in self._defaults.items():
            if value is not None:
                payload[key] = value
        if bindings is not None:
            payload["bindings"] = bindings
        params = {"async": "true"} if async_exec else None
        return self._client.post(
            "/api/v2/statements",
            params=params,
            json=payload,
        ).json()

    # MARK: - SQL execution

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_query(
        self,
        sql: str,
        *,
        bindings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a read-only SQL statement synchronously.

        Use this once :meth:`list_tables` and :meth:`describe_table` have
        clarified the schema. Returns the raw Snowflake SQL API response —
        ``{"resultSetMetaData": {...}, "data": [...]}`` for sync results,
        plus ``statementHandle`` and pagination headers. The natural row
        shape is array-of-arrays under ``data`` with column names under
        ``resultSetMetaData.rowType[*].name``.

        Args:
            sql: ``SELECT``/``WITH``/``SHOW``/``DESCRIBE``/``EXPLAIN``/
                ``USE`` statement. Compound statements and mutation
                keywords are rejected.
            bindings: Optional Snowflake bind variables — a dict where
                each value is ``{"type": <Snowflake type>, "value":
                <literal>}``. Always parameterize untrusted values.

        Safety: this connector is read-only by design. Writes belong on
        a separate destructive connector.
        """
        _validate_read_only_sql(sql)
        return self._submit_statement(sql, bindings=bindings)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def submit_async_query(
        self,
        sql: str,
        *,
        bindings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit a read-only query asynchronously.

        Returns a payload with ``statementHandle``. Poll with
        :meth:`get_statement` until ``status`` reports completion. Useful
        for long-running queries that exceed the synchronous timeout.
        """
        _validate_read_only_sql(sql)
        return self._submit_statement(sql, bindings=bindings, async_exec=True)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_statement(self, statement_handle: str, *, partition: int = 0) -> dict[str, Any]:
        """Fetch the status / results of a previously submitted statement.

        Pass the ``statementHandle`` returned by :meth:`submit_async_query`.
        ``partition`` selects a specific result partition for large
        result sets (0 by default).
        """
        if not statement_handle:
            raise ValueError("statement_handle must be a non-empty string")
        params: dict[str, Any] | None = {"partition": partition} if partition else None
        return self._client.get(
            f"/api/v2/statements/{statement_handle}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_statement(self, statement_handle: str) -> dict[str, Any]:
        """Cancel a running statement.

        Destructive: aborts the in-flight query. Confirm with the user
        before calling — partially produced result partitions may be
        discarded.
        """
        if not statement_handle:
            raise ValueError("statement_handle must be a non-empty string")
        return self._client.post(
            f"/api/v2/statements/{statement_handle}/cancel",
        ).json()

    # MARK: - Catalog helpers (build small SHOW queries)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_DATABASES_OUTPUT)
    def list_databases(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List databases accessible to the role.

        Best first tool when the active database is not yet known.
        Returns ``{"databases", "returned", "total", "truncated"}``. Each
        entry has ``database_ref`` and the user-facing ``name`` (and
        related ``SHOW DATABASES`` columns). Pass ``name`` as the
        ``database`` argument of :meth:`list_schemas` or
        :meth:`list_tables`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        payload = self._submit_statement("SHOW DATABASES")
        rows = _rows_from_payload(payload)
        return _paginate_summary(
            rows,
            key="databases",
            ref_prefix="database",
            max_results=max_results,
            summary_keys=("name", "kind", "owner", "created_on"),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_SCHEMAS_OUTPUT)
    def list_schemas(
        self,
        *,
        database: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List schemas, optionally scoped to ``database``.

        Returns ``{"schemas", "returned", "total", "truncated"}``. Each
        entry has ``schema_ref``, the user-facing ``name``, and parent
        ``database_name``. Pass ``database`` + ``name`` to
        :meth:`list_tables`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        if database is not None:
            self._validate_identifier(database)
            sql = f"SHOW SCHEMAS IN DATABASE {database}"
        else:
            sql = "SHOW SCHEMAS"
        payload = self._submit_statement(sql)
        rows = _rows_from_payload(payload)
        return _paginate_summary(
            rows,
            key="schemas",
            ref_prefix="schema",
            max_results=max_results,
            summary_keys=("name", "database_name", "owner", "created_on"),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_TABLES_OUTPUT)
    def list_tables(
        self,
        *,
        database: str | None = None,
        schema: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List tables. Pass ``database`` and ``schema`` to scope.

        Best first tool for schema exploration once you have a database
        and schema. Returns ``{"tables", "returned", "total",
        "truncated"}``. Each entry carries ``table_ref``, the user-facing
        ``name``, plus parent ``database_name`` / ``schema_name`` and the
        Snowflake ``kind`` (``"TABLE"``, ``"TEMPORARY"``, ``"TRANSIENT"``,
        ``"EXTERNAL"``). Pass ``name`` to :meth:`describe_table`.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        target = self._scope_target(database, schema, kind="SCHEMA")
        sql = f"SHOW TABLES IN {target}" if target else "SHOW TABLES"
        payload = self._submit_statement(sql)
        rows = _rows_from_payload(payload)
        return _paginate_summary(
            rows,
            key="tables",
            ref_prefix="table",
            max_results=max_results,
            summary_keys=("name", "database_name", "schema_name", "kind", "rows", "bytes"),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_VIEWS_OUTPUT)
    def list_views(
        self,
        *,
        database: str | None = None,
        schema: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List views in the chosen scope.

        Returns ``{"views", "returned", "total", "truncated"}``. Each
        entry carries ``view_ref``, the user-facing ``name``, parent
        ``database_name`` / ``schema_name``, and ``owner``.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        target = self._scope_target(database, schema, kind="SCHEMA")
        sql = f"SHOW VIEWS IN {target}" if target else "SHOW VIEWS"
        payload = self._submit_statement(sql)
        rows = _rows_from_payload(payload)
        return _paginate_summary(
            rows,
            key="views",
            ref_prefix="view",
            max_results=max_results,
            summary_keys=("name", "database_name", "schema_name", "owner", "is_secure"),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_table(
        self,
        name: str,
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Describe columns of a table.

        Run after :meth:`list_tables`. Returns the raw Snowflake
        ``DESCRIBE TABLE`` response — column descriptors live under
        ``data`` (one row per column) with names under
        ``resultSetMetaData.rowType``.
        """
        self._validate_identifier(name)
        qualified = self._qualified_name(name, database, schema)
        return self._submit_statement(f"DESCRIBE TABLE {qualified}")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_WAREHOUSES_OUTPUT)
    def list_warehouses(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List warehouses accessible to the role.

        Returns ``{"warehouses", "returned", "total", "truncated"}``.
        Each entry has ``warehouse_ref`` and ``name`` plus key fields
        (``state``, ``size``, ``running``, ``queued``, ``auto_suspend``).
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        payload = self._submit_statement("SHOW WAREHOUSES")
        rows = _rows_from_payload(payload)
        return _paginate_summary(
            rows,
            key="warehouses",
            ref_prefix="warehouse",
            max_results=max_results,
            summary_keys=("name", "state", "size", "running", "queued", "auto_suspend"),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def server_version(self) -> dict[str, Any]:
        """Return ``CURRENT_VERSION()`` and current account.

        Returns the raw SQL API response. The single row in ``data``
        carries Snowflake's version string and the account identifier.
        """
        return self._submit_statement(
            "SELECT CURRENT_VERSION() AS version, CURRENT_ACCOUNT() AS account"
        )

    # MARK: - Helpers

    @staticmethod
    def _validate_identifier(identifier: str) -> None:
        if not identifier:
            raise ValueError("identifier must be a non-empty string")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", identifier):
            raise ValueError("identifier must match ^[A-Za-z_][A-Za-z0-9_$]*$ (no quotes)")

    @classmethod
    def _qualified_name(
        cls,
        name: str,
        database: str | None,
        schema: str | None,
    ) -> str:
        cls._validate_identifier(name)
        parts: list[str] = []
        if database is not None:
            cls._validate_identifier(database)
            parts.append(database)
        if schema is not None:
            cls._validate_identifier(schema)
            parts.append(schema)
        parts.append(name)
        return ".".join(parts)

    @classmethod
    def _scope_target(
        cls,
        database: str | None,
        schema: str | None,
        *,
        kind: str,
    ) -> str | None:
        if database is None and schema is None:
            return None
        if schema is not None:
            return f"{kind} {cls._qualified_name(schema, database, None)}"
        assert database is not None
        cls._validate_identifier(database)
        return f"DATABASE {database}"
