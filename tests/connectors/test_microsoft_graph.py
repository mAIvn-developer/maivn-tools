# pyright: strict
from __future__ import annotations

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.microsoft_graph import (
    MicrosoftFilesToolSet,
    OutlookCalendarToolSet,
    OutlookMailToolSet,
)
from maivn_tools.testing import MockTransport, json_response

# MARK: - Outlook Mail


def _mail() -> tuple[OutlookMailToolSet, MockTransport]:
    transport = MockTransport()
    return OutlookMailToolSet(token="at-graph", transport=transport), transport


def test_outlook_mail_validates_user() -> None:
    with pytest.raises(ValueError):
        OutlookMailToolSet(token="x", user="")


def test_outlook_mail_list_folders_uses_me_path() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"value": []}))
    connector.list_folders()
    assert transport.requests[0].url.endswith("/me/mailFolders")
    assert transport.requests[0].headers["Authorization"] == "Bearer at-graph"


def test_outlook_mail_search_quotes_unquoted_search_string() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"value": []}))
    connector.search_messages(search="needle", top=10)
    request = transport.requests[0]
    assert request.params["$search"] == '"needle"'
    # $orderby is omitted because $search is set.
    assert "$orderby" not in request.params


def test_outlook_mail_search_returns_summaries_without_ids() -> None:
    connector, transport = _mail()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "graph-msg-1",
                        "subject": "Launch review",
                        "from": {
                            "emailAddress": {
                                "name": "Alice",
                                "address": "alice@example.test",
                            }
                        },
                        "toRecipients": [{"emailAddress": {"address": "me@example.test"}}],
                        "receivedDateTime": "2026-05-14T15:00:00Z",
                        "bodyPreview": "Heads up...",
                        "isRead": False,
                    }
                ]
            }
        )
    )
    result = connector.search_messages(top=5)
    assert result["messages"] == [
        {
            "message_ref": "message_1",
            "sender": "Alice <alice@example.test>",
            "to": ["me@example.test"],
            "subject": "Launch review",
            "received_at": "2026-05-14T15:00:00Z",
            "preview": "Heads up...",
            "is_read": False,
        }
    ]
    assert "message_id" not in result["messages"][0]


def test_outlook_mail_search_can_return_ids_for_follow_up_tools() -> None:
    connector, transport = _mail()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "graph-msg-1",
                        "subject": "x",
                        "from": {"emailAddress": {"address": "a@b"}},
                        "conversationId": "conv-1",
                    }
                ]
            }
        )
    )
    result = connector.search_messages(top=5, include_ids=True)
    assert result["messages"][0]["message_id"] == "graph-msg-1"
    assert result["messages"][0]["conversation_id"] == "conv-1"


def test_outlook_mail_search_raw_mode_returns_provider_response() -> None:
    connector, transport = _mail()
    raw = {"value": [{"id": "x", "subject": "raw"}], "@odata.nextLink": "next"}
    transport.enqueue(json_response(raw))
    result = connector.search_messages(top=5, include_metadata=False)
    assert result == raw


def test_outlook_mail_list_folders_returns_summaries() -> None:
    connector, transport = _mail()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "AAMk",
                        "displayName": "Inbox",
                        "totalItemCount": 42,
                        "unreadItemCount": 5,
                    },
                    {
                        "id": "AAMk2",
                        "displayName": "Sent Items",
                        "totalItemCount": 17,
                        "unreadItemCount": 0,
                    },
                ]
            }
        )
    )
    result = connector.list_folders()
    assert result["folders"][0]["folder_ref"] == "folder_1"
    assert result["folders"][0]["display_name"] == "Inbox"
    assert result["folders"][0]["unread_item_count"] == 5
    assert "folder_id" not in result["folders"][0]


def test_outlook_mail_list_folders_include_ids() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"value": [{"id": "AAMk", "displayName": "Inbox"}]}))
    result = connector.list_folders(include_ids=True)
    assert result["folders"][0]["folder_id"] == "AAMk"


