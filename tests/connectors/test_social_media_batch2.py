"""Tests for social media batch 2 connectors.

Reddit, Pinterest, Discord, Telegram, WhatsApp Business, Mastodon,
Bluesky, Threads, and Buffer.
"""

# pyright: strict

from __future__ import annotations

import pytest
from maivn import Agent

from maivn_tools.connectors.bluesky import BlueskyToolSet
from maivn_tools.connectors.buffer import BufferToolSet
from maivn_tools.connectors.discord import DiscordToolSet
from maivn_tools.connectors.mastodon import MastodonToolSet
from maivn_tools.connectors.pinterest import PinterestToolSet
from maivn_tools.connectors.reddit import RedditToolSet
from maivn_tools.connectors.telegram import TelegramToolSet
from maivn_tools.connectors.threads import ThreadsToolSet
from maivn_tools.connectors.whatsapp import WhatsAppBusinessToolSet
from maivn_tools.testing import MockTransport, json_response


def _destructive_tool_names(toolset_instance: object) -> set[str]:
    """Return names of tools tagged ``destructive`` on a toolset."""
    full = Agent(name="t", description="x", system_prompt="x", api_key="mock")
    full.add_toolset(toolset_instance)
    filtered = Agent(name="t2", description="x", system_prompt="x", api_key="mock")
    filtered.add_toolset(toolset_instance, exclude_tags=["destructive"])
    full_names = {tool.name for tool in full.list_tools()}
    safe_names = {tool.name for tool in filtered.list_tools()}
    return full_names - safe_names


# MARK: - Reddit


def _reddit() -> tuple[RedditToolSet, MockTransport]:
    transport = MockTransport()
    return (
        RedditToolSet(
            access_token="bt",
            user_agent="maivn-test:1.0 (by /u/test)",
            transport=transport,
        ),
        transport,
    )


def test_reddit_requires_token_and_agent() -> None:
    with pytest.raises(ValueError):
        RedditToolSet(access_token="", user_agent="ua")
    with pytest.raises(ValueError):
        RedditToolSet(access_token="t", user_agent="")


def test_reddit_reads() -> None:
    connector, transport = _reddit()
    for _ in range(6):
        transport.enqueue(json_response({"data": {}}))
    connector.get_me()
    connector.list_subscribed_subreddits(limit=10, after="t3_abc")
    connector.get_subreddit_about("python")
    connector.list_subreddit_posts("python", sort="new", limit=5, after="t3_x", time="day")
    connector.search("claude", subreddit="python", sort="top", limit=10, after="cur")
    connector.get_post(subreddit="python", post_id="abc")
    assert transport.requests[0].headers["Authorization"] == "Bearer bt"
    assert transport.requests[0].headers["User-Agent"].startswith("maivn-test")
    assert transport.requests[3].url.endswith("/r/python/new")
    with pytest.raises(ValueError):
        connector.get_subreddit_about("")
    with pytest.raises(ValueError):
        connector.list_subreddit_posts("python", sort="invalid")
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.search("x", sort="bogus")
    with pytest.raises(ValueError):
        connector.get_post(subreddit="", post_id="x")


def test_reddit_writes() -> None:
    connector, transport = _reddit()
    for _ in range(8):
        transport.enqueue(json_response({"json": {"errors": []}}))
    connector.submit_post(subreddit="python", title="hi", kind="self", text="body")
    connector.submit_post(subreddit="python", title="hi", kind="link", url="https://x")
    connector.submit_comment(parent="t3_a", text="cool")
    connector.vote(thing="t3_a", direction=1)
    connector.save("t3_a", category="reads")
    connector.unsave("t3_a")
    connector.subscribe("python")
    connector.delete_thing("t3_a")
    body = transport.requests[0].data
    assert isinstance(body, bytes)
    assert b"sr=python" in body
    assert transport.requests[0].headers["Content-Type"] == "application/x-www-form-urlencoded"
    with pytest.raises(ValueError):
        connector.submit_post(subreddit="", title="t", kind="self", text="b")
    with pytest.raises(ValueError):
        connector.submit_post(subreddit="r", title="t", kind="self")
    with pytest.raises(ValueError):
        connector.submit_post(subreddit="r", title="t", kind="link")
    with pytest.raises(ValueError):
        connector.submit_post(subreddit="r", title="t", kind="bogus", text="x")
    with pytest.raises(ValueError):
        connector.submit_comment(parent="", text="x")
    with pytest.raises(ValueError):
        connector.vote(thing="", direction=1)
    with pytest.raises(ValueError):
        connector.vote(thing="t3", direction=5)
    with pytest.raises(ValueError):
        connector.save("")
    with pytest.raises(ValueError):
        connector.unsave("")
    with pytest.raises(ValueError):
        connector.subscribe("")
    with pytest.raises(ValueError):
        connector.delete_thing("")


# MARK: - Pinterest


def _pinterest() -> tuple[PinterestToolSet, MockTransport]:
    transport = MockTransport()
    return PinterestToolSet(access_token="t", transport=transport), transport


def test_pinterest_requires_token() -> None:
    with pytest.raises(ValueError):
        PinterestToolSet(access_token="")


