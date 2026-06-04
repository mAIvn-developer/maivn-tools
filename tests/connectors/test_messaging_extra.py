"""Agent-ready tests for Discord, Telegram, and WhatsApp Business toolsets.

Focuses on summary defaults, ID opt-in, tolerant write inputs, and
destructive-tool marking. Wire-level coverage lives in
``test_social_media_batch2.py``.
"""
# pyright: strict

from __future__ import annotations

from typing import Any

import pytest

from maivn_tools.connectors.discord import DiscordToolSet
from maivn_tools.connectors.telegram import TelegramToolSet
from maivn_tools.connectors.whatsapp import WhatsAppBusinessToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Discord


def _discord() -> tuple[DiscordToolSet, MockTransport]:
    transport = MockTransport()
    return DiscordToolSet(token="abc", transport=transport), transport


def test_discord_list_user_guilds_summaries_hide_ids_by_default() -> None:
    connector, transport = _discord()
    transport.enqueue(
        json_response(
            [
                {"id": "111", "name": "Eng", "owner": False, "permissions": "0"},
                {"id": "222", "name": "Sales", "owner": True, "permissions": "0"},
            ]
        )
    )
    result = connector.list_current_user_guilds(limit=10)
    assert result["guilds"][0]["guild_ref"] == "guild_1"
    assert result["guilds"][0]["name"] == "Eng"
    assert "guild_id" not in result["guilds"][0]
    assert result["guilds"][1]["guild_ref"] == "guild_2"


def test_discord_list_user_guilds_can_include_ids() -> None:
    connector, transport = _discord()
    transport.enqueue(json_response([{"id": "111", "name": "Eng"}]))
    result = connector.list_current_user_guilds(limit=10, include_ids=True)
    assert result["guilds"][0]["guild_id"] == "111"


def test_discord_list_guild_channels_summaries_and_caches_for_writes() -> None:
    connector, transport = _discord()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "100",
                    "name": "general",
                    "type": 0,
                    "topic": "company-wide",
                    "position": 0,
                },
                {
                    "id": "200",
                    "name": "ops",
                    "type": 0,
                    "topic": "alerts",
                    "position": 1,
                },
            ]
        )
    )
    listed = connector.list_guild_channels("guild-1")
    assert listed["channels"][0]["channel_ref"] == "channel_1"
    assert listed["channels"][0]["name"] == "general"
    assert "channel_id" not in listed["channels"][0]

    # Friendly-name write path
    transport.enqueue(json_response({"id": "msg-1"}))
    connector.create_message(channel_id="ops", content="alert!")
    assert "/channels/200/messages" in transport.requests[1].url


def test_discord_list_messages_summaries_and_edit_with_dict() -> None:
    connector, transport = _discord()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "msg-1",
                    "content": "hi",
                    "timestamp": "2026-05-16T12:00:00Z",
                    "attachments": [],
                    "author": {"username": "alice"},
                }
            ]
        )
    )
    result = connector.list_messages("123", limit=5, include_ids=True)
    msg = result["messages"][0]
    assert msg["message_ref"] == "message_1"
    assert msg["author"] == "alice"
    assert msg["content"] == "hi"
    assert msg["message_id"] == "msg-1"

    transport.enqueue(json_response({"id": "msg-1"}))
    connector.edit_message(channel_id="123", message_id=msg, content="updated")
    assert transport.requests[1].method == "PATCH"
    assert "/channels/123/messages/msg-1" in transport.requests[1].url


def test_discord_list_messages_summaries_hide_ids_by_default() -> None:
    connector, transport = _discord()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "msg-1",
                    "content": "x",
                    "timestamp": "2026-05-16T12:00:00Z",
                    "attachments": [{"id": "a"}],
                    "author": {"username": "bob"},
                }
            ]
        )
    )
    result = connector.list_messages("chan-1", limit=5)
    msg = result["messages"][0]
    assert msg["has_attachments"] is True
    assert "message_id" not in msg


def test_discord_delete_message_tolerates_message_dict_and_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _discord()
    opts = get_toolify_options(connector.delete_message)
    assert opts is not None and opts.destructive is True

    transport.enqueue(json_response({}))
    connector.delete_message(channel_id="chan-1", message_id={"message_id": "msg-7"})
    assert "/channels/chan-1/messages/msg-7" in transport.requests[0].url
    assert transport.requests[0].method == "DELETE"


def test_discord_list_messages_raw_mode_passthrough() -> None:
    connector, transport = _discord()
    raw = [{"id": "msg-1", "content": "raw"}]
    transport.enqueue(json_response(raw))
    result = connector.list_messages("chan-1", include_metadata=False)
    assert result == raw


# MARK: - Telegram


def _telegram() -> tuple[TelegramToolSet, MockTransport]:
    transport = MockTransport()
    return TelegramToolSet(bot_token="123:ABC", transport=transport), transport


def test_telegram_get_updates_summaries_hide_ids_by_default() -> None:
    connector, transport = _telegram()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 1001,
                        "message": {
                            "message_id": 50,
                            "from": {"id": 1, "username": "alice"},
                            "chat": {"id": -42, "title": "Ops"},
                            "text": "rollout looks good",
                        },
                    },
                    {
                        "update_id": 1002,
                        "callback_query": {
                            "id": "cb-1",
                            "from": {"id": 1, "username": "alice"},
                            "data": "click",
                        },
                    },
                ],
            }
        )
    )
    result = connector.get_updates(limit=10)
    assert result["updates"][0]["update_ref"] == "update_1"
    assert result["updates"][0]["type"] == "message"
    assert result["updates"][0]["text"] == "rollout looks good"
    assert result["updates"][0]["chat_title"] == "Ops"
    assert "update_id" not in result["updates"][0]
    assert result["updates"][1]["type"] == "callback_query"


