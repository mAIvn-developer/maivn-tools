# pyright: strict
from __future__ import annotations

from typing import cast

from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.microsoft_graph import (
    MicrosoftFilesToolSet,
    OutlookCalendarToolSet,
    OutlookMailToolSet,
)
from maivn_tools.testing import MockTransport


def _make_agent() -> Agent:
    config = MaivnConfiguration(
        server=ServerConfiguration(
            base_url="http://example.com",
            mock_base_url="http://example.com",
        )
    )
    client = Client.from_configuration(api_key="key", configuration=config)
    return Agent(name="t", client=client)


def test_microsoft_graph_list_tools_register_first_class_output_schemas() -> None:
    agent = _make_agent()
    tools = agent.add_toolset(OutlookMailToolSet(token="at", transport=MockTransport()))
    tools += agent.add_toolset(OutlookCalendarToolSet(token="at", transport=MockTransport()))
    tools += agent.add_toolset(MicrosoftFilesToolSet(token="at", transport=MockTransport()))

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool name, expected array property key)
    expected: dict[str, str] = {
        "OUTLOOK_MAIL_list_folders": "folders",
        "OUTLOOK_MAIL_search_messages": "messages",
        "OUTLOOK_MAIL_list_messages_in_folder": "messages",
        "OUTLOOK_CALENDAR_list_calendars": "calendars",
        "OUTLOOK_CALENDAR_list_events": "events",
        "OUTLOOK_CALENDAR_list_event_instances": "events",
        "MS_FILES_list_root_children": "items",
        "MS_FILES_search_files": "items",
        "MS_FILES_list_children": "items",
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_microsoft_graph_output_schemas_not_published_through_metadata() -> None:
    mail = OutlookMailToolSet(token="at", transport=MockTransport())
    calendar = OutlookCalendarToolSet(token="at", transport=MockTransport())
    files = MicrosoftFilesToolSet(token="at", transport=MockTransport())
    annotated = [
        mail.list_folders,
        mail.search_messages,
        mail.list_messages_in_folder,
        calendar.list_calendars,
        calendar.list_events,
        calendar.list_event_instances,
        files.list_root_children,
        files.search_files,
        files.list_children,
    ]
    for method in annotated:
        opts = get_toolify_options(method)
        assert opts is not None, f"{method.__name__} is not a toolify tool"
        assert "output_schema" not in opts.metadata
