# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.google_workspace import (
    GmailToolSet,
    GoogleCalendarToolSet,
    GoogleDriveToolSet,
)
from maivn_tools.connectors.google_workspace._shared import normalize_token_provider
from maivn_tools.testing import MockTransport, json_response


def test_normalize_token_provider_accepts_string_token_object_and_callable() -> None:
    string_provider = normalize_token_provider("at-1")
    assert string_provider().access_token == "at-1"

    from maivn_tools import OAuth2Token

    token = OAuth2Token(access_token="at-2")
    obj_provider = normalize_token_provider(token)
    assert obj_provider().access_token == "at-2"

    callable_provider = normalize_token_provider(lambda: token)
    assert callable_provider().access_token == "at-2"

    with pytest.raises(TypeError):
        normalize_token_provider(123)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        normalize_token_provider("")


# MARK: - Gmail


def _gmail() -> tuple[GmailToolSet, MockTransport]:
    transport = MockTransport()
    return GmailToolSet(token="at-gmail", transport=transport), transport


def test_gmail_validates_user() -> None:
    with pytest.raises(ValueError):
        GmailToolSet(token="x", user="")


def test_gmail_is_a_toolset() -> None:
    from maivn._internal.utils.toolset import get_toolset_options

    opts = get_toolset_options(GmailToolSet)
    assert opts is not None
    assert opts.prefix == "gmail"


def test_gmail_validate_connection_uses_profile_endpoint() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"emailAddress": "a@example.test"}))
    profile = connector.validate_connection()
    assert profile["emailAddress"] == "a@example.test"
    assert transport.requests[0].url.endswith("/users/me/profile")
    assert transport.requests[0].headers["Authorization"] == "Bearer at-gmail"


def test_gmail_search_messages_validates_limits() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.search_messages(max_results=0)
    with pytest.raises(ValueError):
        connector.search_messages(max_results=10_000)


def test_gmail_search_messages_serializes_params() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"messages": []}))
    connector.search_messages(query="from:alice", label_ids=["INBOX"], max_results=5)
    request = transport.requests[0]
    assert request.params["maxResults"] == 5
    assert request.params["q"] == "from:alice"
    assert request.params["labelIds"] == ["INBOX"]


def test_gmail_search_messages_caps_summary_mode() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"messages": [], "resultSizeEstimate": 42}))

    result = connector.search_messages(max_results=50)

    assert transport.requests[0].params["maxResults"] == 10
    assert result["requestedMaxResults"] == 50
    assert result["summaryLimit"] == 10
    assert result["resultSizeEstimate"] == 42


def test_gmail_search_messages_does_not_cap_raw_mode() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"messages": []}))

    connector.search_messages(max_results=50, include_metadata=False)

    assert transport.requests[0].params["maxResults"] == 50


def test_gmail_search_messages_returns_human_summaries_without_ids() -> None:
    connector, transport = _gmail()
    transport.enqueue(
        json_response(
            {
                "messages": [{"id": "m1", "threadId": "t1"}],
                "resultSizeEstimate": 1,
            }
        )
    )
    transport.enqueue(
        json_response(
            {
                "id": "m1",
                "threadId": "t1",
                "labelIds": ["UNREAD", "INBOX"],
                "snippet": "Quick reminder about the launch review.",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Alice <alice@example.test>"},
                        {"name": "To", "value": "Me <me@example.test>"},
                        {"name": "Subject", "value": "Launch review"},
                        {"name": "Date", "value": "Sat, 16 May 2026 09:00:00 -0500"},
                    ]
                },
            }
        )
    )

    result = connector.search_messages(query="is:unread newer_than:1d", max_results=1)

    assert result["messages"] == [
        {
            "message_ref": "message_1",
            "sender": "Alice <alice@example.test>",
            "to": "Me <me@example.test>",
            "subject": "Launch review",
            "received_at": "Sat, 16 May 2026 09:00:00 -0500",
            "snippet": "Quick reminder about the launch review.",
            "label_ids": ["UNREAD", "INBOX"],
        }
    ]
    assert "message_id" not in result["messages"][0]
    assert transport.requests[1].url.endswith("/users/me/messages/m1")
    assert transport.requests[1].params["format"] == "metadata"