def test_outlook_mail_tolerant_inputs_accept_summaries() -> None:
    connector, transport = _mail()
    # delete_message accepts a dict from search_messages output
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"id": "m2"}))
    transport.enqueue(json_response({"id": "m1"}))
    transport.enqueue(json_response({}))
    connector.delete_message(message_id={"message_ref": "message_1", "message_id": "m1"})
    connector.move_message(
        message_id={"id": "m1"},
        destination_folder_id={"folder_id": "folder-x"},
    )
    connector.mark_read({"id": "m1"})
    connector.reply_to_message({"id": "m1"}, "thanks")
    assert transport.requests[0].url.endswith("/me/messages/m1")
    assert transport.requests[1].url.endswith("/me/messages/m1/move")
    assert transport.requests[1].json_body == {"destinationId": "folder-x"}
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[2].url.endswith("/me/messages/m1")
    assert transport.requests[3].url.endswith("/me/messages/m1/reply")


def test_outlook_mail_extractor_rejects_empty_dict() -> None:
    connector, _ = _mail()
    with pytest.raises(ValueError):
        connector.delete_message(message_id={})
    with pytest.raises(ValueError):
        connector.move_message(
            message_id={"id": "m1"},
            destination_folder_id={"no_id": "x"},
        )


def test_outlook_mail_send_email_serializes_recipients_and_html_body() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({}))
    connector.send_email(
        to=["bob@example.test"],
        subject="Hi",
        body_html="<p>Hello</p>",
        cc=["cc@example.test"],
        bcc=["bcc@example.test"],
        save_to_sent=False,
    )
    payload = transport.requests[0].json_body
    assert payload["saveToSentItems"] is False
    assert payload["message"]["body"] == {"contentType": "HTML", "content": "<p>Hello</p>"}
    assert payload["message"]["toRecipients"] == [{"emailAddress": {"address": "bob@example.test"}}]
    assert payload["message"]["ccRecipients"][0]["emailAddress"]["address"] == "cc@example.test"


def test_outlook_mail_move_message_requires_destination() -> None:
    connector, _ = _mail()
    with pytest.raises(ValueError):
        connector.move_message(message_id="m", destination_folder_id="")


def test_outlook_mail_delete_is_destructive() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_message)
    assert opts is not None and opts.destructive is True
    connector.delete_message(message_id="m1")


def test_outlook_mail_other_user_path() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"value": []}))
    connector = OutlookMailToolSet(token="t", user="ops@example.test", transport=transport)
    connector.list_folders()
    assert "/users/ops@example.test/mailFolders" in transport.requests[0].url


def test_outlook_mail_copy_message_validates_and_calls() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "m2"}))
    connector.copy_message(message_id="m1", destination_folder_id="archive")
    assert transport.requests[0].url.endswith("/me/messages/m1/copy")
    with pytest.raises(ValueError):
        connector.copy_message(message_id="", destination_folder_id="x")
    with pytest.raises(ValueError):
        connector.copy_message(message_id="m", destination_folder_id="")


def test_outlook_mail_update_message_patches() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "m1"}))
    connector.update_message("m1", {"isRead": True})
    assert transport.requests[0].method == "PATCH"
    with pytest.raises(ValueError):
        connector.update_message("", {"isRead": True})
    with pytest.raises(ValueError):
        connector.update_message("m", {})


def test_outlook_mail_mark_read_delegates() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "m1"}))
    transport.enqueue(json_response({"id": "m1"}))
    connector.mark_read("m1")
    connector.mark_read("m1", is_read=False)
    assert transport.requests[0].json_body == {"isRead": True}
    assert transport.requests[1].json_body == {"isRead": False}


def test_outlook_mail_flag_message_validates() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "m1"}))
    connector.flag_message("m1", "complete")
    assert transport.requests[0].json_body == {"flag": {"flagStatus": "complete"}}
    with pytest.raises(ValueError):
        connector.flag_message("m1", "BAD")


def test_outlook_mail_reply_and_reply_all() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.reply_to_message("m1", "thanks")
    connector.reply_to_message("m1", "thanks all", reply_all=True)
    assert transport.requests[0].url.endswith("/messages/m1/reply")
    assert transport.requests[1].url.endswith("/messages/m1/replyAll")
    with pytest.raises(ValueError):
        connector.reply_to_message("", "x")


