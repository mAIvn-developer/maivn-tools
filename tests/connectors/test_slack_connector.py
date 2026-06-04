# pyright: strict
from __future__ import annotations

from typing import cast

import pytest

from maivn_tools.connectors.slack import SlackApiError, SlackToolSet
from maivn_tools.testing import MockTransport, json_response


def _connector() -> tuple[SlackToolSet, MockTransport]:
    transport = MockTransport()
    connector = SlackToolSet(token="xoxb-secret", transport=transport)
    return connector, transport


def test_slack_connector_validates_token() -> None:
    with pytest.raises(ValueError):
        SlackToolSet(token="")


def test_slack_connector_is_a_toolset() -> None:
    from maivn._internal.utils.toolset import get_toolify_options, get_toolset_options

    opts = get_toolset_options(SlackToolSet)
    assert opts is not None
    assert opts.prefix == "slack"
    connector, _ = _connector()
    assert get_toolify_options(connector.auth_test) is not None
    assert get_toolify_options(connector.post_message) is not None


def test_auth_test_attaches_bearer_header() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "user": "bot"}))
    result = connector.auth_test()
    assert result["user"] == "bot"
    assert transport.requests[0].headers["Authorization"] == "Bearer xoxb-secret"


def test_user_lookup_dispatches_to_correct_path() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "user": {"id": "U1"}}))
    transport.enqueue(json_response({"ok": True, "user": {"id": "U2"}}))
    connector.user_lookup(user_id="U1")
    connector.user_lookup(email="user@example.test")
    assert transport.requests[0].url.endswith("/users.info")
    assert transport.requests[0].params == {"user": "U1"}
    assert transport.requests[1].url.endswith("/users.lookupByEmail")
    assert transport.requests[1].params == {"email": "user@example.test"}


def test_user_lookup_requires_exactly_one_identifier() -> None:
    connector, _ = _connector()
    with pytest.raises(ValueError):
        connector.user_lookup()
    with pytest.raises(ValueError):
        connector.user_lookup(user_id="U1", email="x@x")


def test_slack_call_surface_raises_for_ok_false() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": False, "error": "channel_not_found"}))
    with pytest.raises(SlackApiError) as exc:
        connector.channel_history(channel="C404")
    assert "channel_not_found" in str(exc.value)


def test_post_message_validates_and_serializes_body() -> None:
    connector, transport = _connector()
    with pytest.raises(ValueError):
        connector.post_message(channel="")
    with pytest.raises(ValueError):
        connector.post_message(channel="C1")

    transport.enqueue(json_response({"ok": True, "ts": "1.0"}))
    connector.post_message(channel="C1", text="hi", thread_ts="parent-1")
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url.endswith("/chat.postMessage")
    assert request.json_body == {"channel": "C1", "text": "hi", "thread_ts": "parent-1"}


def test_search_and_history_validate_inputs() -> None:
    connector, transport = _connector()
    with pytest.raises(ValueError):
        connector.search_messages("")
    with pytest.raises(ValueError):
        connector.channel_history("")
    transport.enqueue(json_response({"ok": True, "messages": {"matches": []}}))
    connector.search_messages("needle")
    assert transport.requests[0].params["query"] == "needle"
    assert transport.requests[0].params["count"] == 20


def test_list_channels_includes_optional_cursor() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "channels": []}))
    transport.enqueue(json_response({"ok": True, "channels": []}))
    connector.list_channels()
    connector.list_channels(cursor="next")
    assert "cursor" not in transport.requests[0].params
    assert transport.requests[1].params["cursor"] == "next"


