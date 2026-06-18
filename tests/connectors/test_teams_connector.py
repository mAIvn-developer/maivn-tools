# pyright: strict
from __future__ import annotations

from typing import cast

from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.teams import MicrosoftTeamsToolSet
from maivn_tools.testing import MockTransport


def _connector() -> MicrosoftTeamsToolSet:
    return MicrosoftTeamsToolSet(token="at", transport=MockTransport())


def _make_agent() -> Agent:
    config = MaivnConfiguration(
        server=ServerConfiguration(
            base_url="http://example.com",
            mock_base_url="http://example.com",
        )
    )
    client = Client.from_configuration(api_key="key", configuration=config)
    return Agent(name="t", client=client)


def test_teams_list_tools_register_first_class_output_schemas() -> None:
    agent = _make_agent()
    tools = agent.add_toolset(_connector())

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool name, expected array property key)
    expected: dict[str, str] = {
        "TEAMS_list_joined_teams": "teams",
        "TEAMS_list_channels": "channels",
        "TEAMS_list_channel_messages": "messages",
        "TEAMS_list_chats": "chats",
        "TEAMS_list_chat_messages": "messages",
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_teams_output_schemas_not_published_through_metadata() -> None:
    connector = _connector()
    opts = get_toolify_options(connector.list_joined_teams)
    assert opts is not None
    assert "output_schema" not in opts.metadata