def test_gmail_search_messages_can_return_ids_for_follow_up_tools() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"messages": [{"id": "m1", "threadId": "t1"}]}))
    transport.enqueue(json_response({"id": "m1", "threadId": "t1", "payload": {"headers": []}}))

    result = connector.search_messages(max_results=1, include_ids=True)

    assert result["messages"][0]["message_id"] == "m1"
    assert result["messages"][0]["thread_id"] == "t1"


def test_gmail_get_message_validates_format() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.get_message(message_id="", format="full")
    with pytest.raises(ValueError):
        connector.get_message(message_id="m", format="bogus")


def test_gmail_send_email_builds_raw_payload() -> None:
    import base64

    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "mid"}))
    result = connector.send_email(
        to=["bob@example.test"],
        subject="Hi",
        body_text="Hello",
        body_html="<p>Hello</p>",
        thread_id="t1",
        sender="me@example.test",
    )
    assert result == {"id": "mid"}
    payload = transport.requests[0].json_body
    assert payload["threadId"] == "t1"
    raw = base64.urlsafe_b64decode(payload["raw"]).decode("utf-8", errors="replace")
    assert "Subject: Hi" in raw
    assert "Hello" in raw


def test_gmail_send_email_validates_inputs() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.send_email(to=[], subject="x")
    with pytest.raises(ValueError):
        connector.send_email(to=["b@x"], subject="x")


def test_gmail_modify_labels_requires_at_least_one_change() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.modify_labels(message_id="m")
    with pytest.raises(ValueError):
        connector.modify_labels(message_id="")


def test_gmail_trash_message_marks_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "m1"}))
    opts = get_toolify_options(connector.trash_message)
    assert opts is not None and opts.destructive is True
    connector.trash_message(message_id="m1")
    assert transport.requests[0].url.endswith("/users/me/messages/m1/trash")


def test_gmail_untrash_and_profile() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "m1"}))
    transport.enqueue(json_response({"emailAddress": "a@b.c", "messagesTotal": 1}))
    connector.untrash_message(message_id="m1")
    profile = connector.get_profile()
    assert transport.requests[0].url.endswith("/users/me/messages/m1/untrash")
    assert profile["emailAddress"] == "a@b.c"


def test_gmail_list_and_get_thread() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"threads": [{"id": "t1"}]}))
    transport.enqueue(json_response({"id": "t1", "messages": []}))
    connector.list_threads(query="from:alice", max_results=5)
    connector.get_thread("t1", format="full")
    assert transport.requests[0].params["q"] == "from:alice"
    assert transport.requests[1].url.endswith("/users/me/threads/t1")
    assert transport.requests[1].params["format"] == "full"


def test_gmail_get_thread_validates() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.get_thread("")
    with pytest.raises(ValueError):
        connector.get_thread("t", format="bogus")


def test_gmail_modify_thread_labels_requires_change() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.modify_thread_labels(thread_id="t1")


def test_gmail_modify_thread_labels_posts() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "t1"}))
    connector.modify_thread_labels(thread_id="t1", add_label_ids=["INBOX"])
    assert transport.requests[0].url.endswith("/users/me/threads/t1/modify")


def test_gmail_trash_untrash_thread() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "t1"}))
    transport.enqueue(json_response({"id": "t1"}))
    connector.trash_thread("t1")
    connector.untrash_thread("t1")
    assert transport.requests[0].url.endswith("/users/me/threads/t1/trash")
    assert transport.requests[1].url.endswith("/users/me/threads/t1/untrash")


def test_gmail_list_drafts_serializes_params() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"drafts": []}))
    connector.list_drafts(max_results=5, query="from:me", page_token="abc")
    request = transport.requests[0]
    assert request.params["maxResults"] == 5
    assert request.params["q"] == "from:me"
    assert request.params["pageToken"] == "abc"


def test_gmail_list_drafts_validates_max_results() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.list_drafts(max_results=0)


def test_gmail_get_draft_validates() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.get_draft("")
    with pytest.raises(ValueError):
        connector.get_draft("d", format="bogus")


