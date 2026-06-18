# pyright: strict
"""First-class output schemas for the database toolsets.

These mirror the connector-owned, normalized shapes that the PostgreSQL,
MySQL/MariaDB, SQLite, and SQL Server read tools build from raw DB-API rows.
None of these tools return a raw provider payload: every shape here is
constructed by the connector itself (the ``_paginate_summary`` summary
envelope, the ``_run_select`` query envelope, or an explicitly assembled
dict), so the assignment planner and repair loop can resolve fields like
``table_ref``, ``row_count``, or ``primary_key`` without guessing.

Each schema is grounded only in the connector's own builders. Item rows that
carry arbitrary SQL-aliased columns are described as open objects with the
fixed columns the connector's SQL always produces.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Wrapper helpers


def _summary(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build the ``_paginate_summary`` envelope schema.

    Shape: ``{<item_key>: [...], returned: int, total: int, truncated: bool}``.
    """
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "returned": {"type": "integer"},
            "total": {"type": "integer"},
            "truncated": {"type": "boolean"},
        },
        "required": [item_key, "returned", "total", "truncated"],
    }


# A row from ``_run_select`` / SQLite ``run_query``: a dict keyed by the
# query's column names. Columns are dynamic, so the row object is open.
_ROW: dict[str, JsonValue] = {"type": "object"}

# The shared ``{columns, rows, row_count, truncated}`` query envelope that
# ``run_query`` and ``sample_table`` return.
_QUERY_RESULT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": _ROW},
        "row_count": {"type": "integer"},
        "truncated": {"type": "boolean"},
    },
    "required": ["columns", "rows", "row_count", "truncated"],
}

QUERY_RESULT_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT


# MARK: - Item summaries (mirror the SQL ``AS`` aliases + the ref prefix)

# Each summary row is ``{<prefix>_ref, **row}``; ``additionalProperties`` is
# left at the JSON-schema default so the natural row columns pass through.

_PG_TABLE_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "schema": {"type": "string"},
    },
    "required": ["table_ref", "name"],
}

_PG_SCHEMA_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema_ref": {"type": "string"},
        "name": {"type": "string"},
    },
    "required": ["schema_ref", "name"],
}

_PG_VIEW_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "view_ref": {"type": "string"},
        "name": {"type": "string"},
        "schema": {"type": "string"},
    },
    "required": ["view_ref", "name"],
}

_PG_INDEX_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "index_ref": {"type": "string"},
        "name": {"type": "string"},
        "schema": {"type": "string"},
        "table": {"type": "string"},
        "definition": {"type": "string"},
    },
    "required": ["index_ref", "name"],
}

_MYSQL_DATABASE_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "database_ref": {"type": "string"},
        "Database": {"type": "string"},
    },
    "required": ["database_ref"],
}

_MYSQL_TABLE_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "schema": {"type": "string"},
    },
    "required": ["table_ref", "name"],
}

_MYSQL_INDEX_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "index_ref": {"type": "string"},
    },
    "required": ["index_ref"],
}

_SQLITE_TABLE_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
    },
    "required": ["table_ref", "name", "type"],
}

_SQLITE_VIEW_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "view_ref": {"type": "string"},
        "name": {"type": "string"},
        "sql": {"type": ["string", "null"]},
    },
    "required": ["view_ref", "name"],
}

_SQLITE_INDEX_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "index_ref": {"type": "string"},
        "name": {"type": "string"},
        "table": {"type": "string"},
        "sql": {"type": ["string", "null"]},
    },
    "required": ["index_ref", "name", "table"],
}

_SQLSERVER_DATABASE_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "database_ref": {"type": "string"},
        "name": {"type": "string"},
    },
    "required": ["database_ref", "name"],
}

_SQLSERVER_SCHEMA_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema_ref": {"type": "string"},
        "name": {"type": "string"},
    },
    "required": ["schema_ref", "name"],
}

_SQLSERVER_TABLE_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "schema": {"type": "string"},
    },
    "required": ["table_ref", "name"],
}

_SQLSERVER_VIEW_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "view_ref": {"type": "string"},
        "name": {"type": "string"},
        "schema": {"type": "string"},
    },
    "required": ["view_ref", "name"],
}


# MARK: - PostgreSQL tool outputs

PG_LIST_TABLES_OUTPUT: dict[str, JsonValue] = _summary("tables", _PG_TABLE_ITEM)
PG_LIST_SCHEMAS_OUTPUT: dict[str, JsonValue] = _summary("schemas", _PG_SCHEMA_ITEM)
PG_LIST_VIEWS_OUTPUT: dict[str, JsonValue] = _summary("views", _PG_VIEW_ITEM)
PG_LIST_INDEXES_OUTPUT: dict[str, JsonValue] = _summary("indexes", _PG_INDEX_ITEM)