def test_outlook_mail_forward_message_validates() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({}))
    connector.forward_message("m1", ["bob@example.test"], "FYI")
    payload = transport.requests[0].json_body
    assert payload["comment"] == "FYI"
    assert payload["toRecipients"][0]["emailAddress"]["address"] == "bob@example.test"
    with pytest.raises(ValueError):
        connector.forward_message("", ["a@b.c"])
    with pytest.raises(ValueError):
        connector.forward_message("m", [])


def test_outlook_mail_attachments_list_and_get() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"name": "a.pdf"}))
    connector.list_attachments("m1")
    connector.get_attachment("m1", "a1")
    assert transport.requests[0].url.endswith("/messages/m1/attachments")
    assert transport.requests[1].url.endswith("/messages/m1/attachments/a1")
    with pytest.raises(ValueError):
        connector.list_attachments("")


def test_outlook_mail_add_attachment_posts_file_attachment() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "a1"}))
    connector.add_attachment(
        message_id="m1",
        name="hello.txt",
        content_base64="aGVsbG8=",
        content_type="text/plain",
    )
    payload = transport.requests[0].json_body
    assert payload["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert payload["contentBytes"] == "aGVsbG8="
    with pytest.raises(ValueError):
        connector.add_attachment(message_id="", name="x", content_base64="y")


def test_outlook_mail_create_and_send_draft() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "d1"}))
    transport.enqueue(json_response({}))
    connector.create_draft(to=["a@b.c"], subject="hi", body_text="hello")
    result = connector.send_draft("d1")
    payload = transport.requests[0].json_body
    assert payload["subject"] == "hi"
    assert transport.requests[1].url.endswith("/me/messages/d1/send")
    assert result["sent"] is True
    with pytest.raises(ValueError):
        connector.create_draft(to=[], subject="x", body_text="y")
    with pytest.raises(ValueError):
        connector.create_draft(to=["a@b"], subject="x")
    with pytest.raises(ValueError):
        connector.send_draft("")


def test_outlook_mail_folder_crud() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "f1", "displayName": "Project"}))
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"id": "child"}))
    transport.enqueue(json_response({"id": "f1", "displayName": "Renamed"}))
    transport.enqueue(json_response({}))
    connector.get_folder("f1")
    connector.list_messages_in_folder("f1", top=10)
    connector.create_folder(display_name="Project")
    connector.update_folder("f1", {"displayName": "Renamed"})
    result = connector.delete_folder("f1")
    assert transport.requests[1].url.endswith("/me/mailFolders/f1/messages")
    assert transport.requests[1].params["$top"] == 10
    assert transport.requests[2].url.endswith("/me/mailFolders")
    assert transport.requests[4].method == "DELETE"
    assert result["deleted"] is True


def test_outlook_mail_folder_validates() -> None:
    connector, _ = _mail()
    with pytest.raises(ValueError):
        connector.get_folder("")
    with pytest.raises(ValueError):
        connector.list_messages_in_folder("")
    with pytest.raises(ValueError):
        connector.create_folder("")
    with pytest.raises(ValueError):
        connector.update_folder("", {"displayName": "x"})
    with pytest.raises(ValueError):
        connector.update_folder("f", {})
    with pytest.raises(ValueError):
        connector.delete_folder("")


def test_outlook_mail_create_folder_nested_uses_child_path() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"id": "f2"}))
    connector.create_folder(display_name="Child", parent_folder_id="parent")
    assert transport.requests[0].url.endswith("/me/mailFolders/parent/childFolders")


def test_outlook_mail_rules_crud_and_categories() -> None:
    connector, transport = _mail()
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"id": "r1"}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"value": []}))
    connector.list_mail_rules()
    connector.create_mail_rule(rule={"displayName": "r", "conditions": {}, "actions": {}})
    result = connector.delete_mail_rule("r1")
    connector.list_categories()
    assert transport.requests[0].url.endswith("/me/mailFolders/inbox/messageRules")
    assert transport.requests[1].method == "POST"
    assert result["deleted"] is True
    assert transport.requests[3].url.endswith("/me/outlook/masterCategories")


