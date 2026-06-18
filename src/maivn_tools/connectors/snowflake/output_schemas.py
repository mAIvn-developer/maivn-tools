# pyright: strict
"""First-class output schemas for the Snowflake toolset.

These document the connector-owned, normalized summary envelopes that the
catalog ``list_*`` tools build via ``_paginate_summary``. They are not the raw
Snowflake SQL API payloads: each schema mirrors exactly the compact dict the
connector emits -- a ``{<key>: [...], "returned", "total", "truncated"}``
envelope whose items carry a synthetic ``*_ref`` plus the selected
``summary_keys`` pulled from each ``SHOW ...`` row.

Tools that return the raw SQL API response unchanged (``run_query``,
``submit_async_query``, ``get_statement``, ``describe_table``,
``server_version``) are provider-dependent and intentionally not annotated.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``summary_keys`` selections)

_DATABASE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "database_ref": {"type": "string"},
        "name": {"type": ["string", "null"]},
        "kind": {"type": ["string", "null"]},
        "owner": {"type": ["string", "null"]},
        "created_on": {"type": ["string", "null"]},
    },
    "required": ["database_ref"],
}

_SCHEMA_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "schema_ref": {"type": "string"},
        "name": {"type": ["string", "null"]},
        "database_name": {"type": ["string", "null"]},
        "owner": {"type": ["string", "null"]},
        "created_on": {"type": ["string", "null"]},
    },
    "required": ["schema_ref"],
}

_TABLE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "table_ref": {"type": "string"},
        "name": {"type": ["string", "null"]},
        "database_name": {"type": ["string", "null"]},
        "schema_name": {"type": ["string", "null"]},
        "kind": {"type": ["string", "null"]},
        "rows": {"type": ["integer", "null"]},
        "bytes": {"type": ["integer", "null"]},
    },
    "required": ["table_ref"],
}

_VIEW_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "view_ref": {"type": "string"},
        "name": {"type": ["string", "null"]},
        "database_name": {"type": ["string", "null"]},
        "schema_name": {"type": ["string", "null"]},
        "owner": {"type": ["string", "null"]},
        "is_secure": {"type": ["boolean", "null"]},
    },
    "required": ["view_ref"],
}

_WAREHOUSE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "warehouse_ref": {"type": "string"},
        "name": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "size": {"type": ["string", "null"]},
        "running": {"type": ["integer", "null"]},
        "queued": {"type": ["integer", "null"]},
        "auto_suspend": {"type": ["integer", "null"]},
    },
    "required": ["warehouse_ref"],
}


# MARK: - Wrapper helper


def _envelope(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], returned, total, truncated}`` schema."""
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


# MARK: - Tool output schemas

LIST_DATABASES_OUTPUT: dict[str, JsonValue] = _envelope("databases", _DATABASE_SUMMARY)
LIST_SCHEMAS_OUTPUT: dict[str, JsonValue] = _envelope("schemas", _SCHEMA_SUMMARY)
LIST_TABLES_OUTPUT: dict[str, JsonValue] = _envelope("tables", _TABLE_SUMMARY)
LIST_VIEWS_OUTPUT: dict[str, JsonValue] = _envelope("views", _VIEW_SUMMARY)
LIST_WAREHOUSES_OUTPUT: dict[str, JsonValue] = _envelope("warehouses", _WAREHOUSE_SUMMARY)


__all__ = [
    "LIST_DATABASES_OUTPUT",
    "LIST_SCHEMAS_OUTPUT",
    "LIST_TABLES_OUTPUT",
    "LIST_VIEWS_OUTPUT",
    "LIST_WAREHOUSES_OUTPUT",
]