def test_gmail_create_and_update_draft_builds_raw_payload() -> None:
    import base64

    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "d1"}))
    transport.enqueue(json_response({"id": "d1"}))
    connector.create_draft(
        to=["bob@example.test"],
        subject="Draft",
        body_text="hi",
        thread_id="t1",
    )
    connector.update_draft(
        draft_id="d1",
        to=["bob@example.test"],
        subject="Draft v2",
        body_text="hi again",
    )
    create_payload = transport.requests[0].json_body
    update_payload = transport.requests[1].json_body
    raw = base64.urlsafe_b64decode(create_payload["message"]["raw"]).decode()
    assert "Subject: Draft" in raw
    assert create_payload["message"]["threadId"] == "t1"
    assert transport.requests[1].method == "PUT"
    assert (
        "Subject: Draft v2" in base64.urlsafe_b64decode(update_payload["message"]["raw"]).decode()
    )


def test_gmail_create_draft_validates() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.create_draft(to=[], subject="x", body_text="hi")
    with pytest.raises(ValueError):
        connector.create_draft(to=["a@b.c"], subject="x")


def test_gmail_send_draft_and_delete_draft() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "m1"}))
    transport.enqueue(json_response({}))
    connector.send_draft("d1")
    result = connector.delete_draft("d1")
    assert transport.requests[0].url.endswith("/users/me/drafts/send")
    assert transport.requests[0].json_body == {"id": "d1"}
    assert transport.requests[1].method == "DELETE"
    assert result["deleted"] is True


def test_gmail_label_crud() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"id": "Label_1"}))
    transport.enqueue(json_response({"id": "Label_1", "name": "Project"}))
    transport.enqueue(json_response({"id": "Label_1", "name": "Project Renamed"}))
    transport.enqueue(json_response({}))
    connector.create_label(name="Project")
    connector.get_label("Label_1")
    connector.update_label("Label_1", {"name": "Project Renamed"})
    result = connector.delete_label("Label_1")
    assert transport.requests[0].json_body["name"] == "Project"
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[3].method == "DELETE"
    assert result["deleted"] is True


def test_gmail_label_validates() -> None:
    connector, _ = _gmail()
    with pytest.raises(ValueError):
        connector.create_label(name="")
    with pytest.raises(ValueError):
        connector.update_label("", {"name": "x"})
    with pytest.raises(ValueError):
        connector.update_label("x", {})
    with pytest.raises(ValueError):
        connector.delete_label("")
    with pytest.raises(ValueError):
        connector.get_label("")


def test_gmail_get_attachment_validates_and_calls() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"data": "ZGVhZGJlZWY="}))
    connector.get_attachment(message_id="m1", attachment_id="a1")
    assert transport.requests[0].url.endswith("/users/me/messages/m1/attachments/a1")
    with pytest.raises(ValueError):
        connector.get_attachment(message_id="", attachment_id="a")


def test_gmail_batch_modify_validates_and_calls() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({}))
    connector.batch_modify_messages(message_ids=["m1", "m2"], add_label_ids=["L1"])
    payload = transport.requests[0].json_body
    assert payload["ids"] == ["m1", "m2"]
    assert payload["addLabelIds"] == ["L1"]
    with pytest.raises(ValueError):
        connector.batch_modify_messages(message_ids=[], add_label_ids=["x"])
    with pytest.raises(ValueError):
        connector.batch_modify_messages(message_ids=["m1"])


def test_gmail_batch_delete_messages_validates() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({}))
    result = connector.batch_delete_messages(message_ids=["m1"])
    assert transport.requests[0].url.endswith("/users/me/messages/batchDelete")
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.batch_delete_messages(message_ids=[])


def test_gmail_list_history_validates_and_calls() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"history": []}))
    connector.list_history(start_history_id="123", history_types=["messageAdded"])
    request = transport.requests[0]
    assert request.params["startHistoryId"] == "123"
    assert request.params["historyTypes"] == ["messageAdded"]
    with pytest.raises(ValueError):
        connector.list_history(start_history_id="")
    with pytest.raises(ValueError):
        connector.list_history(start_history_id="1", max_results=0)


def test_gmail_filter_crud_and_send_as() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"filter": []}))
    transport.enqueue(json_response({"id": "f1"}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"sendAs": []}))
    connector.list_filters()
    connector.create_filter(criteria={"from": "a@b.c"}, action={"addLabelIds": ["L1"]})
    result = connector.delete_filter("f1")
    connector.list_send_as()
    assert transport.requests[0].url.endswith("/users/me/settings/filters")
    assert transport.requests[1].json_body["criteria"] == {"from": "a@b.c"}
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.create_filter(criteria={}, action={})
    with pytest.raises(ValueError):
        connector.delete_filter("")