def test_outlook_mail_rule_validates() -> None:
    connector, _ = _mail()
    with pytest.raises(ValueError):
        connector.create_mail_rule(rule={})
    with pytest.raises(ValueError):
        connector.delete_mail_rule("")


# MARK: - Outlook Calendar


def _cal() -> tuple[OutlookCalendarToolSet, MockTransport]:
    transport = MockTransport()
    return OutlookCalendarToolSet(token="at-cal", transport=transport), transport


def test_outlook_calendar_uses_calendar_view_when_window_supplied() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"value": []}))
    connector.list_events(start="2026-05-14T00:00:00Z", end="2026-05-15T00:00:00Z")
    assert transport.requests[0].url.endswith("/me/calendarView")
    params = transport.requests[0].params
    assert params["startDateTime"] == "2026-05-14T00:00:00Z"


def test_outlook_calendar_list_calendars_returns_summaries() -> None:
    connector, transport = _cal()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "cal-1",
                        "name": "Team",
                        "color": "auto",
                        "isDefaultCalendar": True,
                        "canEdit": True,
                    }
                ]
            }
        )
    )
    result = connector.list_calendars()
    assert result["calendars"][0]["calendar_ref"] == "calendar_1"
    assert result["calendars"][0]["name"] == "Team"
    assert result["calendars"][0]["is_default"] is True
    assert "calendar_id" not in result["calendars"][0]


def test_outlook_calendar_list_calendars_include_ids() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"value": [{"id": "cal-1", "name": "Team"}]}))
    result = connector.list_calendars(include_ids=True)
    assert result["calendars"][0]["calendar_id"] == "cal-1"


def test_outlook_calendar_list_events_returns_summaries() -> None:
    connector, transport = _cal()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "evt-1",
                        "subject": "Standup",
                        "start": {"dateTime": "2026-05-14T15:00:00", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-05-14T15:30:00", "timeZone": "UTC"},
                        "location": {"displayName": "Zoom"},
                        "organizer": {
                            "emailAddress": {"name": "Alice", "address": "alice@example.test"}
                        },
                        "attendees": [{"emailAddress": {"address": "bob@example.test"}}],
                        "isOnlineMeeting": True,
                        "isAllDay": False,
                    }
                ]
            }
        )
    )
    result = connector.list_events()
    event = result["events"][0]
    assert event["event_ref"] == "event_1"
    assert event["subject"] == "Standup"
    assert event["start_time"] == "2026-05-14T15:00:00"
    assert event["location"] == "Zoom"
    assert event["organizer"] == "Alice <alice@example.test>"
    assert event["attendees"] == ["bob@example.test"]
    assert event["is_online_meeting"] is True
    assert "event_id" not in event


def test_outlook_calendar_list_events_include_ids() -> None:
    connector, transport = _cal()
    transport.enqueue(
        json_response({"value": [{"id": "evt-1", "subject": "x", "iCalUId": "uid-1"}]})
    )
    result = connector.list_events(include_ids=True)
    assert result["events"][0]["event_id"] == "evt-1"
    assert result["events"][0]["i_cal_uid"] == "uid-1"


def test_outlook_calendar_list_events_raw_mode_returns_provider_response() -> None:
    connector, transport = _cal()
    raw = {"value": [{"id": "evt-1", "subject": "x"}], "@odata.nextLink": "next"}
    transport.enqueue(json_response(raw))
    result = connector.list_events(include_metadata=False)
    assert result == raw


def test_outlook_calendar_tolerant_inputs_accept_summaries() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"id": "e1"}))
    transport.enqueue(json_response({}))
    connector.delete_event(event_id={"event_ref": "event_1", "event_id": "e1"})
    connector.update_event(event_id={"id": "e1"}, patch={"subject": "x"})
    connector.respond_to_event(event_id={"id": "e1"}, response="accept")
    assert transport.requests[0].url.endswith("/me/events/e1")
    assert transport.requests[1].method == "PATCH"
    assert transport.requests[2].url.endswith("/me/events/e1/accept")