def test_slack_search_files_and_user_endpoints() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "files": {"matches": []}}))
    transport.enqueue(json_response({"ok": True, "members": []}))
    transport.enqueue(json_response({"ok": True, "profile": {}}))
    transport.enqueue(json_response({"ok": True, "profile": {}}))
    transport.enqueue(json_response({"ok": True, "presence": "active"}))
    connector.search_files("needle")
    connector.list_users(cursor="abc")
    connector.get_user_profile(user_id="U1")
    connector.set_user_status("OOO", ":palm_tree:", status_expiration=1234567890)
    connector.get_user_presence(user_id="U1")
    assert transport.requests[0].url.endswith("/search.files")
    assert transport.requests[1].params["cursor"] == "abc"
    assert transport.requests[2].params == {"user": "U1", "include_labels": "false"}
    assert transport.requests[3].json_body["profile"]["status_text"] == "OOO"
    assert transport.requests[4].params == {"user": "U1"}
    with pytest.raises(ValueError):
        connector.search_files("")
    with pytest.raises(ValueError):
        connector.get_user_profile("")
    with pytest.raises(ValueError):
        connector.get_user_presence("")


def test_slack_channel_meta_and_membership() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "channel": {}}))
    transport.enqueue(json_response({"ok": True, "members": []}))
    transport.enqueue(json_response({"ok": True, "messages": []}))
    connector.channel_info("C1", include_locale=True, include_num_members=True)
    connector.channel_members("C1", cursor="next")
    connector.thread_replies("C1", "1.0", cursor="next2")
    assert transport.requests[0].params["include_locale"] == "true"
    assert transport.requests[1].params["cursor"] == "next"
    assert transport.requests[2].params["ts"] == "1.0"
    with pytest.raises(ValueError):
        connector.channel_info("")
    with pytest.raises(ValueError):
        connector.channel_members("")
    with pytest.raises(ValueError):
        connector.thread_replies("", "1.0")
    with pytest.raises(ValueError):
        connector.thread_replies("C1", "")


def test_slack_channel_lifecycle() -> None:
    connector, transport = _connector()
    for _ in range(11):
        transport.enqueue(json_response({"ok": True}))
    connector.create_channel("project")
    connector.rename_channel("C1", "renamed")
    connector.set_channel_topic("C1", "topic")
    connector.set_channel_purpose("C1", "purpose")
    connector.join_channel("C1")
    connector.leave_channel("C1")
    connector.invite_to_channel("C1", users=["U1", "U2"])
    connector.kick_from_channel("C1", "U1")
    connector.archive_channel("C1")
    connector.unarchive_channel("C1")
    connector.open_im(["U1", "U2"])
    assert transport.requests[0].json_body == {"name": "project", "is_private": False}
    assert transport.requests[1].json_body == {"channel": "C1", "name": "renamed"}
    assert transport.requests[6].json_body["users"] == "U1,U2"
    assert transport.requests[10].url.endswith("/conversations.open")
    with pytest.raises(ValueError):
        connector.create_channel("")
    with pytest.raises(ValueError):
        connector.rename_channel("C", "")
    with pytest.raises(ValueError):
        connector.invite_to_channel("C1", users=[])


def test_slack_message_mutations() -> None:
    connector, transport = _connector()
    for _ in range(7):
        transport.enqueue(json_response({"ok": True}))
    connector.post_ephemeral("C1", "U1", text="hi")
    connector.update_message("C1", "1.0", text="new")
    connector.delete_message("C1", "1.0")
    connector.schedule_message("C1", post_at=1700000000, text="later")
    connector.get_permalink("C1", "1.0")
    connector.add_reaction("C1", "1.0", "thumbsup")
    connector.remove_reaction("C1", "1.0", "thumbsup")
    assert transport.requests[0].url.endswith("/chat.postEphemeral")
    assert transport.requests[1].url.endswith("/chat.update")
    assert transport.requests[2].url.endswith("/chat.delete")
    assert transport.requests[3].json_body["post_at"] == 1700000000
    assert transport.requests[4].params == {"channel": "C1", "message_ts": "1.0"}
    with pytest.raises(ValueError):
        connector.post_ephemeral("", "U", text="x")
    with pytest.raises(ValueError):
        connector.update_message("C", "")
    with pytest.raises(ValueError):
        connector.update_message("C", "1")
    with pytest.raises(ValueError):
        connector.delete_message("", "1")
    with pytest.raises(ValueError):
        connector.schedule_message("", post_at=1, text="x")
    with pytest.raises(ValueError):
        connector.schedule_message("C", post_at=0, text="x")
    with pytest.raises(ValueError):
        connector.add_reaction("", "1", "thumbsup")


