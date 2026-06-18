# pyright: strict
from __future__ import annotations

from typing import cast

from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.infisical import InfisicalToolSet
from maivn_tools.testing import MockTransport


def _connector() -> tuple[InfisicalToolSet, MockTransport]:
    transport = MockTransport()
    connector = InfisicalToolSet(access_token="tok_secret", transport=transport)
    return connector, transport


def _make_agent() -> Agent:
    config = MaivnConfiguration(
        server=ServerConfiguration(
            base_url="http://example.com",
            mock_base_url="http://example.com",
        )
    )
    client = Client.from_configuration(api_key="key", configuration=config)
    return Agent(name="t", client=client)


def test_infisical_list_tools_register_first_class_output_schemas() -> None:
    connector, _ = _connector()
    agent = _make_agent()
    tools = agent.add_toolset(connector)

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool suffix, expected array property key)
    expected: dict[str, str] = {
        "INFISICAL_list_projects": "projects",
        "INFISICAL_list_secrets": "secrets",
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_infisical_output_schemas_not_published_through_metadata() -> None:
    connector, _ = _connector()
    for method in (connector.list_projects, connector.list_secrets):
        opts = get_toolify_options(method)
        assert opts is not None
        assert "output_schema" not in opts.metadata
