# pyright: strict
from __future__ import annotations

from typing import cast

from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.magento import MagentoToolSet
from maivn_tools.testing import MockTransport


def _connector() -> MagentoToolSet:
    return MagentoToolSet(
        base_url="https://store.example.com",
        access_token="token",
        transport=MockTransport(),
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


def test_magento_list_tools_register_first_class_output_schemas() -> None:
    connector = _connector()
    agent = _make_agent()
    tools = agent.add_toolset(connector)

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool name, expected array property key)
    expected: dict[str, str] = {
        "MAGENTO_list_products": "products",
        "MAGENTO_list_orders": "orders",
        "MAGENTO_list_customers": "customers",
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_magento_output_schemas_not_published_through_metadata() -> None:
    connector = _connector()
    for method in (
        connector.list_products,
        connector.list_orders,
        connector.list_customers,
    ):
        opts = get_toolify_options(method)
        assert opts is not None
        assert "output_schema" not in opts.metadata