def test_pinterest_boards_and_pins() -> None:
    connector, transport = _pinterest()
    for _ in range(10):
        transport.enqueue(json_response({"items": []}))
    connector.get_user_account()
    connector.list_boards(page_size=10, bookmark="b", privacy="PUBLIC")
    connector.get_board("board-1")
    connector.create_board(name="new", description="d", privacy="SECRET")
    connector.delete_board("board-1")
    connector.list_board_pins("board-1", page_size=10, bookmark="b")
    connector.list_pins(page_size=10, bookmark="b")
    connector.get_pin("pin-1")
    connector.create_pin(
        board_id="board-1",
        media_source={"source_type": "image_url", "url": "https://x.png"},
        title="t",
        description="d",
        link="https://l",
        alt_text="a",
    )
    connector.delete_pin("pin-1")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_board("")
    with pytest.raises(ValueError):
        connector.create_board(name="")
    with pytest.raises(ValueError):
        connector.create_board(name="x", privacy="bogus")
    with pytest.raises(ValueError):
        connector.delete_board("")
    with pytest.raises(ValueError):
        connector.list_board_pins("")
    with pytest.raises(ValueError):
        connector.get_pin("")
    with pytest.raises(ValueError):
        connector.create_pin(board_id="", media_source={"x": 1})
    with pytest.raises(ValueError):
        connector.create_pin(board_id="b", media_source={})
    with pytest.raises(ValueError):
        connector.delete_pin("")


def test_pinterest_analytics() -> None:
    connector, transport = _pinterest()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.get_pin_analytics(
        "pin-1",
        start_date="2026-01-01",
        end_date="2026-01-31",
        metric_types=["IMPRESSION", "CLICKTHROUGH"],
    )
    connector.get_user_analytics(
        start_date="2026-01-01",
        end_date="2026-01-31",
        metric_types=["IMPRESSION"],
    )
    assert transport.requests[0].params["metric_types"] == "IMPRESSION,CLICKTHROUGH"
    with pytest.raises(ValueError):
        connector.get_pin_analytics("", start_date="a", end_date="b", metric_types=["x"])
    with pytest.raises(ValueError):
        connector.get_pin_analytics("p", start_date="a", end_date="b", metric_types=[])
    with pytest.raises(ValueError):
        connector.get_user_analytics(start_date="", end_date="b", metric_types=["x"])
    with pytest.raises(ValueError):
        connector.get_user_analytics(start_date="a", end_date="b", metric_types=[])


# MARK: - Discord


def _discord() -> tuple[DiscordToolSet, MockTransport]:
    transport = MockTransport()
    return DiscordToolSet(token="abc", transport=transport), transport


def test_discord_requires_token_and_type() -> None:
    with pytest.raises(ValueError):
        DiscordToolSet(token="")
    with pytest.raises(ValueError):
        DiscordToolSet(token="x", token_type="bogus")


def test_discord_guild_and_channel() -> None:
    connector, transport = _discord()
    for _ in range(6):
        transport.enqueue(json_response({"id": "1"}))
    connector.get_current_user()
    connector.list_current_user_guilds(limit=10, before="b", after="a")
    connector.get_guild("g1")
    connector.list_guild_channels("g1")
    connector.list_guild_members("g1", limit=50, after="u1")
    connector.get_channel("c1")
    assert transport.requests[0].headers["Authorization"] == "Bot abc"
    assert "/v10/users/@me" in transport.requests[0].url
    with pytest.raises(ValueError):
        connector.get_guild("")
    with pytest.raises(ValueError):
        connector.list_guild_channels("")
    with pytest.raises(ValueError):
        connector.list_guild_members("")
    with pytest.raises(ValueError):
        connector.get_channel("")


def test_discord_messages() -> None:
    connector, transport = _discord()
    for _ in range(6):
        transport.enqueue(json_response({"id": "m1"}))
    connector.list_messages("c1", limit=10, before="b", after="a", around="x")
    connector.get_message(channel_id="c1", message_id="m1")
    connector.create_message(channel_id="c1", content="hi", tts=True)
    connector.edit_message(channel_id="c1", message_id="m1", content="updated")
    connector.delete_message(channel_id="c1", message_id="m1")
    connector.create_reaction(channel_id="c1", message_id="m1", emoji="🔥")
    assert transport.requests[3].method == "PATCH"
    assert transport.requests[4].method == "DELETE"
    assert transport.requests[5].method == "PUT"
    with pytest.raises(ValueError):
        connector.list_messages("")
    with pytest.raises(ValueError):
        connector.get_message(channel_id="", message_id="m")
    with pytest.raises(ValueError):
        connector.create_message(channel_id="")
    with pytest.raises(ValueError):
        connector.create_message(channel_id="c")
    with pytest.raises(ValueError):
        connector.edit_message(channel_id="", message_id="m")
    with pytest.raises(ValueError):
        connector.edit_message(channel_id="c", message_id="m")
    with pytest.raises(ValueError):
        connector.delete_message(channel_id="", message_id="m")
    with pytest.raises(ValueError):
        connector.create_reaction(channel_id="", message_id="m", emoji="x")


def test_discord_dm_roles_webhook() -> None:
    connector, transport = _discord()
    for _ in range(4):
        transport.enqueue(json_response({"id": "1"}))
    connector.create_dm("u1")
    connector.add_guild_member_role(guild_id="g1", user_id="u1", role_id="r1")
    connector.remove_guild_member(guild_id="g1", user_id="u1")
    connector.execute_webhook(
        webhook_id="w1",
        webhook_token="tok",
        content="hello",
        username="bot",
        avatar_url="https://x",
    )
    assert transport.requests[1].method == "PUT"
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.create_dm("")
    with pytest.raises(ValueError):
        connector.add_guild_member_role(guild_id="", user_id="u", role_id="r")
    with pytest.raises(ValueError):
        connector.remove_guild_member(guild_id="", user_id="u")
    with pytest.raises(ValueError):
        connector.execute_webhook(webhook_id="", webhook_token="t", content="x")
    with pytest.raises(ValueError):
        connector.execute_webhook(webhook_id="w", webhook_token="t")