def test_gmail_vacation_settings_crud() -> None:
    connector, transport = _gmail()
    transport.enqueue(json_response({"enableAutoReply": False}))
    transport.enqueue(json_response({"enableAutoReply": True}))
    connector.get_vacation_settings()
    connector.update_vacation_settings({"enableAutoReply": True, "responseSubject": "OOO"})
    assert transport.requests[1].method == "PUT"
    with pytest.raises(ValueError):
        connector.update_vacation_settings({})


# MARK: - Calendar


def _calendar() -> tuple[GoogleCalendarToolSet, MockTransport]:
    transport = MockTransport()
    return GoogleCalendarToolSet(token="at-cal", transport=transport), transport


def test_calendar_list_validates_max_results() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.list_calendars(max_results=0)


def test_calendar_list_events_serializes_filters() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"items": []}))
    connector.list_events(
        calendar_id="primary",
        time_min="2026-01-01T00:00:00Z",
        time_max="2026-02-01T00:00:00Z",
        q="standup",
        page_token="next",
    )
    request = transport.requests[0]
    assert request.url.endswith("/calendars/primary/events")
    assert request.params["timeMin"] == "2026-01-01T00:00:00Z"
    assert request.params["q"] == "standup"
    assert request.params["pageToken"] == "next"


def test_calendar_list_calendars_returns_summaries() -> None:
    connector, transport = _calendar()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "primary",
                        "summary": "me@example.test",
                        "description": "Main",
                        "timeZone": "America/Chicago",
                        "accessRole": "owner",
                        "primary": True,
                    }
                ]
            }
        )
    )
    result = connector.list_calendars()
    assert result["calendars"][0]["calendar_ref"] == "calendar_1"
    assert result["calendars"][0]["summary"] == "me@example.test"
    assert result["calendars"][0]["primary"] is True
    assert "calendar_id" not in result["calendars"][0]


def test_calendar_list_calendars_include_ids() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"items": [{"id": "primary", "summary": "me@example.test"}]}))
    result = connector.list_calendars(include_ids=True)
    assert result["calendars"][0]["calendar_id"] == "primary"


def test_calendar_list_events_returns_summaries() -> None:
    connector, transport = _calendar()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "evt-1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-05-14T15:00:00-05:00"},
                        "end": {"dateTime": "2026-05-14T15:30:00-05:00"},
                        "location": "Zoom",
                        "organizer": {
                            "email": "alice@example.test",
                            "displayName": "Alice",
                        },
                        "attendees": [{"email": "bob@example.test", "responseStatus": "accepted"}],
                        "status": "confirmed",
                        "htmlLink": "https://calendar/x",
                    }
                ]
            }
        )
    )
    result = connector.list_events()
    event = result["events"][0]
    assert event["event_ref"] == "event_1"
    assert event["summary"] == "Standup"
    assert event["start_time"] == "2026-05-14T15:00:00-05:00"
    assert event["organizer"] == "Alice <alice@example.test>"
    assert event["attendees"] == ["bob@example.test"]
    assert event["status"] == "confirmed"
    assert event["html_link"] == "https://calendar/x"
    assert "event_id" not in event


def test_calendar_list_events_include_ids() -> None:
    connector, transport = _calendar()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "evt-1",
                        "summary": "x",
                        "iCalUID": "uid-1",
                        "recurringEventId": "rec-1",
                    }
                ]
            }
        )
    )
    result = connector.list_events(include_ids=True)
    assert result["events"][0]["event_id"] == "evt-1"
    assert result["events"][0]["i_cal_uid"] == "uid-1"
    assert result["events"][0]["recurring_event_id"] == "rec-1"


def test_calendar_list_events_raw_mode_returns_provider_response() -> None:
    connector, transport = _calendar()
    raw = {"items": [{"id": "evt-1", "summary": "x"}], "nextPageToken": "next"}
    transport.enqueue(json_response(raw))
    result = connector.list_events(include_metadata=False)
    assert result == raw


def test_calendar_tolerant_inputs_accept_summaries() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"id": "evt-1"}))
    connector.delete_event(
        event_id={"event_ref": "event_1", "event_id": "evt-1"},
        calendar_id={"calendar_id": "primary"},
    )
    connector.update_event(
        event_id={"id": "evt-1"},
        patch={"summary": "x"},
        calendar_id={"id": "primary"},
    )
    assert transport.requests[0].url.endswith("/calendars/primary/events/evt-1")
    assert transport.requests[1].method == "PATCH"


