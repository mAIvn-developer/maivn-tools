# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.google_chat import GoogleChatToolSet
from maivn_tools.connectors.teams import MicrosoftTeamsToolSet
from maivn_tools.connectors.zoom import ZoomToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Microsoft Teams


def _teams() -> tuple[MicrosoftTeamsToolSet, MockTransport]:
    transport = MockTransport()
    return MicrosoftTeamsToolSet(token="graph-token", transport=transport), transport


def test_teams_joined_teams_and_get_team() -> None:
    connector, transport = _teams()
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"id": "t1"}))
    connector.list_joined_teams()
    connector.get_team("t1")
    assert transport.requests[0].url.endswith("/me/joinedTeams")
    with pytest.raises(ValueError):
        connector.get_team("")


def test_teams_channels_lifecycle() -> None:
    connector, transport = _teams()
    for _ in range(5):
        transport.enqueue(json_response({"id": "c1"}))
    connector.list_channels("t1")
    connector.get_channel("t1", "c1")
    connector.create_channel("t1", display_name="planning", description="d")
    connector.create_channel("t1", display_name="x", membership_type="private")
    connector.delete_channel("t1", "c1")
    assert transport.requests[2].json_body["displayName"] == "planning"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_channels("")
    with pytest.raises(ValueError):
        connector.get_channel("", "c1")
    with pytest.raises(ValueError):
        connector.create_channel("t1", display_name="")
    with pytest.raises(ValueError):
        connector.create_channel("t1", display_name="x", membership_type="bogus")
    with pytest.raises(ValueError):
        connector.delete_channel("", "c1")


def test_teams_channel_messages() -> None:
    connector, transport = _teams()
    for _ in range(4):
        transport.enqueue(json_response({"id": "m1"}))
    connector.list_channel_messages("t1", "c1", top=20)
    connector.send_channel_message("t1", "c1", content="<p>Hi</p>", subject="Announce")
    connector.list_channel_replies("t1", "c1", "m1")
    connector.reply_to_channel_message("t1", "c1", "m1", content="<p>OK</p>")
    body = transport.requests[1].json_body
    assert body["body"]["content"] == "<p>Hi</p>"
    assert body["subject"] == "Announce"
    with pytest.raises(ValueError):
        connector.list_channel_messages("", "c1")
    with pytest.raises(ValueError):
        connector.send_channel_message("t1", "c1", content="", content_type="html")
    with pytest.raises(ValueError):
        connector.send_channel_message("t1", "c1", content="x", content_type="md")
    with pytest.raises(ValueError):
        connector.list_channel_replies("t1", "", "m1")
    with pytest.raises(ValueError):
        connector.reply_to_channel_message("", "c1", "m1", content="x")


def test_teams_members_and_chats() -> None:
    connector, transport = _teams()
    for _ in range(5):
        transport.enqueue(json_response({"value": []}))
    connector.list_members("t1")
    connector.add_member("t1", user_id="u1", roles=["owner"])
    connector.remove_member("t1", "memb1")
    connector.list_chats(top=5)
    connector.get_chat("ch1")
    assert "user@odata.bind" in transport.requests[1].json_body
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_members("")
    with pytest.raises(ValueError):
        connector.add_member("", user_id="u")
    with pytest.raises(ValueError):
        connector.remove_member("t1", "")
    with pytest.raises(ValueError):
        connector.get_chat("")


def test_teams_chat_messages() -> None:
    connector, transport = _teams()
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"id": "m"}))
    connector.list_chat_messages("ch1", top=10)
    connector.send_chat_message("ch1", content="hi")
    assert transport.requests[0].params == {"$top": 10}
    assert transport.requests[1].json_body["body"]["content"] == "hi"
    with pytest.raises(ValueError):
        connector.list_chat_messages("")
    with pytest.raises(ValueError):
        connector.send_chat_message("", content="hi")


# MARK: - Google Chat


def _gchat() -> tuple[GoogleChatToolSet, MockTransport]:
    transport = MockTransport()
    return GoogleChatToolSet(token="chat-token", transport=transport), transport


def test_gchat_spaces_lifecycle() -> None:
    connector, transport = _gchat()
    for _ in range(5):
        transport.enqueue(json_response({"spaces": []}))
    connector.list_spaces(page_size=10)
    connector.get_space("spaces/AAA")
    connector.create_space(display_name="planning")
    connector.search_spaces("ops")
    connector.delete_space("spaces/AAA")
    assert transport.requests[0].params["pageSize"] == 10
    assert transport.requests[2].json_body["displayName"] == "planning"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_spaces(page_size=0)
    with pytest.raises(ValueError):
        connector.get_space("")
    with pytest.raises(ValueError):
        connector.create_space(display_name="")
    with pytest.raises(ValueError):
        connector.create_space(display_name="x", space_type="bogus")
    with pytest.raises(ValueError):
        connector.delete_space("")
    with pytest.raises(ValueError):
        connector.search_spaces("")