def test_outlook_calendar_create_event_serializes_attendees() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"id": "e1"}))
    connector.create_event(
        subject="Sync",
        start={"dateTime": "2026-05-14T15:00:00Z", "timeZone": "UTC"},
        end={"dateTime": "2026-05-14T15:30:00Z", "timeZone": "UTC"},
        attendees=[{"emailAddress": {"address": "bob@example.test"}}],
    )
    payload = transport.requests[0].json_body
    assert payload["subject"] == "Sync"
    assert payload["attendees"][0]["emailAddress"]["address"] == "bob@example.test"


def test_outlook_calendar_delete_is_destructive() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_event)
    assert opts is not None and opts.destructive is True
    connector.delete_event(event_id="e1")


def test_outlook_calendar_free_busy_validates_inputs() -> None:
    connector, _ = _cal()
    with pytest.raises(ValueError):
        connector.free_busy(start="x", end="y", schedules=[])
    with pytest.raises(ValueError):
        connector.free_busy(start="x", end="y", schedules=["a"], interval=1)


def test_outlook_calendar_get_calendar_paths() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"id": "default"}))
    transport.enqueue(json_response({"id": "cal-1"}))
    connector.get_calendar()
    connector.get_calendar(calendar_id="cal-1")
    assert transport.requests[0].url.endswith("/me/calendar")
    assert transport.requests[1].url.endswith("/me/calendars/cal-1")
    with pytest.raises(ValueError):
        connector.get_calendar(calendar_id="")


def test_outlook_calendar_list_event_instances() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"value": []}))
    connector.list_event_instances(
        event_id="e1",
        start="2026-01-01T00:00:00Z",
        end="2026-01-02T00:00:00Z",
    )
    assert transport.requests[0].url.endswith("/me/events/e1/instances")
    with pytest.raises(ValueError):
        connector.list_event_instances(event_id="", start="x", end="y")
    with pytest.raises(ValueError):
        connector.list_event_instances(event_id="e", start="x", end="y", top=0)


def test_outlook_calendar_respond_to_event() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({}))
    connector.respond_to_event(event_id="e1", response="accept", comment="Thanks")
    assert transport.requests[0].url.endswith("/me/events/e1/accept")
    assert transport.requests[0].json_body["sendResponse"] is True
    with pytest.raises(ValueError):
        connector.respond_to_event(event_id="e", response="maybe")
    with pytest.raises(ValueError):
        connector.respond_to_event(event_id="", response="accept")


def test_outlook_calendar_cancel_and_forward_event() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.cancel_event("e1", comment="bye")
    connector.forward_event("e1", to_recipients=["bob@example.test"], comment="fyi")
    assert transport.requests[0].url.endswith("/me/events/e1/cancel")
    assert transport.requests[1].url.endswith("/me/events/e1/forward")
    recipients = transport.requests[1].json_body["toRecipients"]
    assert recipients[0]["emailAddress"]["address"] == "bob@example.test"
    with pytest.raises(ValueError):
        connector.cancel_event("")
    with pytest.raises(ValueError):
        connector.forward_event(event_id="", to_recipients=["a@b.c"])
    with pytest.raises(ValueError):
        connector.forward_event(event_id="e", to_recipients=[])


def test_outlook_calendar_find_meeting_times() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"meetingTimeSuggestions": []}))
    connector.find_meeting_times(
        attendees=["bob@example.test"],
        meeting_duration_minutes=45,
    )
    payload = transport.requests[0].json_body
    assert payload["meetingDuration"] == "PT45M"
    assert payload["attendees"][0]["emailAddress"]["address"] == "bob@example.test"
    with pytest.raises(ValueError):
        connector.find_meeting_times(attendees=[])
    with pytest.raises(ValueError):
        connector.find_meeting_times(attendees=["a@b"], meeting_duration_minutes=0)