def test_slack_pins_and_files_and_misc() -> None:
    connector, transport = _connector()
    for _ in range(9):
        transport.enqueue(json_response({"ok": True}))
    connector.pin_message("C1", "1.0")
    connector.unpin_message("C1", "1.0")
    connector.list_pins("C1")
    connector.list_files(channel="C1", count=50)
    connector.file_info("F1")
    connector.delete_file("F1")
    connector.add_reminder("write report", "in 1 hour", user="U1")
    connector.list_reminders()
    connector.delete_reminder("Rm1")
    assert transport.requests[0].url.endswith("/pins.add")
    assert transport.requests[2].params == {"channel": "C1"}
    assert transport.requests[3].params["count"] == 50
    assert transport.requests[6].json_body["text"] == "write report"
    assert transport.requests[8].json_body == {"reminder": "Rm1"}
    with pytest.raises(ValueError):
        connector.pin_message("", "1")
    with pytest.raises(ValueError):
        connector.list_pins("")
    with pytest.raises(ValueError):
        connector.file_info("")
    with pytest.raises(ValueError):
        connector.delete_file("")
    with pytest.raises(ValueError):
        connector.add_reminder("", "")
    with pytest.raises(ValueError):
        connector.delete_reminder("")


def test_slack_emoji_and_team_info() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "emoji": {}}))
    transport.enqueue(json_response({"ok": True, "team": {}}))
    connector.emoji_list()
    connector.team_info()
    assert transport.requests[0].url.endswith("/emoji.list")
    assert transport.requests[1].url.endswith("/team.info")


# MARK: - Agent-ready: Slack summaries / tolerant inputs


def test_slack_list_channels_summaries_hide_ids_by_default() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "channels": [
                    {
                        "id": "C111111111",
                        "name": "general",
                        "is_private": False,
                        "is_member": True,
                        "topic": {"value": "Company-wide"},
                        "num_members": 42,
                    },
                    {
                        "id": "C222222222",
                        "name": "random",
                        "is_private": False,
                        "is_member": False,
                        "topic": {"value": "Watercooler"},
                        "num_members": 21,
                    },
                ],
                "response_metadata": {"next_cursor": "cur-next"},
            }
        )
    )
    result = connector.list_channels()
    assert result["channels"][0]["channel_ref"] == "channel_1"
    assert result["channels"][0]["name"] == "general"
    assert result["channels"][0]["topic"] == "Company-wide"
    assert "channel_id" not in result["channels"][0]
    assert result["channels"][1]["channel_ref"] == "channel_2"
    assert result["next_cursor"] == "cur-next"


def test_slack_list_channels_can_include_ids() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "channels": [{"id": "C123", "name": "general"}],
                "response_metadata": {"next_cursor": ""},
            }
        )
    )
    result = connector.list_channels(include_ids=True)
    assert result["channels"][0]["channel_id"] == "C123"


def test_slack_list_channels_raw_mode_passthrough() -> None:
    connector, transport = _connector()
    raw_payload = {
        "ok": True,
        "channels": [{"id": "C123", "name": "general", "is_archived": False}],
        "response_metadata": {"next_cursor": ""},
    }
    transport.enqueue(json_response(raw_payload))
    result = connector.list_channels(include_metadata=False)
    assert result == raw_payload


def test_slack_channel_history_summaries_hide_ids_and_support_dict_channel() -> None:
    connector, transport = _connector()
    # list_channels populates the channel name -> id cache
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "channels": [{"id": "C999999999", "name": "ops"}],
                "response_metadata": {"next_cursor": ""},
            }
        )
    )
    connector.list_channels()

    transport.enqueue(
        json_response(
            {
                "ok": True,
                "messages": [
                    {
                        "user": "U1",
                        "text": "rollout looks good",
                        "ts": "1700000000.000200",
                        "thread_ts": None,
                        "reply_count": 0,
                    }
                ],
                "has_more": False,
                "response_metadata": {"next_cursor": ""},
            }
        )
    )
    # Call by friendly channel name -- should resolve to the cached id
    result = connector.channel_history("ops")
    assert transport.requests[1].params["channel"] == "C999999999"
    assert result["messages"][0]["message_ref"] == "message_1"
    assert result["messages"][0]["text"] == "rollout looks good"
    assert result["messages"][0]["ts"] == "1700000000.000200"
    assert "channel_id" not in result["messages"][0]


