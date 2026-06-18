# pyright: strict
from __future__ import annotations

from typing import cast

from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.google_workspace import (
    GmailToolSet,
    GoogleCalendarToolSet,
    GoogleDriveToolSet,
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


def _connectors() -> tuple[GmailToolSet, GoogleCalendarToolSet, GoogleDriveToolSet]:
    transport = MockTransport()
    gmail = GmailToolSet(token="tok", transport=transport)
    calendar = GoogleCalendarToolSet(token="tok", transport=transport)
    drive = GoogleDriveToolSet(token="tok", transport=transport)
    return gmail, calendar, drive


def test_google_workspace_list_tools_register_first_class_output_schemas() -> None:
    gmail, calendar, drive = _connectors()
    agent = _make_agent()
    tools = agent.add_toolset(gmail) + agent.add_toolset(calendar) + agent.add_toolset(drive)

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool name, expected array property key)
    expected: dict[str, str] = {
        "GMAIL_search_messages": "messages",
        "GOOGLE_CALENDAR_list_calendars": "calendars",
        "GOOGLE_CALENDAR_list_events": "events",
        "GOOGLE_CALENDAR_list_event_instances": "events",
        "GOOGLE_DRIVE_search_files": "files",
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_google_workspace_output_schemas_not_published_through_metadata() -> None:
    gmail, calendar, drive = _connectors()
    for method in (
        gmail.search_messages,
        calendar.list_calendars,
        calendar.list_events,
        calendar.list_event_instances,
        drive.search_files,
    ):
        opts = get_toolify_options(method)
        assert opts is not None
        assert "output_schema" not in opts.metadata