def test_calendar_extractor_rejects_invalid_dict() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.delete_event(event_id={})
    with pytest.raises(ValueError):
        connector.list_events(calendar_id={"no_id": True})


def test_calendar_create_event_serializes_attendees() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"id": "evt-1"}))
    result = connector.create_event(
        summary="Sync",
        start={"dateTime": "2026-05-14T15:00:00Z"},
        end={"dateTime": "2026-05-14T15:30:00Z"},
        description="Weekly",
        location="Zoom",
        attendees=[{"email": "bob@example.test"}],
        send_updates="all",
    )
    assert result == {"id": "evt-1"}
    request = transport.requests[0]
    assert request.params == {"sendUpdates": "all"}
    assert request.json_body["attendees"] == [{"email": "bob@example.test"}]


def test_calendar_update_event_requires_patch() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.update_event(event_id="", patch={"summary": "x"})
    with pytest.raises(ValueError):
        connector.update_event(event_id="e", patch={})


def test_calendar_delete_event_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _calendar()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_event)
    assert opts is not None and opts.destructive is True
    connector.delete_event(event_id="e1")


def test_calendar_free_busy_requires_calendars() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.free_busy(
            time_min="2026-01-01T00:00:00Z",
            time_max="2026-01-02T00:00:00Z",
            calendars=[],
        )


def test_calendar_list_event_instances_serializes_params() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"items": []}))
    connector.list_event_instances(
        event_id="e1",
        time_min="2026-01-01T00:00:00Z",
        time_max="2026-02-01T00:00:00Z",
        page_token="np",
    )
    request = transport.requests[0]
    assert request.url.endswith("/calendars/primary/events/e1/instances")
    assert request.params["timeMin"] == "2026-01-01T00:00:00Z"
    assert request.params["pageToken"] == "np"


def test_calendar_list_event_instances_validates() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.list_event_instances(event_id="")
    with pytest.raises(ValueError):
        connector.list_event_instances(event_id="e", max_results=0)


def test_calendar_quick_add_event_posts_text() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"id": "e1"}))
    connector.quick_add_event("Lunch tomorrow noon", send_updates="all")
    request = transport.requests[0]
    assert request.url.endswith("/calendars/primary/events/quickAdd")
    assert request.params["text"] == "Lunch tomorrow noon"
    assert request.params["sendUpdates"] == "all"
    with pytest.raises(ValueError):
        connector.quick_add_event("")


def test_calendar_move_event_validates_and_calls() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"id": "e1"}))
    connector.move_event(event_id="e1", destination_calendar_id="cal2", send_updates="all")
    request = transport.requests[0]
    assert request.url.endswith("/calendars/primary/events/e1/move")
    assert request.params["destination"] == "cal2"
    with pytest.raises(ValueError):
        connector.move_event(event_id="", destination_calendar_id="x")


def test_calendar_respond_to_event_patches_attendee() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"id": "e1", "attendees": [{"email": "me@x.com"}]}))
    transport.enqueue(json_response({"id": "e1"}))
    connector.respond_to_event(event_id="e1", response_status="accepted", attendee_email="me@x.com")
    patch = transport.requests[1].json_body
    assert patch["attendees"][0]["responseStatus"] == "accepted"


def test_calendar_respond_to_event_validates() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.respond_to_event(event_id="e", response_status="bad", attendee_email="x@y")
    with pytest.raises(ValueError):
        connector.respond_to_event(event_id="", response_status="accepted", attendee_email="x@y")


def test_calendar_create_update_delete_calendar() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"id": "cal-1"}))
    transport.enqueue(json_response({"id": "cal-1", "summary": "Renamed"}))
    transport.enqueue(json_response({}))
    connector.create_calendar(summary="Project", description="desc")
    connector.update_calendar(calendar_id="cal-1", patch={"summary": "Renamed"})
    result = connector.delete_calendar(calendar_id="cal-1")
    assert transport.requests[0].json_body["summary"] == "Project"
    assert transport.requests[1].method == "PATCH"
    assert transport.requests[2].method == "DELETE"
    assert result["deleted"] is True


def test_calendar_create_calendar_validates() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.create_calendar(summary="")