PG_DESCRIBE_TABLE_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "schema": {"type": "string"},
        "columns": {"type": "array", "items": _ROW},
        "primary_key": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "schema", "columns", "primary_key"],
}

PG_GET_TABLE_SIZE_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "name": {"type": "string"},
        "total_bytes": {"type": ["integer", "null"]},
        "table_bytes": {"type": ["integer", "null"]},
    },
    "required": ["schema", "name"],
}

PG_COUNT_ROWS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "name": {"type": "string"},
        "row_count": {"type": "integer"},
    },
    "required": ["schema", "name", "row_count"],
}

PG_SERVER_VERSION_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "version": {"type": ["string", "null"]},
        "database": {"type": ["string", "null"]},
    },
    "required": ["version", "database"],
}

PG_LIST_FOREIGN_KEYS_OUTPUT: dict[str, JsonValue] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "column": {"type": "string"},
            "foreign_schema": {"type": "string"},
            "foreign_table": {"type": "string"},
            "foreign_column": {"type": "string"},
        },
        "required": ["name", "column"],
    },
}

PG_LIST_EXTENSIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "version": {"type": ["string", "null"]},
        },
        "required": ["name"],
    },
}

PG_RUN_QUERY_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT
PG_SAMPLE_TABLE_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT
PG_EXPLAIN_QUERY_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT


# MARK: - MySQL tool outputs

MYSQL_LIST_DATABASES_OUTPUT: dict[str, JsonValue] = _summary("databases", _MYSQL_DATABASE_ITEM)
MYSQL_LIST_TABLES_OUTPUT: dict[str, JsonValue] = _summary("tables", _MYSQL_TABLE_ITEM)
MYSQL_LIST_INDEXES_OUTPUT: dict[str, JsonValue] = _summary("indexes", _MYSQL_INDEX_ITEM)

MYSQL_DESCRIBE_TABLE_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema": {"type": ["string", "null"]},
        "name": {"type": "string"},
        "columns": {"type": "array", "items": _ROW},
        "primary_key": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "columns", "primary_key"],
}

MYSQL_COUNT_ROWS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema": {"type": ["string", "null"]},
        "name": {"type": "string"},
        "row_count": {"type": "integer"},
    },
    "required": ["name", "row_count"],
}

MYSQL_SERVER_VERSION_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "version": {"type": ["string", "null"]},
        "database": {"type": ["string", "null"]},
    },
    "required": ["version", "database"],
}

MYSQL_RUN_QUERY_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT
MYSQL_SAMPLE_TABLE_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT
MYSQL_EXPLAIN_QUERY_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT


# MARK: - SQLite tool outputs

SQLITE_LIST_TABLES_OUTPUT: dict[str, JsonValue] = _summary("tables", _SQLITE_TABLE_ITEM)
SQLITE_LIST_VIEWS_OUTPUT: dict[str, JsonValue] = _summary("views", _SQLITE_VIEW_ITEM)
SQLITE_LIST_INDEXES_OUTPUT: dict[str, JsonValue] = _summary("indexes", _SQLITE_INDEX_ITEM)

SQLITE_DESCRIBE_TABLE_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cid": {"type": "integer"},
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "notnull": {"type": "boolean"},
                    "default": {"type": ["string", "null"]},
                    "primary_key": {"type": "boolean"},
                },
                "required": ["cid", "name", "type", "notnull", "primary_key"],
            },
        },
        "indexes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "unique": {"type": "boolean"},
                    "origin": {"type": "string"},
                    "partial": {"type": "boolean"},
                },
                "required": ["name", "unique", "origin", "partial"],
            },
        },
        "foreign_keys": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "table": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": ["string", "null"]},
                    "on_delete": {"type": "string"},
                    "on_update": {"type": "string"},
                },
                "required": ["id", "table", "from"],
            },
        },
    },
    "required": ["name", "columns", "indexes", "foreign_keys"],
}

SQLITE_LIST_FOREIGN_KEYS_OUTPUT: dict[str, JsonValue] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "seq": {"type": "integer"},
            "table": {"type": "string"},
            "from": {"type": "string"},
            "to": {"type": ["string", "null"]},
            "on_update": {"type": "string"},
            "on_delete": {"type": "string"},
            "match": {"type": "string"},
        },
        "required": ["id", "table", "from"],
    },
}

SQLITE_EXPLAIN_QUERY_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "plan": {"type": "boolean"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": _ROW},
    },
    "required": ["plan", "columns", "rows"],
}