def test_gchat_messages() -> None:
    connector, transport = _gchat()
    for _ in range(5):
        transport.enqueue(json_response({"name": "m"}))
    connector.list_messages("spaces/AAA", filter="createTime>0")
    connector.get_message("spaces/AAA/messages/m1")
    connector.send_message("spaces/AAA", text="hello", thread_key="t1", message_id="m1")
    connector.update_message("spaces/AAA/messages/m1", text="edit", update_mask="text")
    connector.delete_message("spaces/AAA/messages/m1")
    assert transport.requests[0].params["filter"] == "createTime>0"
    assert transport.requests[2].params["messageId"] == "m1"
    assert transport.requests[3].method == "PATCH"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_messages("")
    with pytest.raises(ValueError):
        connector.get_message("")
    with pytest.raises(ValueError):
        connector.send_message("")
    with pytest.raises(ValueError):
        connector.send_message("spaces/AAA")
    with pytest.raises(ValueError):
        connector.update_message("")
    with pytest.raises(ValueError):
        connector.delete_message("")


def test_gchat_members_and_reactions() -> None:
    connector, transport = _gchat()
    for _ in range(5):
        transport.enqueue(json_response({"members": []}))
    connector.list_members("spaces/AAA")
    connector.add_member("spaces/AAA", user_name="users/12345")
    connector.remove_member("spaces/AAA/members/12345")
    connector.create_reaction("spaces/AAA/messages/m1", emoji="🎉")
    connector.delete_reaction("spaces/AAA/messages/m1/reactions/r1")
    assert transport.requests[1].json_body["member"]["name"] == "users/12345"
    assert transport.requests[3].json_body["emoji"]["unicode"] == "🎉"
    with pytest.raises(ValueError):
        connector.list_members("")
    with pytest.raises(ValueError):
        connector.add_member("", user_name="u")
    with pytest.raises(ValueError):
        connector.remove_member("")
    with pytest.raises(ValueError):
        connector.create_reaction("", emoji="x")
    with pytest.raises(ValueError):
        connector.delete_reaction("")


# MARK: - Zoom


def _zoom() -> tuple[ZoomToolSet, MockTransport]:
    transport = MockTransport()
    return ZoomToolSet(token="z-token", transport=transport), transport


def test_zoom_requires_token() -> None:
    with pytest.raises(ValueError):
        ZoomToolSet(token="")


def test_zoom_users() -> None:
    connector, transport = _zoom()
    for _ in range(4):
        transport.enqueue(json_response({"users": []}))
    connector.list_users(status="active", page_number=1)
    connector.get_user()
    connector.create_user(action="create", email="a@b.com", first_name="A", last_name="B")
    connector.delete_user("a@b.com", action="delete")
    assert transport.requests[0].params["status"] == "active"
    assert transport.requests[2].json_body["action"] == "create"
    assert transport.requests[3].params == {"action": "delete"}
    with pytest.raises(ValueError):
        connector.list_users(status="bogus")
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.create_user(action="bogus", email="x")
    with pytest.raises(ValueError):
        connector.create_user(action="create", email="")
    with pytest.raises(ValueError):
        connector.delete_user("", action="delete")
    with pytest.raises(ValueError):
        connector.delete_user("u", action="bogus")


def test_zoom_meetings_lifecycle() -> None:
    connector, transport = _zoom()
    for _ in range(7):
        transport.enqueue(json_response({"meetings": []}))
    connector.list_meetings()
    connector.get_meeting(12345)
    connector.create_meeting(topic="Sync", start_time="2026-01-01T00:00:00Z")
    connector.update_meeting(12345, {"topic": "Renamed"})
    connector.list_meeting_participants(12345)
    connector.list_meeting_registrants(12345, status="approved")
    connector.delete_meeting(12345, schedule_for_reminder=True)
    assert transport.requests[2].json_body["topic"] == "Sync"
    assert transport.requests[6].params["schedule_for_reminder"] == "true"
    with pytest.raises(ValueError):
        connector.list_meetings("")
    with pytest.raises(ValueError):
        connector.list_meetings(type="bogus")
    with pytest.raises(ValueError):
        connector.get_meeting("")
    with pytest.raises(ValueError):
        connector.create_meeting(topic="")
    with pytest.raises(ValueError):
        connector.update_meeting("", {"x": 1})
    with pytest.raises(ValueError):
        connector.update_meeting(1, {})
    with pytest.raises(ValueError):
        connector.delete_meeting("")