# MARK: - Telegram


def _telegram() -> tuple[TelegramToolSet, MockTransport]:
    transport = MockTransport()
    return TelegramToolSet(bot_token="123:ABC", transport=transport), transport


def test_telegram_requires_token() -> None:
    with pytest.raises(ValueError):
        TelegramToolSet(bot_token="")


def test_telegram_endpoints() -> None:
    connector, transport = _telegram()
    for _ in range(11):
        transport.enqueue(json_response({"ok": True, "result": {}}))
    connector.get_me()
    connector.get_updates(offset=1, limit=50, timeout=10, allowed_updates=["message"])
    connector.send_message(
        chat_id=123,
        text="hi",
        parse_mode="Markdown",
        reply_to_message_id=1,
        disable_notification=True,
        reply_markup={"inline_keyboard": []},
    )
    connector.edit_message_text(chat_id=123, message_id=99, text="new", parse_mode="HTML")
    connector.delete_message(chat_id=123, message_id=99)
    connector.send_photo(chat_id=123, photo="https://x.png", caption="cap", parse_mode="HTML")
    connector.answer_callback_query(callback_query_id="cb1", text="ack", show_alert=True)
    connector.get_chat("@channel")
    connector.get_chat_member(chat_id=123, user_id=456)
    connector.set_webhook(url="https://hook", secret_token="s", allowed_updates=["message"])
    connector.delete_webhook(drop_pending_updates=True)
    assert transport.requests[0].url.endswith("/bot123:ABC/getMe")
    assert transport.requests[2].json_body["text"] == "hi"
    with pytest.raises(ValueError):
        connector.send_message(chat_id="", text="x")
    with pytest.raises(ValueError):
        connector.send_message(chat_id=1, text="")
    with pytest.raises(ValueError):
        connector.edit_message_text(chat_id="", message_id=1, text="x")
    with pytest.raises(ValueError):
        connector.delete_message(chat_id="", message_id=1)
    with pytest.raises(ValueError):
        connector.send_photo(chat_id="", photo="x")
    with pytest.raises(ValueError):
        connector.answer_callback_query(callback_query_id="")
    with pytest.raises(ValueError):
        connector.get_chat("")
    with pytest.raises(ValueError):
        connector.get_chat_member(chat_id="", user_id=1)
    with pytest.raises(ValueError):
        connector.set_webhook(url="")


def test_telegram_webhook_info() -> None:
    connector, transport = _telegram()
    transport.enqueue(json_response({"ok": True, "result": {"url": "x"}}))
    connector.get_webhook_info()
    assert transport.requests[0].url.endswith("getWebhookInfo")


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


def test_whatsapp_requires_token_and_phone() -> None:
    with pytest.raises(ValueError):
        WhatsAppBusinessToolSet(access_token="", phone_number_id="1")
    with pytest.raises(ValueError):
        WhatsAppBusinessToolSet(access_token="t", phone_number_id="")


def test_whatsapp_messaging() -> None:
    connector, transport = _whatsapp()
    for _ in range(5):
        transport.enqueue(json_response({"messages": [{"id": "wamid"}]}))
    connector.send_text(to="+1", body="hello", preview_url=True)
    connector.send_template(
        to="+1",
        template_name="hello_world",
        language_code="en_US",
        components=[{"type": "body", "parameters": []}],
    )
    connector.send_media(to="+1", media_type="image", link="https://x.png", caption="c")
    connector.send_media(to="+1", media_type="document", media_id="mid", filename="f.pdf")
    connector.mark_message_read(message_id="wamid")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert "/v23.0/123/messages" in transport.requests[0].url
    assert transport.requests[0].json_body["text"]["body"] == "hello"
    with pytest.raises(ValueError):
        connector.send_text(to="", body="x")
    with pytest.raises(ValueError):
        connector.send_text(to="+1", body="")
    with pytest.raises(ValueError):
        connector.send_template(to="", template_name="t", language_code="en")
    with pytest.raises(ValueError):
        connector.send_template(to="+1", template_name="", language_code="en")
    with pytest.raises(ValueError):
        connector.send_template(to="+1", template_name="t", language_code="")
    with pytest.raises(ValueError):
        connector.send_media(to="", media_type="image", link="x")
    with pytest.raises(ValueError):
        connector.send_media(to="+1", media_type="bogus", link="x")
    with pytest.raises(ValueError):
        connector.send_media(to="+1", media_type="image")
    with pytest.raises(ValueError):
        connector.send_media(to="+1", media_type="image", link="x", media_id="y")
    with pytest.raises(ValueError):
        connector.mark_message_read(message_id="")