def test_outlook_calendar_create_update_delete_calendar() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"id": "cal-1"}))
    transport.enqueue(json_response({"id": "cal-1", "name": "Renamed"}))
    transport.enqueue(json_response({}))
    connector.create_calendar(name="Project")
    connector.update_calendar(calendar_id="cal-1", patch={"name": "Renamed"})
    result = connector.delete_calendar(calendar_id="cal-1")
    assert transport.requests[0].json_body["name"] == "Project"
    assert transport.requests[1].method == "PATCH"
    assert transport.requests[2].method == "DELETE"
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.create_calendar(name="")
    with pytest.raises(ValueError):
        connector.update_calendar(calendar_id="", patch={"name": "x"})
    with pytest.raises(ValueError):
        connector.update_calendar(calendar_id="c", patch={})
    with pytest.raises(ValueError):
        connector.delete_calendar(calendar_id="")


def test_outlook_calendar_list_calendar_groups() -> None:
    connector, transport = _cal()
    transport.enqueue(json_response({"value": []}))
    connector.list_calendar_groups()
    assert transport.requests[0].url.endswith("/me/calendarGroups")


def test_graph_files_list_children_validates() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"value": []}))
    connector.list_children(item_id="i1")
    assert transport.requests[0].url.endswith("/me/drive/items/i1/children")
    with pytest.raises(ValueError):
        connector.list_children(item_id="")
    with pytest.raises(ValueError):
        connector.list_children(item_id="i", top=0)


def test_graph_files_get_item_by_path() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"id": "i1"}))
    connector.get_item_by_path("/Documents/file.txt")
    assert "/me/drive/root:/Documents/file.txt" in transport.requests[0].url
    with pytest.raises(ValueError):
        connector.get_item_by_path("")


def test_graph_files_create_folder_validates_conflict_behavior() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"id": "i1"}))
    connector.create_folder(parent_id="p", name="New", conflict_behavior="replace")
    payload = transport.requests[0].json_body
    assert payload["folder"] == {}
    assert payload["@microsoft.graph.conflictBehavior"] == "replace"
    with pytest.raises(ValueError):
        connector.create_folder(parent_id="p", name="x", conflict_behavior="bogus")
    with pytest.raises(ValueError):
        connector.create_folder(parent_id="", name="x")


def test_graph_files_rename_and_metadata_patch() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"id": "i1", "name": "renamed.txt"}))
    transport.enqueue(json_response({"id": "i1"}))
    connector.rename_item("i1", "renamed.txt")
    connector.update_item_metadata("i1", {"description": "d"})
    assert transport.requests[0].json_body == {"name": "renamed.txt"}
    assert transport.requests[1].method == "PATCH"
    with pytest.raises(ValueError):
        connector.rename_item("", "x")
    with pytest.raises(ValueError):
        connector.update_item_metadata("", {"a": 1})
    with pytest.raises(ValueError):
        connector.update_item_metadata("i", {})


def test_graph_files_move_and_copy() -> None:
    from maivn_tools.runtime.http import HttpResponse

    connector, transport = _files()
    transport.enqueue(json_response({"id": "i1"}))
    transport.enqueue(
        HttpResponse(
            status=202,
            headers={"Location": "https://monitor.example.com/op1"},
            body=b"",
            url="https://graph.microsoft.com/x",
        )
    )
    connector.move_item("i1", "p2")
    result = connector.copy_item("i1", new_parent_id="p2", new_name="copy.txt")
    move_payload = transport.requests[0].json_body
    copy_payload = transport.requests[1].json_body
    assert move_payload["parentReference"] == {"id": "p2"}
    assert copy_payload["parentReference"] == {"id": "p2"}
    assert copy_payload["name"] == "copy.txt"
    assert result["monitor_url"] == "https://monitor.example.com/op1"


def test_graph_files_create_upload_session() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"uploadUrl": "https://up.example.com/x"}))
    connector.create_upload_session(parent_id="p", name="big.bin")
    assert "/createUploadSession" in transport.requests[0].url
    with pytest.raises(ValueError):
        connector.create_upload_session(parent_id="", name="x")
    with pytest.raises(ValueError):
        connector.create_upload_session(parent_id="p", name="x", conflict_behavior="bogus")