def test_telegram_get_updates_can_include_ids() -> None:
    connector, transport = _telegram()
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 1001,
                        "message": {
                            "message_id": 50,
                            "from": {"id": 1, "username": "alice"},
                            "chat": {"id": -42, "title": "Ops"},
                            "text": "hi",
                        },
                    }
                ],
            }
        )
    )
    result = connector.get_updates(limit=10, include_ids=True)
    upd = result["updates"][0]
    assert upd["update_id"] == 1001
    assert upd["message_id"] == 50
    assert upd["chat_id"] == -42


def test_telegram_send_message_accepts_update_dict_for_chat_and_message() -> None:
    connector, transport = _telegram()
    # Seed an update so we can feed the dict straight to send_message
    transport.enqueue(
        json_response(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 1001,
                        "message": {
                            "message_id": 50,
                            "from": {"id": 1, "username": "alice"},
                            "chat": {"id": -42, "title": "Ops"},
                            "text": "hi",
                        },
                    }
                ],
            }
        )
    )
    updates = connector.get_updates(limit=1, include_ids=True)
    update = updates["updates"][0]
    transport.enqueue(json_response({"ok": True, "result": {"message_id": 99}}))
    connector.send_message(
        chat_id=update,
        text="thanks",
        reply_to_message_id=update,
    )
    body = transport.requests[1].json_body
    assert body["chat_id"] == -42
    assert body["reply_to_message_id"] == 50


def test_telegram_delete_message_is_destructive_and_takes_dicts() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _telegram()
    opts = get_toolify_options(connector.delete_message)
    assert opts is not None and opts.destructive is True

    transport.enqueue(json_response({"ok": True, "result": True}))
    connector.delete_message(
        chat_id={"chat_id": -42},
        message_id={"message_id": 99},
    )
    body = transport.requests[0].json_body
    assert body["chat_id"] == -42
    assert body["message_id"] == 99


def test_telegram_get_updates_raw_mode_passthrough() -> None:
    connector, transport = _telegram()
    raw: dict[str, Any] = {"ok": True, "result": []}
    transport.enqueue(json_response(raw))
    result = connector.get_updates(limit=10, include_metadata=False)
    assert result == raw


# MARK: - WhatsApp Business


def _whatsapp() -> tuple[WhatsAppBusinessToolSet, MockTransport]:
    transport = MockTransport()
    return (
        WhatsAppBusinessToolSet(
            access_token="t",
            phone_number_id="123",
            transport=transport,
        ),
        transport,
    )


def test_whatsapp_list_templates_summaries_hide_ids_by_default() -> None:
    connector, transport = _whatsapp()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "tpl-1",
                        "name": "welcome",
                        "language": "en_US",
                        "category": "MARKETING",
                        "status": "APPROVED",
                    },
                    {
                        "id": "tpl-2",
                        "name": "order_status",
                        "language": "en_US",
                        "category": "UTILITY",
                        "status": "APPROVED",
                    },
                ],
                "paging": {"cursors": {"after": "cur"}},
            }
        )
    )
    result = connector.list_message_templates("waba-1", limit=10)
    assert result["templates"][0]["template_ref"] == "template_1"
    assert result["templates"][0]["name"] == "welcome"
    assert "template_id" not in result["templates"][0]
    assert result["templates"][1]["template_ref"] == "template_2"
    assert result["paging"] == {"cursors": {"after": "cur"}}


def test_whatsapp_list_templates_can_return_ids() -> None:
    connector, transport = _whatsapp()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "tpl-1",
                        "name": "welcome",
                        "language": "en_US",
                        "category": "MARKETING",
                        "status": "APPROVED",
                    }
                ]
            }
        )
    )
    result = connector.list_message_templates("waba-1", limit=10, include_ids=True)
    assert result["templates"][0]["template_id"] == "tpl-1"


def test_whatsapp_mark_message_read_accepts_send_response_dict() -> None:
    connector, transport = _whatsapp()
    # Tolerant input: pass the entire response from send_text into
    # mark_message_read.
    send_response = {"messaging_product": "whatsapp", "messages": [{"id": "wamid.123"}]}
    transport.enqueue(json_response({"success": True}))
    connector.mark_message_read(message_id=send_response)
    body = transport.requests[0].json_body
    assert body["message_id"] == "wamid.123"


def test_whatsapp_mark_message_read_accepts_simple_dict() -> None:
    connector, transport = _whatsapp()
    transport.enqueue(json_response({"success": True}))
    connector.mark_message_read(message_id={"id": "wamid.555"})
    assert transport.requests[0].json_body["message_id"] == "wamid.555"


def test_whatsapp_delete_media_marked_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _whatsapp()
    opts = get_toolify_options(connector.delete_media)
    assert opts is not None and opts.destructive is True


def test_whatsapp_mark_message_read_requires_id_in_dict() -> None:
    connector, _ = _whatsapp()
    with pytest.raises(ValueError):
        connector.mark_message_read(message_id={"foo": "bar"})


def test_whatsapp_list_templates_raw_mode_passthrough() -> None:
    connector, transport = _whatsapp()
    raw = {"data": [{"id": "tpl-1", "name": "x"}]}
    transport.enqueue(json_response(raw))
    result = connector.list_message_templates("waba-1", include_metadata=False)
    assert result == raw