def test_whatsapp_media_and_templates() -> None:
    connector, transport = _whatsapp()
    for _ in range(5):
        transport.enqueue(json_response({"id": "x"}))
    connector.get_media_metadata("mid")
    connector.delete_media("mid")
    connector.list_phone_numbers("waba1")
    connector.list_message_templates("waba1", limit=10)
    connector.create_message_template(
        waba_id="waba1",
        name="welcome",
        language="en_US",
        category="MARKETING",
        components=[{"type": "BODY", "text": "hi"}],
    )
    assert transport.requests[1].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_media_metadata("")
    with pytest.raises(ValueError):
        connector.delete_media("")
    with pytest.raises(ValueError):
        connector.list_phone_numbers("")
    with pytest.raises(ValueError):
        connector.list_message_templates("")
    with pytest.raises(ValueError):
        connector.create_message_template(
            waba_id="",
            name="n",
            language="en",
            category="c",
            components=[{}],
        )
    with pytest.raises(ValueError):
        connector.create_message_template(
            waba_id="w",
            name="n",
            language="en",
            category="c",
            components=[],
        )


# MARK: - Mastodon


def _mastodon() -> tuple[MastodonToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MastodonToolSet(
            access_token="t",
            instance_url="https://mastodon.social",
            transport=transport,
        ),
        transport,
    )


def test_mastodon_requires_token_and_url() -> None:
    with pytest.raises(ValueError):
        MastodonToolSet(access_token="", instance_url="https://x")
    with pytest.raises(ValueError):
        MastodonToolSet(access_token="t", instance_url="")


def test_mastodon_reads() -> None:
    connector, transport = _mastodon()
    for _ in range(8):
        transport.enqueue(json_response({"id": "1"}))
    connector.verify_credentials()
    connector.get_account("a1")
    connector.lookup_account("user@server")
    connector.home_timeline(limit=10, max_id="m", since_id="s")
    connector.public_timeline(local=True, remote=False, only_media=True, limit=10)
    connector.hashtag_timeline("python", limit=10, max_id="m")
    connector.get_status("s1")
    connector.search("python", type="hashtags", resolve=True, limit=10)
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[7].url.endswith("/api/v2/search")
    with pytest.raises(ValueError):
        connector.get_account("")
    with pytest.raises(ValueError):
        connector.lookup_account("")
    with pytest.raises(ValueError):
        connector.hashtag_timeline("")
    with pytest.raises(ValueError):
        connector.get_status("")
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.search("x", type="bogus")


def test_mastodon_writes() -> None:
    connector, transport = _mastodon()
    for _ in range(7):
        transport.enqueue(json_response({"id": "p1"}))
    connector.post_status(
        status="hi",
        in_reply_to_id="r",
        visibility="public",
        spoiler_text="cw",
        sensitive=True,
        language="en",
        idempotency_key="key-1",
    )
    connector.delete_status("p1")
    connector.favourite_status("p1")
    connector.reblog_status("p1", visibility="unlisted")
    connector.follow_account("a1")
    connector.unfollow_account("a1")
    connector.list_notifications(types=["mention"], limit=10, max_id="m")
    assert transport.requests[0].headers["Idempotency-Key"] == "key-1"
    assert transport.requests[1].method == "DELETE"
    with pytest.raises(ValueError):
        connector.post_status(status="", media_ids=None)
    with pytest.raises(ValueError):
        connector.post_status(status="x", visibility="bogus")
    with pytest.raises(ValueError):
        connector.delete_status("")
    with pytest.raises(ValueError):
        connector.favourite_status("")
    with pytest.raises(ValueError):
        connector.reblog_status("")
    with pytest.raises(ValueError):
        connector.follow_account("")
    with pytest.raises(ValueError):
        connector.unfollow_account("")


# MARK: - Bluesky


def _bluesky() -> tuple[BlueskyToolSet, MockTransport]:
    transport = MockTransport()
    return (
        BlueskyToolSet(access_jwt="jwt", did="did:plc:1", transport=transport),
        transport,
    )


def test_bluesky_requires_jwt_and_did() -> None:
    with pytest.raises(ValueError):
        BlueskyToolSet(access_jwt="", did="d")
    with pytest.raises(ValueError):
        BlueskyToolSet(access_jwt="j", did="")


def test_bluesky_reads() -> None:
    connector, transport = _bluesky()
    for _ in range(6):
        transport.enqueue(json_response({"data": {}}))
    connector.get_profile("alice.bsky.social")
    connector.get_timeline(limit=10, cursor="c")
    connector.get_author_feed("alice.bsky.social", limit=10, cursor="c")
    connector.search_posts("claude", limit=10, cursor="c", author="alice.bsky.social")
    connector.get_followers("alice.bsky.social", limit=10, cursor="c")
    connector.get_follows("alice.bsky.social", limit=10, cursor="c")
    assert transport.requests[0].headers["Authorization"] == "Bearer jwt"
    assert "/xrpc/app.bsky.actor.getProfile" in transport.requests[0].url
    with pytest.raises(ValueError):
        connector.get_profile("")
    with pytest.raises(ValueError):
        connector.get_author_feed("")
    with pytest.raises(ValueError):
        connector.search_posts("")
    with pytest.raises(ValueError):
        connector.get_followers("")
    with pytest.raises(ValueError):
        connector.get_follows("")


def test_bluesky_writes() -> None:
    connector, transport = _bluesky()
    for _ in range(5):
        transport.enqueue(json_response({"uri": "at://1", "cid": "c"}))
    connector.create_post(text="hello", langs=["en"])
    connector.delete_post("rkey1")
    connector.like(uri="at://x", cid="cid1")
    connector.repost(uri="at://x", cid="cid1")
    connector.follow("did:plc:2")
    body = transport.requests[0].json_body
    assert body["repo"] == "did:plc:1"
    assert body["collection"] == "app.bsky.feed.post"
    assert body["record"]["text"] == "hello"
    with pytest.raises(ValueError):
        connector.create_post(text="")
    with pytest.raises(ValueError):
        connector.delete_post("")
    with pytest.raises(ValueError):
        connector.like(uri="", cid="c")
    with pytest.raises(ValueError):
        connector.like(uri="u", cid="")
    with pytest.raises(ValueError):
        connector.repost(uri="", cid="c")
    with pytest.raises(ValueError):
        connector.follow("")