def test_graph_files_versions_list_and_restore() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({}))
    connector.list_versions("i1")
    result = connector.restore_version("i1", "v1")
    assert transport.requests[1].url.endswith("/me/drive/items/i1/versions/v1/restoreVersion")
    assert result["restored"] is True
    with pytest.raises(ValueError):
        connector.list_versions("")
    with pytest.raises(ValueError):
        connector.restore_version("", "v")


def test_graph_files_permissions_share_invite_revoke() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"link": {"webUrl": "https://share/x"}}))
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({}))
    connector.list_permissions("i1")
    connector.create_share_link(
        item_id="i1",
        link_type="view",
        scope="anonymous",
        password="secret",
    )
    connector.invite_to_item(item_id="i1", recipients=["bob@example.test"], roles=["write"])
    result = connector.revoke_permission(item_id="i1", permission_id="perm1")
    create_payload = transport.requests[1].json_body
    invite_payload = transport.requests[2].json_body
    assert create_payload["type"] == "view"
    assert create_payload["password"] == "secret"
    assert invite_payload["recipients"][0]["email"] == "bob@example.test"
    assert invite_payload["roles"] == ["write"]
    assert transport.requests[3].method == "DELETE"
    assert result["deleted"] is True


def test_graph_files_share_link_validates() -> None:
    connector, _ = _files()
    with pytest.raises(ValueError):
        connector.create_share_link(item_id="i", link_type="bad", scope="anonymous")
    with pytest.raises(ValueError):
        connector.create_share_link(item_id="i", link_type="view", scope="bad")
    with pytest.raises(ValueError):
        connector.invite_to_item(item_id="", recipients=["a@b.c"])
    with pytest.raises(ValueError):
        connector.invite_to_item(item_id="i", recipients=[])


def test_graph_files_drive_metadata() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"id": "drive", "driveType": "personal"}))
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"value": []}))
    connector.get_drive()
    connector.list_recent()
    connector.list_shared_with_me()
    assert transport.requests[0].url.endswith("/me/drive")
    assert transport.requests[1].url.endswith("/me/drive/recent")
    assert transport.requests[2].url.endswith("/me/drive/sharedWithMe")


# MARK: - Graph Files


def _files(drive_root: str = "me/drive") -> tuple[MicrosoftFilesToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MicrosoftFilesToolSet(token="at-files", drive_root=drive_root, transport=transport),
        transport,
    )


def test_graph_files_validates_drive_root() -> None:
    with pytest.raises(ValueError):
        MicrosoftFilesToolSet(token="t", drive_root="")


def test_graph_files_list_root_children_targets_drive_path() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"value": []}))
    connector.list_root_children()
    assert transport.requests[0].url.endswith("/me/drive/root/children")


def test_graph_files_search_files_validates_query_and_top() -> None:
    connector, _ = _files()
    with pytest.raises(ValueError):
        connector.search_files(query="")
    with pytest.raises(ValueError):
        connector.search_files(query="x", top=0)


def test_graph_files_search_uses_sharepoint_drive_root() -> None:
    connector, transport = _files(drive_root="sites/site-1/drive")
    transport.enqueue(json_response({"value": []}))
    connector.search_files(query="needle")
    assert "/sites/site-1/drive/root/search(q='needle')" in transport.requests[0].url


def test_graph_files_upload_small_file_enforces_size_limit() -> None:
    import base64

    connector, transport = _files()
    too_big = base64.b64encode(b"x" * (5 * 1024 * 1024)).decode("ascii")
    with pytest.raises(ValueError):
        connector.upload_small_file(parent_id="p", name="f", content_base64=too_big)
    transport.enqueue(json_response({"id": "i1"}))
    small = base64.b64encode(b"hello").decode("ascii")
    connector.upload_small_file(
        parent_id="p", name="hello.txt", content_base64=small, content_type="text/plain"
    )
    request = transport.requests[0]
    assert request.method == "PUT"
    assert request.headers["Content-Type"] == "text/plain"
    assert request.data == b"hello"


def test_graph_files_delete_is_destructive() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_item)
    assert opts is not None and opts.destructive is True
    connector.delete_item(item_id="x")