def test_calendar_update_calendar_validates() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.update_calendar(calendar_id="", patch={"summary": "x"})
    with pytest.raises(ValueError):
        connector.update_calendar(calendar_id="c", patch={})


def test_calendar_delete_calendar_refuses_primary() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.delete_calendar(calendar_id="primary")
    with pytest.raises(ValueError):
        connector.delete_calendar(calendar_id="")


def test_calendar_clear_calendar_posts() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({}))
    result = connector.clear_calendar()
    assert transport.requests[0].url.endswith("/calendars/primary/clear")
    assert result["cleared"] is True


def test_calendar_acl_crud() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"items": []}))
    transport.enqueue(json_response({"id": "r1"}))
    transport.enqueue(json_response({}))
    connector.list_acl()
    connector.create_acl_rule(
        calendar_id="primary",
        scope_type="user",
        role="writer",
        scope_value="bob@example.test",
        send_notifications=False,
    )
    result = connector.delete_acl_rule(calendar_id="primary", rule_id="r1")
    create_payload = transport.requests[1].json_body
    assert create_payload["scope"]["type"] == "user"
    assert create_payload["scope"]["value"] == "bob@example.test"
    assert create_payload["role"] == "writer"
    assert transport.requests[2].method == "DELETE"
    assert result["deleted"] is True


def test_calendar_acl_rule_validates() -> None:
    connector, _ = _calendar()
    with pytest.raises(ValueError):
        connector.create_acl_rule(calendar_id="primary", scope_type="bad", role="reader")
    with pytest.raises(ValueError):
        connector.create_acl_rule(calendar_id="primary", scope_type="user", role="god")
    with pytest.raises(ValueError):
        connector.delete_acl_rule(calendar_id="primary", rule_id="")


def test_calendar_settings_and_colors() -> None:
    connector, transport = _calendar()
    transport.enqueue(json_response({"items": []}))
    transport.enqueue(json_response({"calendar": {}, "event": {}}))
    connector.list_settings()
    connector.get_colors()
    assert transport.requests[0].url.endswith("/users/me/settings")
    assert transport.requests[1].url.endswith("/colors")


# MARK: - Drive


def _drive() -> tuple[GoogleDriveToolSet, MockTransport]:
    transport = MockTransport()
    return GoogleDriveToolSet(token="at-drv", transport=transport), transport


def test_drive_search_files_serializes_query() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"files": []}))
    connector.search_files(query="name contains 'foo'", page_size=10)
    request = transport.requests[0]
    assert request.params["q"] == "name contains 'foo'"
    assert request.params["pageSize"] == 10


def test_drive_search_files_returns_summaries_without_raw_ids_by_default() -> None:
    connector, transport = _drive()
    transport.enqueue(
        json_response(
            {
                "files": [
                    {
                        "id": "drive-id-1",
                        "name": "Q3 plan.docx",
                        "mimeType": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        "modifiedTime": "2026-05-16T09:00:00Z",
                        "size": "12345",
                        "owners": [{"displayName": "Alice", "emailAddress": "alice@x.test"}],
                    },
                    {
                        "id": "drive-id-2",
                        "name": "Shared",
                        "mimeType": "application/vnd.google-apps.folder",
                        "modifiedTime": "2026-05-10T09:00:00Z",
                        "owners": [{"displayName": "Bob"}],
                    },
                ]
            }
        )
    )
    result = connector.search_files(query="name contains 'Q'")
    files = result["files"]
    assert files[0]["file_ref"] == "file_1"
    assert files[0]["name"] == "Q3 plan.docx"
    assert files[0]["owner"] == "Alice"
    assert "file_id" not in files[0]
    assert files[1]["folder_ref"] == "folder_2"
    assert "file_id" not in files[1]
    assert "folder_id" not in files[1]


def test_drive_search_files_include_ids_exposes_raw_ids() -> None:
    connector, transport = _drive()
    transport.enqueue(
        json_response(
            {
                "files": [
                    {
                        "id": "drive-id-1",
                        "name": "plan.docx",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-05-16T09:00:00Z",
                        "owners": [{"displayName": "Alice"}],
                    }
                ]
            }
        )
    )
    result = connector.search_files(query="x", include_ids=True)
    assert result["files"][0]["file_id"] == "drive-id-1"