# MARK: - Threads


def _threads() -> tuple[ThreadsToolSet, MockTransport]:
    transport = MockTransport()
    return ThreadsToolSet(access_token="t", transport=transport), transport


def test_threads_requires_token() -> None:
    with pytest.raises(ValueError):
        ThreadsToolSet(access_token="")


def test_threads_endpoints() -> None:
    connector, transport = _threads()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.get_me(fields=["id", "username"])
    connector.list_threads(
        "u1",
        fields=["id"],
        limit=10,
        after="cur",
        since="2026-01-01",
        until="2026-02-01",
    )
    connector.get_thread("m1", fields=["id"])
    connector.create_media_container(
        "u1",
        media_type="IMAGE",
        text="cap",
        image_url="https://x.png",
    )
    connector.create_media_container(
        "u1",
        media_type="VIDEO",
        video_url="https://x.mp4",
    )
    connector.create_media_container(
        "u1",
        media_type="CAROUSEL",
        children=["c1", "c2"],
    )
    connector.publish_media(user_id="u1", creation_id="cr1")
    connector.get_container_status("cr1")
    connector.list_replies("m1", fields=["id"], reverse=True)
    connector.hide_reply("r1", hide=True)
    assert transport.requests[0].params["access_token"] == "t"
    assert "/v1.0/me" in transport.requests[0].url
    with pytest.raises(ValueError):
        connector.list_threads("")
    with pytest.raises(ValueError):
        connector.get_thread("")
    with pytest.raises(ValueError):
        connector.create_media_container("", media_type="TEXT")
    with pytest.raises(ValueError):
        connector.create_media_container("u", media_type="bogus")
    with pytest.raises(ValueError):
        connector.create_media_container("u", media_type="IMAGE")
    with pytest.raises(ValueError):
        connector.create_media_container("u", media_type="VIDEO")
    with pytest.raises(ValueError):
        connector.create_media_container("u", media_type="CAROUSEL")
    with pytest.raises(ValueError):
        connector.publish_media(user_id="", creation_id="c")
    with pytest.raises(ValueError):
        connector.publish_media(user_id="u", creation_id="")
    with pytest.raises(ValueError):
        connector.get_container_status("")
    with pytest.raises(ValueError):
        connector.list_replies("")
    with pytest.raises(ValueError):
        connector.hide_reply("")


def test_threads_insights() -> None:
    connector, transport = _threads()
    for _ in range(2):
        transport.enqueue(json_response({"data": []}))
    connector.get_media_insights("m1", metric=["views", "likes"])
    connector.get_user_insights(
        "u1",
        metric=["views"],
        since="1712991600",
        until="1715583600",
    )
    assert transport.requests[0].params["metric"] == "views,likes"
    with pytest.raises(ValueError):
        connector.get_media_insights("", metric=["x"])
    with pytest.raises(ValueError):
        connector.get_media_insights("m", metric=[])
    with pytest.raises(ValueError):
        connector.get_user_insights("", metric=["x"])
    with pytest.raises(ValueError):
        connector.get_user_insights("u", metric=[])


# MARK: - Buffer


def _buffer() -> tuple[BufferToolSet, MockTransport]:
    transport = MockTransport()
    return BufferToolSet(api_key="t", transport=transport), transport


def test_buffer_requires_token() -> None:
    with pytest.raises(ValueError):
        BufferToolSet(api_key="")


def test_buffer_profiles_and_updates() -> None:
    connector, transport = _buffer()
    for _ in range(11):
        transport.enqueue(json_response({"updates": []}))
    connector.get_user()
    connector.list_profiles()
    connector.get_profile("p1")
    connector.list_pending_updates("p1", first=10)
    connector.list_sent_updates("p1", first=10)
    connector.get_update("u1")
    connector.create_update(
        profile_ids=["p1", "p2"],
        text="hello",
        media={"link": "https://x"},
        scheduled_at=1700000000,
        shorten=False,
        top=True,
    )
    connector.update_update("u1", text="new", scheduled_at=1700000100)
    connector.share_update_now("u1")
    connector.destroy_update("u1")
    connector.get_update_interactions("u1", event="retweet", first=5)
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[0].url == "https://api.buffer.com"
    create_input = transport.requests[6].json_body["variables"]["input"]
    assert create_input["channelIds"] == ["p1", "p2"]
    with pytest.raises(ValueError):
        connector.get_profile("")
    with pytest.raises(ValueError):
        connector.list_pending_updates("")
    with pytest.raises(ValueError):
        connector.list_sent_updates("")
    with pytest.raises(ValueError):
        connector.get_update("")
    with pytest.raises(ValueError):
        connector.create_update(profile_ids=[], text="x")
    with pytest.raises(ValueError):
        connector.create_update(profile_ids=["p"], text="")
    with pytest.raises(ValueError):
        connector.update_update("")
    with pytest.raises(ValueError):
        connector.update_update("u1")
    with pytest.raises(ValueError):
        connector.share_update_now("")
    with pytest.raises(ValueError):
        connector.destroy_update("")
    with pytest.raises(ValueError):
        connector.get_update_interactions("")