def test_slack_channel_history_accepts_channel_summary_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True, "messages": []}))
    connector.channel_history({"channel_id": "C0000000099"})
    assert transport.requests[0].params["channel"] == "C0000000099"


def test_slack_search_messages_summaries_hide_ids() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "messages": {
                    "matches": [
                        {
                            "username": "alice",
                            "text": "ship the migration",
                            "ts": "1700000000.000200",
                            "permalink": "https://x.slack.com/p1",
                            "user": "U1",
                            "channel": {"id": "C1", "name": "ops"},
                        }
                    ],
                    "total": 1,
                    "pagination": {"page_count": 1},
                },
            }
        )
    )
    result = connector.search_messages("rollout")
    msg = result["messages"][0]
    assert msg["message_ref"] == "message_1"
    assert msg["username"] == "alice"
    assert msg["channel_name"] == "ops"
    assert msg["permalink"] == "https://x.slack.com/p1"
    assert "user_id" not in msg
    assert "channel_id" not in msg


def test_slack_search_messages_can_return_ids() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "messages": {
                    "matches": [
                        {
                            "username": "alice",
                            "text": "x",
                            "ts": "1.0",
                            "user": "U42",
                            "channel": {"id": "C7", "name": "ops"},
                        }
                    ],
                    "total": 1,
                },
            }
        )
    )
    result = connector.search_messages("anything", include_ids=True)
    msg = result["messages"][0]
    assert msg["user_id"] == "U42"
    assert msg["channel_id"] == "C7"


def test_slack_post_message_accepts_friendly_name_and_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "channels": [{"id": "C111111111", "name": "alerts"}],
                "response_metadata": {"next_cursor": ""},
            }
        )
    )
    connector.list_channels()

    # Friendly name path
    transport.enqueue(json_response({"ok": True, "ts": "1.0"}))
    connector.post_message("alerts", text="hello world")
    assert transport.requests[1].json_body["channel"] == "C111111111"

    # Dict path
    transport.enqueue(json_response({"ok": True, "ts": "2.0"}))
    connector.post_message({"channel_id": "C222222222"}, text="hi")
    assert transport.requests[2].json_body["channel"] == "C222222222"


def test_slack_update_and_delete_message_tolerate_message_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"ok": True}))
    message = {"ts": "1700000000.000200"}
    connector.update_message("C1234567890", message, text="edited")
    assert transport.requests[0].json_body["ts"] == "1700000000.000200"

    transport.enqueue(json_response({"ok": True}))
    connector.delete_message("C1234567890", message)
    assert transport.requests[1].url.endswith("/chat.delete")
    assert transport.requests[1].json_body["ts"] == "1700000000.000200"


def test_slack_destructive_tools_tagged() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _connector()
    for method in (
        connector.delete_message,
        connector.delete_file,
        connector.delete_reminder,
    ):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


def test_slack_permissions_and_destructive_are_wired() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    from maivn_tools.core.permissions import PermissionFlag, PermissionSet

    connector, _ = _connector()
    # list_channels is READ; create_channel is WRITE; delete_message is
    # DELETE+destructive. Tags ("read"/"write"/"destructive") are
    # auto-derived from these markers at Agent registration time.
    list_opts = get_toolify_options(connector.list_channels)
    write_opts = get_toolify_options(connector.create_channel)
    del_opts = get_toolify_options(connector.delete_message)
    assert list_opts is not None
    assert write_opts is not None
    assert del_opts is not None
    assert cast(PermissionSet, list_opts.permissions).includes(PermissionFlag.READ)
    assert cast(PermissionSet, write_opts.permissions).includes(PermissionFlag.WRITE)
    assert cast(PermissionSet, del_opts.permissions).includes(PermissionFlag.DELETE)
    assert del_opts.destructive is True