def test_zoom_webinars_and_recordings() -> None:
    connector, transport = _zoom()
    for _ in range(6):
        transport.enqueue(json_response({"webinars": []}))
    connector.list_webinars()
    connector.get_webinar(99)
    connector.create_webinar(topic="Launch")
    connector.list_recordings(from_date="2026-01-01", to_date="2026-02-01")
    connector.get_meeting_recordings(12345)
    connector.delete_meeting_recordings(12345, action="delete")
    assert transport.requests[2].json_body["topic"] == "Launch"
    assert transport.requests[3].params["from"] == "2026-01-01"
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.create_webinar(topic="")
    with pytest.raises(ValueError):
        connector.delete_meeting_recordings(99, action="bogus")


# MARK: - Agent-ready: Teams summaries / tolerant inputs


def test_teams_list_joined_teams_summaries_hide_ids_by_default() -> None:
    connector, transport = _teams()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {"id": "team-guid-1", "displayName": "Engineering", "description": "eng"},
                    {"id": "team-guid-2", "displayName": "Sales", "description": "rev"},
                ]
            }
        )
    )
    result = connector.list_joined_teams()
    assert result["teams"][0]["team_ref"] == "team_1"
    assert result["teams"][0]["display_name"] == "Engineering"
    assert "team_id" not in result["teams"][0]
    assert result["teams"][1]["team_ref"] == "team_2"


def test_teams_list_joined_teams_can_return_ids() -> None:
    connector, transport = _teams()
    transport.enqueue(
        json_response({"value": [{"id": "team-guid-1", "displayName": "Engineering"}]})
    )
    result = connector.list_joined_teams(include_ids=True)
    assert result["teams"][0]["team_id"] == "team-guid-1"


def test_teams_list_channels_summaries_and_caching_for_friendly_writes() -> None:
    connector, transport = _teams()
    # list_channels populates cache; send_channel_message then accepts the
    # friendly display name.
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "channel-guid-1",
                        "displayName": "general",
                        "description": "Main channel",
                        "membershipType": "standard",
                    }
                ]
            }
        )
    )
    listed = connector.list_channels("team-guid-1")
    assert listed["channels"][0]["channel_ref"] == "channel_1"
    assert listed["channels"][0]["display_name"] == "general"
    assert "channel_id" not in listed["channels"][0]

    transport.enqueue(json_response({"id": "m1"}))
    connector.send_channel_message("team-guid-1", "general", content="<p>Hi</p>")
    sent_url = transport.requests[1].url
    assert "/teams/team-guid-1/channels/channel-guid-1/messages" in sent_url


def test_teams_send_channel_message_accepts_summary_dict() -> None:
    connector, transport = _teams()
    transport.enqueue(json_response({"id": "m1"}))
    summary = {"channel_id": "channel-guid-9", "display_name": "ops"}
    connector.send_channel_message({"team_id": "team-guid-2"}, summary, content="<p>Hi</p>")
    assert "/teams/team-guid-2/channels/channel-guid-9/messages" in transport.requests[0].url


def test_teams_list_channel_messages_summaries_hide_ids() -> None:
    connector, transport = _teams()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "msg-1",
                        "createdDateTime": "2026-05-16T12:00:00Z",
                        "body": {"contentType": "html", "content": "<p>Status update</p>"},
                        "from": {"user": {"displayName": "Alice"}},
                    }
                ]
            }
        )
    )
    result = connector.list_channel_messages("t1", "c1", top=10)
    msg = result["messages"][0]
    assert msg["message_ref"] == "message_1"
    assert msg["sender"] == "Alice"
    assert msg["content_preview"] == "Status update"
    assert "message_id" not in msg


def test_teams_list_chats_summaries_and_send_via_dict() -> None:
    connector, transport = _teams()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "chat-1",
                        "topic": "Sprint planning",
                        "chatType": "group",
                        "lastUpdatedDateTime": "2026-05-16T12:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_chats(top=10, include_ids=True)
    assert result["chats"][0]["chat_ref"] == "chat_1"
    assert result["chats"][0]["chat_id"] == "chat-1"

    transport.enqueue(json_response({"id": "m1"}))
    connector.send_chat_message(result["chats"][0], content="hi")
    assert "/chats/chat-1/messages" in transport.requests[1].url


def test_teams_destructive_tools_tagged() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _teams()
    for method in (connector.delete_channel, connector.remove_member):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - Agent-ready: Google Chat summaries / tolerant inputs


def test_gchat_list_spaces_summaries_hide_resource_names() -> None:
    connector, transport = _gchat()
    transport.enqueue(
        json_response(
            {
                "spaces": [
                    {
                        "name": "spaces/AAA",
                        "displayName": "Team planning",
                        "spaceType": "SPACE",
                    },
                    {
                        "name": "spaces/BBB",
                        "displayName": "Ops",
                        "spaceType": "SPACE",
                    },
                ]
            }
        )
    )
    result = connector.list_spaces(page_size=10)
    assert result["spaces"][0]["space_ref"] == "space_1"
    assert result["spaces"][0]["display_name"] == "Team planning"
    assert "space_name" not in result["spaces"][0]