# MARK: - Agent-ready tests


# MARK: - Reddit agent-ready


def test_reddit_list_subreddit_posts_summary_default() -> None:
    connector, transport = _reddit()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "after": "t3_next",
                    "children": [
                        {
                            "data": {
                                "id": "abc",
                                "name": "t3_abc",
                                "title": "First post",
                                "author": "alice",
                                "subreddit": "python",
                                "created_utc": 1700000000.0,
                                "score": 42,
                                "num_comments": 7,
                                "permalink": "/r/python/comments/abc/first_post/",
                                "selftext": "Hello world",
                            }
                        }
                    ],
                }
            }
        )
    )
    result = connector.list_subreddit_posts("python")
    summary = result["posts"][0]
    assert summary["post_ref"] == "post_1"
    assert summary["title"] == "First post"
    assert summary["author"] == "alice"
    assert summary["score"] == 42
    assert "thing_id" not in summary
    assert result["after"] == "t3_next"


def test_reddit_list_subreddit_posts_include_ids() -> None:
    connector, transport = _reddit()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "abc",
                                "name": "t3_abc",
                                "title": "x",
                                "author": "a",
                                "subreddit": "python",
                                "created_utc": 0,
                                "score": 0,
                                "num_comments": 0,
                                "permalink": "/r/python/comments/abc/",
                                "selftext": "",
                            }
                        }
                    ],
                }
            }
        )
    )
    result = connector.list_subreddit_posts("python", include_ids=True)
    assert result["posts"][0]["thing_id"] == "t3_abc"
    assert result["posts"][0]["post_id"] == "abc"


def test_reddit_search_summary_default() -> None:
    connector, transport = _reddit()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "x1",
                                "name": "t3_x1",
                                "title": "Match",
                                "author": "u",
                                "subreddit": "python",
                                "created_utc": 0,
                                "score": 1,
                                "num_comments": 0,
                                "permalink": "",
                                "selftext": "",
                            }
                        }
                    ]
                }
            }
        )
    )
    result = connector.search("hello")
    assert result["posts"][0]["title"] == "Match"
    assert "thing_id" not in result["posts"][0]


def test_reddit_tolerant_inputs() -> None:
    connector, transport = _reddit()
    for _ in range(4):
        transport.enqueue(json_response({"json": {"errors": []}}))
    post_dict = {
        "post_ref": "post_1",
        "title": "x",
        "thing_id": "t3_dictid",
    }
    connector.vote(thing=post_dict, direction=1)
    connector.save(post_dict)
    connector.unsave(post_dict)
    connector.delete_thing(post_dict)
    for request in transport.requests:
        assert b"id=t3_dictid" in (request.data or b"")


def test_reddit_destructive_tags() -> None:
    connector = RedditToolSet(access_token="t", user_agent="ua")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_thing") for name in destructive)


# MARK: - Pinterest agent-ready


def test_pinterest_list_boards_summary_default() -> None:
    connector, transport = _pinterest()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "board-1",
                        "name": "Inspiration",
                        "description": "ideas",
                        "privacy": "PUBLIC",
                        "owner": {"username": "creator"},
                        "pin_count": 5,
                        "follower_count": 100,
                        "created_at": "2026-04-01T10:00:00Z",
                    }
                ],
                "bookmark": "bm-1",
            }
        )
    )
    result = connector.list_boards()
    summary = result["boards"][0]
    assert summary["board_ref"] == "board_1"
    assert summary["name"] == "Inspiration"
    assert summary["owner"] == "creator"
    assert "board_id" not in summary
    assert result["bookmark"] == "bm-1"


def test_pinterest_list_boards_include_ids() -> None:
    connector, transport = _pinterest()
    transport.enqueue(json_response({"items": [{"id": "b1", "name": "x"}]}))
    result = connector.list_boards(include_ids=True)
    assert result["boards"][0]["board_id"] == "b1"


def test_pinterest_list_pins_summary_default() -> None:
    connector, transport = _pinterest()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "pin-1",
                        "title": "Sunset",
                        "description": "warm tones",
                        "alt_text": "",
                        "link": "https://example.com",
                        "created_at": "2026-04-01T10:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_pins()
    summary = result["pins"][0]
    assert summary["pin_ref"] == "pin_1"
    assert summary["title"] == "Sunset"
    assert summary["url"] == "https://www.pinterest.com/pin/pin-1/"
    assert "pin_id" not in summary


def test_pinterest_delete_pin_tolerant_input() -> None:
    connector, transport = _pinterest()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.delete_pin("pin-1")
    connector.delete_pin({"pin_id": "pin-2"})
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[1].method == "DELETE"


def test_pinterest_destructive_tags() -> None:
    connector = PinterestToolSet(access_token="t")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_board") for name in destructive)
    assert any(name.endswith("delete_pin") for name in destructive)


# MARK: - Mastodon agent-ready


def test_mastodon_home_timeline_summary_default() -> None:
    connector, transport = _mastodon()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "s1",
                    "account": {"acct": "alice@m.social", "display_name": "Alice"},
                    "content": "<p>hello</p>",
                    "created_at": "2026-04-01T11:00:00Z",
                    "spoiler_text": "",
                    "visibility": "public",
                    "favourites_count": 5,
                    "reblogs_count": 2,
                    "replies_count": 1,
                    "url": "https://m.social/@alice/s1",
                }
            ]
        )
    )
    result = connector.home_timeline()
    summary = result["statuses"][0]
    assert summary["status_ref"] == "status_1"
    assert summary["author"] == "alice@m.social"
    assert summary["url"] == "https://m.social/@alice/s1"
    assert "status_id" not in summary