def test_drive_search_files_raw_mode_returns_provider_payload() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"files": [{"id": "x", "name": "y"}], "nextPageToken": "n"}))
    result = connector.search_files(query="x", include_metadata=False)
    assert "files" in result
    assert result["files"][0]["id"] == "x"
    assert result["nextPageToken"] == "n"


def test_drive_download_file_accepts_dict_with_file_id() -> None:
    from maivn_tools.runtime.http import HttpResponse

    connector, transport = _drive()
    transport.enqueue(
        HttpResponse(
            status=200,
            headers={"Content-Type": "text/plain"},
            body=b"hi",
            url="https://drive/x",
        )
    )
    result = connector.download_file(file_id={"file_id": "abc-from-dict", "name": "x"})
    assert result["file_id"] == "abc-from-dict"
    assert transport.requests[0].url.endswith("/files/abc-from-dict")
    assert transport.requests[0].params == {"alt": "media", "supportsAllDrives": "true"}


def test_drive_delete_file_accepts_dict_input() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({}))
    connector.delete_file({"file_id": "del-1", "name": "doomed.txt"})
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[0].url.endswith("/files/del-1")


def test_drive_move_file_accepts_dict_input() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "mv-1"}))
    connector.move_file(
        {"file_id": "mv-1", "name": "x"},
        add_parent_id="P2",
        remove_parent_id="P1",
    )
    assert "/files/mv-1" in transport.requests[0].url


def test_drive_update_file_metadata_accepts_dict_input() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "u-1"}))
    connector.update_file_metadata({"file_id": "u-1"}, {"description": "d"})
    assert "/files/u-1" in transport.requests[0].url
    assert transport.requests[0].json_body == {"description": "d"}


def test_drive_empty_trash_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _drive()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.empty_trash)
    assert opts is not None and opts.destructive is True
    connector.empty_trash()


def test_drive_download_returns_base64_payload() -> None:
    from maivn_tools.runtime.http import HttpResponse

    connector, transport = _drive()
    transport.enqueue(
        HttpResponse(
            status=200,
            headers={"Content-Type": "application/octet-stream"},
            body=b"hello",
            url="https://drive/x",
        )
    )
    result = connector.download_file(file_id="abc")
    import base64

    assert base64.b64decode(result["content_base64"]) == b"hello"
    assert result["size"] == 5
    assert result["content_type"] == "application/octet-stream"


def test_drive_export_validates_inputs() -> None:
    connector, _ = _drive()
    with pytest.raises(ValueError):
        connector.export_file(file_id="", mime_type="application/pdf")
    with pytest.raises(ValueError):
        connector.export_file(file_id="x", mime_type="")


def test_drive_create_folder_sets_mime_type_and_parent() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "f1"}))
    connector.create_folder(name="reports", parent_id="root")
    payload = transport.requests[0].json_body
    assert payload["mimeType"] == "application/vnd.google-apps.folder"
    assert payload["parents"] == ["root"]


def test_drive_delete_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _drive()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_file)
    assert opts is not None and opts.destructive is True
    connector.delete_file(file_id="x")


def test_drive_trash_untrash_and_rename() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "x", "trashed": True}))
    transport.enqueue(json_response({"id": "x", "trashed": False}))
    transport.enqueue(json_response({"id": "x", "name": "new.txt"}))
    connector.trash_file("x")
    connector.untrash_file("x")
    connector.rename_file("x", "new.txt")
    assert transport.requests[0].json_body == {"trashed": True}
    assert transport.requests[1].json_body == {"trashed": False}
    assert transport.requests[2].json_body == {"name": "new.txt"}


def test_drive_trash_untrash_rename_validates() -> None:
    connector, _ = _drive()
    with pytest.raises(ValueError):
        connector.trash_file("")
    with pytest.raises(ValueError):
        connector.untrash_file("")
    with pytest.raises(ValueError):
        connector.rename_file("", "n")
    with pytest.raises(ValueError):
        connector.rename_file("x", "")


def test_drive_update_file_metadata_validates_and_calls() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "x"}))
    connector.update_file_metadata("x", {"description": "d"})
    assert transport.requests[0].json_body == {"description": "d"}
    with pytest.raises(ValueError):
        connector.update_file_metadata("", {"name": "n"})
    with pytest.raises(ValueError):
        connector.update_file_metadata("x", {})