def test_graph_files_list_root_children_returns_summaries_without_ids() -> None:
    connector, transport = _files()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "raw-id-1",
                        "name": "report.docx",
                        "size": 4567,
                        "lastModifiedDateTime": "2026-05-16T09:00:00Z",
                        "file": {"mimeType": "application/vnd.openxmlformats-doc"},
                        "createdBy": {"user": {"displayName": "Alice"}},
                        "webUrl": "https://onedrive/x",
                    },
                    {
                        "id": "raw-id-2",
                        "name": "Reports",
                        "folder": {"childCount": 3},
                        "lastModifiedDateTime": "2026-05-15T09:00:00Z",
                        "createdBy": {"user": {"displayName": "Bob"}},
                        "webUrl": "https://onedrive/y",
                    },
                ]
            }
        )
    )
    result = connector.list_root_children()
    items = result["items"]
    assert items[0]["item_ref"] == "item_1"
    assert items[0]["name"] == "report.docx"
    assert items[0]["owner"] == "Alice"
    assert "item_id" not in items[0]
    assert items[1]["folder_ref"] == "folder_2"
    assert items[1]["kind"] == "folder"
    assert "item_id" not in items[1]


def test_graph_files_list_root_children_include_ids_exposes_raw_ids() -> None:
    connector, transport = _files()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "raw-id-1",
                        "name": "report.docx",
                        "lastModifiedDateTime": "2026-05-16T09:00:00Z",
                        "file": {"mimeType": "x"},
                    }
                ]
            }
        )
    )
    result = connector.list_root_children(include_ids=True)
    assert result["items"][0]["item_id"] == "raw-id-1"


def test_graph_files_list_root_children_raw_mode_returns_provider_payload() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"value": [{"id": "x", "name": "y"}]}))
    result = connector.list_root_children(include_metadata=False)
    assert "value" in result


def test_graph_files_search_files_returns_summaries() -> None:
    connector, transport = _files()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "id-1",
                        "name": "memo.docx",
                        "file": {"mimeType": "x"},
                        "lastModifiedDateTime": "2026-05-16T09:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.search_files(query="memo")
    assert result["items"][0]["item_ref"] == "item_1"
    assert "item_id" not in result["items"][0]


def test_graph_files_list_children_summary_mode_and_tolerant_input() -> None:
    connector, transport = _files()
    transport.enqueue(
        json_response(
            {
                "value": [
                    {
                        "id": "child-1",
                        "name": "memo.docx",
                        "file": {"mimeType": "x"},
                        "lastModifiedDateTime": "2026-05-16T09:00:00Z",
                    }
                ]
            }
        )
    )
    # Tolerant input: pass a folder dict instead of a raw id.
    result = connector.list_children({"item_id": "folder-1", "name": "Folder"})
    assert "/me/drive/items/folder-1/children" in transport.requests[0].url
    assert result["items"][0]["item_ref"] == "item_1"
    assert "item_id" not in result["items"][0]


def test_graph_files_delete_item_accepts_dict_input() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({}))
    connector.delete_item({"item_id": "del-1", "name": "doomed.txt"})
    assert transport.requests[0].method == "DELETE"
    assert "/me/drive/items/del-1" in transport.requests[0].url


def test_graph_files_download_file_accepts_dict_input() -> None:
    from maivn_tools.runtime.http import HttpResponse

    connector, transport = _files()
    transport.enqueue(
        HttpResponse(
            status=200,
            headers={"Content-Type": "text/plain"},
            body=b"hi",
            url="https://graph/x",
        )
    )
    result = connector.download_file({"item_id": "i-1"})
    assert result["item_id"] == "i-1"


def test_graph_files_move_item_accepts_dict_input() -> None:
    connector, transport = _files()
    transport.enqueue(json_response({"id": "i-1"}))
    connector.move_item({"item_id": "i-1", "name": "x"}, "parent-2")
    assert "/me/drive/items/i-1" in transport.requests[0].url
    assert transport.requests[0].json_body == {"parentReference": {"id": "parent-2"}}