def test_mastodon_home_timeline_include_ids() -> None:
    connector, transport = _mastodon()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "s2",
                    "account": {"acct": "bob@m.social"},
                    "content": "hi",
                    "created_at": "",
                    "visibility": "public",
                }
            ]
        )
    )
    result = connector.home_timeline(include_ids=True)
    assert result["statuses"][0]["status_id"] == "s2"


def test_mastodon_delete_status_tolerant_input() -> None:
    connector, transport = _mastodon()
    transport.enqueue(json_response({"id": "s1"}))
    transport.enqueue(json_response({"id": "s2"}))
    connector.delete_status("s1")
    connector.delete_status({"status_id": "s2"})
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[1].method == "DELETE"


def test_mastodon_favourite_status_tolerant_input() -> None:
    connector, transport = _mastodon()
    transport.enqueue(json_response({"id": "s1"}))
    transport.enqueue(json_response({"id": "s2"}))
    connector.favourite_status("s1")
    connector.favourite_status({"id": "s2"})
    assert transport.requests[1].url.endswith("/api/v1/statuses/s2/favourite")


def test_mastodon_destructive_tags() -> None:
    connector = MastodonToolSet(access_token="t", instance_url="https://m.social")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_status") for name in destructive)


# MARK: - Bluesky agent-ready


def test_bluesky_get_timeline_summary_default() -> None:
    connector, transport = _bluesky()
    transport.enqueue(
        json_response(
            {
                "feed": [
                    {
                        "post": {
                            "uri": "at://did:plc:1/app.bsky.feed.post/3rkey",
                            "cid": "cid1",
                            "author": {
                                "did": "did:plc:1",
                                "handle": "alice.bsky.social",
                                "displayName": "Alice",
                            },
                            "record": {
                                "text": "hi from bluesky",
                                "createdAt": "2026-04-01T12:00:00Z",
                            },
                            "likeCount": 7,
                            "repostCount": 1,
                            "replyCount": 0,
                        }
                    }
                ],
                "cursor": "cur-1",
            }
        )
    )
    result = connector.get_timeline()
    summary = result["posts"][0]
    assert summary["post_ref"] == "post_1"
    assert summary["author"] == "alice.bsky.social"
    assert summary["text"] == "hi from bluesky"
    assert summary["like_count"] == 7
    assert summary["url"] == "https://bsky.app/profile/alice.bsky.social/post/3rkey"
    assert "uri" not in summary
    assert "cid" not in summary
    assert result["cursor"] == "cur-1"


def test_bluesky_search_posts_summary_default() -> None:
    connector, transport = _bluesky()
    transport.enqueue(
        json_response(
            {
                "posts": [
                    {
                        "uri": "at://did:plc:2/app.bsky.feed.post/sk2",
                        "cid": "cid2",
                        "author": {
                            "did": "did:plc:2",
                            "handle": "bob.bsky.social",
                        },
                        "record": {"text": "hello", "createdAt": "2026-04-01"},
                        "likeCount": 0,
                        "repostCount": 0,
                        "replyCount": 0,
                    }
                ]
            }
        )
    )
    result = connector.search_posts("hello")
    assert result["posts"][0]["author"] == "bob.bsky.social"
    assert "uri" not in result["posts"][0]


def test_bluesky_search_posts_include_ids() -> None:
    connector, transport = _bluesky()
    transport.enqueue(
        json_response(
            {
                "posts": [
                    {
                        "uri": "at://did:plc:2/app.bsky.feed.post/sk2",
                        "cid": "cid2",
                        "author": {"did": "did:plc:2", "handle": "b"},
                        "record": {"text": "h", "createdAt": ""},
                    }
                ]
            }
        )
    )
    result = connector.search_posts("h", include_ids=True)
    assert result["posts"][0]["uri"] == "at://did:plc:2/app.bsky.feed.post/sk2"
    assert result["posts"][0]["cid"] == "cid2"
    assert result["posts"][0]["rkey"] == "sk2"


def test_bluesky_delete_post_tolerant_input() -> None:
    connector, transport = _bluesky()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    # raw rkey
    connector.delete_post("rkey-1")
    # full at:// URI
    connector.delete_post("at://did:plc:1/app.bsky.feed.post/rkey-2")
    # post dict from feed
    connector.delete_post({"post": {"uri": "at://did:plc:1/app.bsky.feed.post/rkey-3"}})
    assert transport.requests[0].json_body["rkey"] == "rkey-1"
    assert transport.requests[1].json_body["rkey"] == "rkey-2"
    assert transport.requests[2].json_body["rkey"] == "rkey-3"


def test_bluesky_like_tolerant_input() -> None:
    connector, transport = _bluesky()
    transport.enqueue(json_response({"uri": "at://1", "cid": "c"}))
    transport.enqueue(json_response({"uri": "at://2", "cid": "c"}))
    post_dict = {
        "post": {
            "uri": "at://did:plc:1/app.bsky.feed.post/aaa",
            "cid": "cidA",
        }
    }
    connector.like(post_dict)
    connector.like(uri="at://b", cid="cidB")
    assert transport.requests[0].json_body["record"]["subject"] == {
        "uri": "at://did:plc:1/app.bsky.feed.post/aaa",
        "cid": "cidA",
    }
    assert transport.requests[1].json_body["record"]["subject"] == {
        "uri": "at://b",
        "cid": "cidB",
    }