def test_gchat_send_message_accepts_friendly_display_name() -> None:
    connector, transport = _gchat()
    transport.enqueue(
        json_response(
            {
                "spaces": [
                    {"name": "spaces/AAA", "displayName": "Team planning", "spaceType": "SPACE"}
                ]
            }
        )
    )
    connector.list_spaces(page_size=10)
    transport.enqueue(json_response({"name": "spaces/AAA/messages/m1"}))
    connector.send_message("Team planning", text="hello")
    assert "/v1/spaces/AAA/messages" in transport.requests[1].url


def test_gchat_send_message_accepts_summary_dict() -> None:
    connector, transport = _gchat()
    transport.enqueue(json_response({"name": "spaces/CCC/messages/m1"}))
    connector.send_message(
        {"space_name": "spaces/CCC", "display_name": "Eng"},
        text="hi",
    )
    assert "/v1/spaces/CCC/messages" in transport.requests[0].url


def test_gchat_list_messages_returns_summaries_without_ids() -> None:
    connector, transport = _gchat()
    transport.enqueue(
        json_response(
            {
                "messages": [
                    {
                        "name": "spaces/AAA/messages/m1",
                        "text": "Daily standup notes",
                        "createTime": "2026-05-16T09:00:00Z",
                        "sender": {"displayName": "Alice"},
                    }
                ],
                "nextPageToken": "tok2",
            }
        )
    )
    result = connector.list_messages("spaces/AAA")
    assert result["messages"][0]["message_ref"] == "message_1"
    assert result["messages"][0]["sender"] == "Alice"
    assert result["messages"][0]["text_preview"] == "Daily standup notes"
    assert "message_name" not in result["messages"][0]
    assert result["next_page_token"] == "tok2"


def test_gchat_update_message_accepts_summary_dict() -> None:
    connector, transport = _gchat()
    transport.enqueue(json_response({"name": "spaces/AAA/messages/m1"}))
    connector.update_message({"message_name": "spaces/AAA/messages/m1"}, text="edited")
    assert transport.requests[0].method == "PATCH"


def test_gchat_destructive_tools_tagged() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _gchat()
    for method in (
        connector.delete_space,
        connector.delete_message,
        connector.remove_member,
        connector.delete_reaction,
    ):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - Agent-ready: Zoom summaries / tolerant inputs


def test_zoom_list_meetings_returns_summaries_without_ids() -> None:
    connector, transport = _zoom()
    transport.enqueue(
        json_response(
            {
                "meetings": [
                    {
                        "id": 1111111,
                        "topic": "Standup",
                        "start_time": "2026-05-16T10:00:00Z",
                        "duration": 30,
                        "join_url": "https://zoom.us/j/1111111",
                    }
                ],
                "next_page_token": "next-tok",
            }
        )
    )
    result = connector.list_meetings()
    assert result["meetings"][0]["meeting_ref"] == "meeting_1"
    assert result["meetings"][0]["topic"] == "Standup"
    assert result["meetings"][0]["join_url"] == "https://zoom.us/j/1111111"
    assert "meeting_id" not in result["meetings"][0]
    assert result["next_page_token"] == "next-tok"


def test_zoom_list_meetings_can_include_ids() -> None:
    connector, transport = _zoom()
    transport.enqueue(json_response({"meetings": [{"id": 1234567, "topic": "Sync"}]}))
    result = connector.list_meetings(include_ids=True)
    assert result["meetings"][0]["meeting_id"] == 1234567


def test_zoom_get_meeting_accepts_summary_dict() -> None:
    connector, transport = _zoom()
    transport.enqueue(json_response({"meetings": [{"id": 7654321, "topic": "Review"}]}))
    listed = connector.list_meetings(include_ids=True)
    transport.enqueue(json_response({"id": 7654321}))
    connector.get_meeting(listed["meetings"][0])
    assert "/v2/meetings/7654321" in transport.requests[1].url


def test_zoom_update_and_delete_meeting_accept_meeting_dict() -> None:
    connector, transport = _zoom()
    transport.enqueue(json_response({"id": 5555555}))
    connector.update_meeting({"meeting_id": 5555555}, {"topic": "Renamed"})
    assert "/v2/meetings/5555555" in transport.requests[0].url
    transport.enqueue(json_response({}))
    connector.delete_meeting({"id": 6666666})
    assert "/v2/meetings/6666666" in transport.requests[1].url


def test_zoom_destructive_tools_tagged() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _zoom()
    for method in (
        connector.delete_user,
        connector.delete_meeting,
        connector.delete_meeting_recordings,
    ):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True
