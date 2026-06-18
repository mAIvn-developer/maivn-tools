# pyright: strict
from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.databases import (
    MySQLToolSet,
    PostgresToolSet,
    SQLiteToolSet,
    SQLServerToolSet,
)


def _make_agent() -> Agent:
    config = MaivnConfiguration(
        server=ServerConfiguration(
            base_url="http://example.com",
            mock_base_url="http://example.com",
        )
    )
    client = Client.from_configuration(api_key="key", configuration=config)
    return Agent(name="t", client=client)


def _postgres() -> PostgresToolSet:
    return PostgresToolSet(connection_factory=lambda: cast("object", None))  # type: ignore[arg-type]


def _mysql() -> MySQLToolSet:
    return MySQLToolSet(connection_factory=lambda: cast("object", None))  # type: ignore[arg-type]


def _sqlserver() -> SQLServerToolSet:
    return SQLServerToolSet(connection_factory=lambda: cast("object", None))  # type: ignore[arg-type]


def _sqlite() -> SQLiteToolSet:
    return SQLiteToolSet(":memory:")


# (tool name, expected array property key) for each toolset's annotated tools.
_POSTGRES_ARRAYS: dict[str, str] = {
    "POSTGRES_list_tables": "tables",
    "POSTGRES_list_schemas": "schemas",
    "POSTGRES_list_views": "views",
    "POSTGRES_list_indexes": "indexes",
    "POSTGRES_describe_table": "columns",
    "POSTGRES_run_query": "rows",
    "POSTGRES_sample_table": "rows",
    "POSTGRES_explain_query": "rows",
}
_MYSQL_ARRAYS: dict[str, str] = {
    "MYSQL_list_databases": "databases",
    "MYSQL_list_tables": "tables",
    "MYSQL_list_indexes": "indexes",
    "MYSQL_describe_table": "columns",
    "MYSQL_run_query": "rows",
    "MYSQL_sample_table": "rows",
    "MYSQL_explain_query": "rows",
}
_SQLITE_ARRAYS: dict[str, str] = {
    "SQLITE_list_tables": "tables",
    "SQLITE_list_views": "views",
    "SQLITE_list_indexes": "indexes",
    "SQLITE_describe_table": "columns",
    "SQLITE_run_query": "rows",
    "SQLITE_sample_table": "rows",
    "SQLITE_explain_query": "rows",
}
_SQLSERVER_ARRAYS: dict[str, str] = {
    "SQLSERVER_list_databases": "databases",
    "SQLSERVER_list_schemas": "schemas",
    "SQLSERVER_list_tables": "tables",
    "SQLSERVER_list_views": "views",
    "SQLSERVER_describe_table": "columns",
    "SQLSERVER_run_query": "rows",
    "SQLSERVER_sample_table": "rows",
}


def _assert_array_schemas(schemas_by_name: Mapping[str, object], expected: dict[str, str]) -> None:
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_databases_register_first_class_output_schemas() -> None:
    agent = _make_agent()
    pairs = (
        (_postgres(), _POSTGRES_ARRAYS),
        (_mysql(), _MYSQL_ARRAYS),
        (_sqlite(), _SQLITE_ARRAYS),
        (_sqlserver(), _SQLSERVER_ARRAYS),
    )
    for connector, expected in pairs:
        tools = agent.add_toolset(connector)
        schemas_by_name = {tool.name: tool.output_schema for tool in tools}
        _assert_array_schemas(schemas_by_name, expected)


def test_databases_output_schemas_not_published_through_metadata() -> None:
    methods = (
        _postgres().list_tables,
        _postgres().run_query,
        _mysql().list_databases,
        _sqlite().list_tables,
        _sqlserver().list_tables,
    )
    for method in methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert "output_schema" not in opts.metadata