def test_bluesky_repost_tolerant_input() -> None:
    connector, transport = _bluesky()
    transport.enqueue(json_response({"uri": "at://1", "cid": "c"}))
    connector.repost({"uri": "at://x", "cid": "cidX"})
    assert transport.requests[0].json_body["record"]["subject"]["uri"] == "at://x"


def test_bluesky_destructive_tags() -> None:
    connector = BlueskyToolSet(access_jwt="j", did="did:plc:1")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_post") for name in destructive)


# MARK: - Threads agent-ready


def test_threads_list_threads_summary_default() -> None:
    connector, transport = _threads()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "th-1",
                        "username": "alice",
                        "text": "first thread",
                        "media_type": "TEXT_POST",
                        "timestamp": "2026-04-01T13:00:00Z",
                        "permalink": "https://threads.net/@alice/post/th-1",
                    }
                ]
            }
        )
    )
    result = connector.list_threads("user-1")
    summary = result["posts"][0]
    assert summary["post_ref"] == "post_1"
    assert summary["author"] == "alice"
    assert summary["text"] == "first thread"
    assert "post_id" not in summary


def test_threads_list_threads_include_ids() -> None:
    connector, transport = _threads()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "th-2",
                        "username": "x",
                        "text": "x",
                        "media_type": "TEXT_POST",
                        "timestamp": "",
                        "permalink": "",
                    }
                ]
            }
        )
    )
    result = connector.list_threads("user-1", include_ids=True)
    assert result["posts"][0]["post_id"] == "th-2"


def test_threads_list_replies_summary_default() -> None:
    connector, transport = _threads()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "r1",
                        "username": "fan",
                        "text": "nice",
                        "timestamp": "2026-04-01T13:30:00Z",
                        "permalink": "",
                    }
                ]
            }
        )
    )
    result = connector.list_replies("th-1")
    summary = result["replies"][0]
    assert summary["reply_ref"] == "reply_1"
    assert summary["author"] == "fan"
    assert "reply_id" not in summary


def test_threads_no_destructive_tags() -> None:
    connector = ThreadsToolSet(access_token="t")
    destructive = _destructive_tool_names(connector)
    # Threads connector doesn't expose destructive tools yet
    # (hide_reply is reversible, no delete endpoint surfaced).
    assert destructive == set()


# MARK: - Buffer agent-ready


def test_buffer_list_pending_updates_summary_default() -> None:
    connector, transport = _buffer()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "posts": {
                        "edges": [
                            {
                                "node": {
                                    "id": "up-1",
                                    "text": "Hello world",
                                    "status": "pending",
                                    "scheduledAt": 1700000000,
                                    "sentAt": 0,
                                    "service": "twitter",
                                    "channelId": "prof-1",
                                    "author": {"name": "Alice"},
                                },
                                "cursor": "c1",
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": "c1"},
                    }
                }
            }
        )
    )
    result = connector.list_pending_updates("prof-1")
    summary = result["updates"][0]
    assert summary["update_ref"] == "update_1"
    assert summary["text"] == "Hello world"
    assert summary["service"] == "twitter"
    assert "update_id" not in summary
    assert "profile_id" not in summary


def test_buffer_list_pending_updates_include_ids() -> None:
    connector, transport = _buffer()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "posts": {
                        "edges": [
                            {
                                "node": {
                                    "id": "up-2",
                                    "text": "x",
                                    "status": "pending",
                                    "scheduledAt": 0,
                                    "sentAt": 0,
                                    "service": "twitter",
                                    "channelId": "prof-1",
                                    "author": {"name": ""},
                                },
                                "cursor": "c1",
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": "c1"},
                    }
                }
            }
        )
    )
    result = connector.list_pending_updates("prof-1", include_ids=True)
    assert result["updates"][0]["update_id"] == "up-2"
    assert result["updates"][0]["profile_id"] == "prof-1"


def test_buffer_destroy_update_tolerant_input() -> None:
    connector, transport = _buffer()
    transport.enqueue(json_response({"data": {"deletePost": {"deletedId": "up-1"}}}))
    transport.enqueue(json_response({"data": {"deletePost": {"deletedId": "up-2"}}}))
    connector.destroy_update("up-1")
    connector.destroy_update({"update_id": "up-2"})
    assert "deletePost" in transport.requests[0].json_body["query"]
    assert transport.requests[0].json_body["variables"]["id"] == "up-1"
    assert transport.requests[1].json_body["variables"]["id"] == "up-2"


def test_buffer_share_update_now_tolerant_input() -> None:
    connector, transport = _buffer()
    transport.enqueue(json_response({"data": {"sharePostNow": {"post": {"id": "up-1"}}}}))
    transport.enqueue(json_response({"data": {"sharePostNow": {"post": {"id": "up-2"}}}}))
    connector.share_update_now("up-1")
    connector.share_update_now({"id": "up-2"})
    assert "sharePostNow" in transport.requests[0].json_body["query"]
    assert transport.requests[0].json_body["variables"]["id"] == "up-1"
    assert transport.requests[1].json_body["variables"]["id"] == "up-2"


def test_buffer_destructive_tags() -> None:
    connector = BufferToolSet(api_key="t")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("destroy_update") for name in destructive)