SQLITE_GET_SCHEMA_DUMP_OUTPUT: dict[str, JsonValue] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "name": {"type": "string"},
            "table": {"type": ["string", "null"]},
            "sql": {"type": ["string", "null"]},
        },
        "required": ["type", "name"],
    },
}

SQLITE_COUNT_ROWS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table": {"type": "string"},
        "row_count": {"type": "integer"},
    },
    "required": ["table", "row_count"],
}

SQLITE_RUN_QUERY_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT
SQLITE_SAMPLE_TABLE_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT


# MARK: - SQL Server tool outputs

SQLSERVER_LIST_DATABASES_OUTPUT: dict[str, JsonValue] = _summary(
    "databases", _SQLSERVER_DATABASE_ITEM
)
SQLSERVER_LIST_SCHEMAS_OUTPUT: dict[str, JsonValue] = _summary("schemas", _SQLSERVER_SCHEMA_ITEM)
SQLSERVER_LIST_TABLES_OUTPUT: dict[str, JsonValue] = _summary("tables", _SQLSERVER_TABLE_ITEM)
SQLSERVER_LIST_VIEWS_OUTPUT: dict[str, JsonValue] = _summary("views", _SQLSERVER_VIEW_ITEM)

SQLSERVER_DESCRIBE_TABLE_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "name": {"type": "string"},
        "columns": {"type": "array", "items": _ROW},
        "primary_key": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["schema", "name", "columns", "primary_key"],
}

SQLSERVER_COUNT_ROWS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "name": {"type": "string"},
        "row_count": {"type": "integer"},
    },
    "required": ["schema", "name", "row_count"],
}

SQLSERVER_SERVER_VERSION_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "version": {"type": ["string", "null"]},
        "database": {"type": ["string", "null"]},
    },
    "required": ["version", "database"],
}

SQLSERVER_RUN_QUERY_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT
SQLSERVER_SAMPLE_TABLE_OUTPUT: dict[str, JsonValue] = _QUERY_RESULT


__all__ = [
    "MYSQL_COUNT_ROWS_OUTPUT",
    "MYSQL_DESCRIBE_TABLE_OUTPUT",
    "MYSQL_EXPLAIN_QUERY_OUTPUT",
    "MYSQL_LIST_DATABASES_OUTPUT",
    "MYSQL_LIST_INDEXES_OUTPUT",
    "MYSQL_LIST_TABLES_OUTPUT",
    "MYSQL_RUN_QUERY_OUTPUT",
    "MYSQL_SAMPLE_TABLE_OUTPUT",
    "MYSQL_SERVER_VERSION_OUTPUT",
    "PG_COUNT_ROWS_OUTPUT",
    "PG_DESCRIBE_TABLE_OUTPUT",
    "PG_EXPLAIN_QUERY_OUTPUT",
    "PG_GET_TABLE_SIZE_OUTPUT",
    "PG_LIST_EXTENSIONS_OUTPUT",
    "PG_LIST_FOREIGN_KEYS_OUTPUT",
    "PG_LIST_INDEXES_OUTPUT",
    "PG_LIST_SCHEMAS_OUTPUT",
    "PG_LIST_TABLES_OUTPUT",
    "PG_LIST_VIEWS_OUTPUT",
    "PG_RUN_QUERY_OUTPUT",
    "PG_SAMPLE_TABLE_OUTPUT",
    "PG_SERVER_VERSION_OUTPUT",
    "QUERY_RESULT_OUTPUT",
    "SQLITE_COUNT_ROWS_OUTPUT",
    "SQLITE_DESCRIBE_TABLE_OUTPUT",
    "SQLITE_EXPLAIN_QUERY_OUTPUT",
    "SQLITE_GET_SCHEMA_DUMP_OUTPUT",
    "SQLITE_LIST_FOREIGN_KEYS_OUTPUT",
    "SQLITE_LIST_INDEXES_OUTPUT",
    "SQLITE_LIST_TABLES_OUTPUT",
    "SQLITE_LIST_VIEWS_OUTPUT",
    "SQLITE_RUN_QUERY_OUTPUT",
    "SQLITE_SAMPLE_TABLE_OUTPUT",
    "SQLSERVER_COUNT_ROWS_OUTPUT",
    "SQLSERVER_DESCRIBE_TABLE_OUTPUT",
    "SQLSERVER_LIST_DATABASES_OUTPUT",
    "SQLSERVER_LIST_SCHEMAS_OUTPUT",
    "SQLSERVER_LIST_TABLES_OUTPUT",
    "SQLSERVER_LIST_VIEWS_OUTPUT",
    "SQLSERVER_RUN_QUERY_OUTPUT",
    "SQLSERVER_SAMPLE_TABLE_OUTPUT",
    "SQLSERVER_SERVER_VERSION_OUTPUT",
]