def test_drive_copy_file_serializes_payload() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "y"}))
    connector.copy_file("x", name="copy.txt", parent_id="root")
    payload = transport.requests[0].json_body
    assert payload["name"] == "copy.txt"
    assert payload["parents"] == ["root"]
    with pytest.raises(ValueError):
        connector.copy_file("")


def test_drive_move_file_uses_add_remove_parents() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "x"}))
    connector.move_file(file_id="x", add_parent_id="P2", remove_parent_id="P1")
    request = transport.requests[0]
    assert request.method == "PATCH"
    assert request.params["addParents"] == "P2"
    assert request.params["removeParents"] == "P1"
    with pytest.raises(ValueError):
        connector.move_file(file_id="", add_parent_id="x")


def test_drive_empty_trash() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({}))
    result = connector.empty_trash()
    assert transport.requests[0].method == "DELETE"
    assert result["emptied"] is True


def test_drive_create_shortcut() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"id": "s1"}))
    connector.create_shortcut(target_id="t1", name="Shortcut", parent_id="p")
    payload = transport.requests[0].json_body
    assert payload["mimeType"] == "application/vnd.google-apps.shortcut"
    assert payload["shortcutDetails"]["targetId"] == "t1"
    with pytest.raises(ValueError):
        connector.create_shortcut(target_id="", name="x")


def test_drive_revisions_crud() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"revisions": []}))
    transport.enqueue(json_response({"id": "r1"}))
    transport.enqueue(json_response({}))
    connector.list_revisions("x")
    connector.get_revision("x", "r1")
    result = connector.delete_revision("x", "r1")
    assert transport.requests[0].url.endswith("/files/x/revisions")
    assert transport.requests[2].method == "DELETE"
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.list_revisions("")
    with pytest.raises(ValueError):
        connector.list_revisions("x", page_size=0)


def test_drive_permissions_crud() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"permissions": []}))
    transport.enqueue(json_response({"id": "perm1"}))
    transport.enqueue(json_response({"id": "perm1", "role": "writer"}))
    transport.enqueue(json_response({}))
    connector.list_permissions("x")
    connector.share_file(
        file_id="x",
        permission_type="user",
        role="reader",
        email_address="bob@example.test",
    )
    connector.update_permission(file_id="x", permission_id="perm1", patch={"role": "writer"})
    result = connector.revoke_permission(file_id="x", permission_id="perm1")
    payload = transport.requests[1].json_body
    assert payload["type"] == "user"
    assert payload["emailAddress"] == "bob@example.test"
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[3].method == "DELETE"
    assert result["deleted"] is True


def test_drive_share_validates() -> None:
    connector, _ = _drive()
    with pytest.raises(ValueError):
        connector.share_file(file_id="x", permission_type="bad", role="reader")
    with pytest.raises(ValueError):
        connector.share_file(file_id="x", permission_type="user", role="god")
    with pytest.raises(ValueError):
        connector.share_file(file_id="", permission_type="user", role="reader")


def test_drive_update_permission_validates() -> None:
    connector, _ = _drive()
    with pytest.raises(ValueError):
        connector.update_permission(file_id="", permission_id="p", patch={"role": "r"})
    with pytest.raises(ValueError):
        connector.update_permission(file_id="x", permission_id="p", patch={})


def test_drive_drives_and_changes() -> None:
    connector, transport = _drive()
    transport.enqueue(json_response({"drives": []}))
    transport.enqueue(json_response({"changes": []}))
    transport.enqueue(json_response({"startPageToken": "12"}))
    transport.enqueue(json_response({"user": {"emailAddress": "me@x"}}))
    connector.list_drives()
    connector.list_changes(page_token="5")
    connector.get_changes_start_page_token()
    connector.get_about()
    assert transport.requests[0].url.endswith("/drives")
    assert transport.requests[1].params["pageToken"] == "5"
    assert transport.requests[2].url.endswith("/changes/startPageToken")
    assert transport.requests[3].url.endswith("/about")


def test_drive_list_changes_validates() -> None:
    connector, _ = _drive()
    with pytest.raises(ValueError):
        connector.list_changes(page_token="")
    with pytest.raises(ValueError):
        connector.list_changes(page_token="1", page_size=0)


def test_drive_list_drives_validates() -> None:
    connector, _ = _drive()
    with pytest.raises(ValueError):
        connector.list_drives(page_size=0)
