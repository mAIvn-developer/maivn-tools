# pyright: strict
from __future__ import annotations

import pytest
from maivn import Agent

from maivn_tools.connectors.instagram import InstagramToolSet
from maivn_tools.connectors.linkedin import LinkedInToolSet
from maivn_tools.connectors.meta import MetaToolSet
from maivn_tools.connectors.tiktok import TikTokToolSet
from maivn_tools.connectors.x import XToolSet
from maivn_tools.connectors.youtube import YouTubeToolSet
from maivn_tools.testing import MockTransport, json_response


def _destructive_tool_names(toolset_instance: object) -> set[str]:
    """Return names of tools tagged ``destructive`` on a toolset.

    Uses the Agent surface to query exclude_tags behaviour: a tool is
    destructive iff it disappears when ``exclude_tags=["destructive"]``
    is applied.
    """
    full = Agent(name="t", description="x", system_prompt="x", api_key="mock")
    full.add_toolset(toolset_instance)
    filtered = Agent(name="t2", description="x", system_prompt="x", api_key="mock")
    filtered.add_toolset(toolset_instance, exclude_tags=["destructive"])
    full_names = {tool.name for tool in full.list_tools()}
    safe_names = {tool.name for tool in filtered.list_tools()}
    return full_names - safe_names


# MARK: - X (Twitter)


def _x() -> tuple[XToolSet, MockTransport]:
    transport = MockTransport()
    return XToolSet(bearer_token="bt", transport=transport), transport


def test_x_requires_token() -> None:
    with pytest.raises(ValueError):
        XToolSet(bearer_token="")


def test_x_users() -> None:
    connector, transport = _x()
    for _ in range(4):
        transport.enqueue(json_response({"data": {}}))
    connector.get_me(user_fields=["username", "name"])
    connector.get_user(user_id="123", user_fields=["username"])
    connector.get_user(username="elonmusk")
    connector.get_user_by_ids(["1", "2"])
    assert transport.requests[0].headers["Authorization"] == "Bearer bt"
    assert transport.requests[0].params["user.fields"] == "username,name"
    assert transport.requests[2].url.endswith("/2/users/by/username/elonmusk")
    with pytest.raises(ValueError):
        connector.get_user()
    with pytest.raises(ValueError):
        connector.get_user_by_ids([])


def test_x_tweets_read() -> None:
    connector, transport = _x()
    for _ in range(5):
        transport.enqueue(json_response({"data": []}))
    connector.get_tweet("1", tweet_fields=["created_at"], expansions=["author_id"])
    connector.get_tweets(["1", "2"])
    connector.search_recent_tweets(
        "claude",
        max_results=50,
        next_token="nt",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-02-01T00:00:00Z",
        tweet_fields=["lang"],
        expansions=["author_id"],
    )
    connector.get_user_tweets(
        "123",
        max_results=50,
        pagination_token="pt",
        exclude=["replies"],
        tweet_fields=["created_at"],
    )
    connector.get_user_mentions("123", max_results=10, pagination_token="pt")
    with pytest.raises(ValueError):
        connector.get_tweet("")
    with pytest.raises(ValueError):
        connector.get_tweets([])
    with pytest.raises(ValueError):
        connector.search_recent_tweets("")
    with pytest.raises(ValueError):
        connector.search_recent_tweets("x", max_results=5)
    with pytest.raises(ValueError):
        connector.get_user_tweets("")
    with pytest.raises(ValueError):
        connector.get_user_mentions("")


def test_x_post_and_delete() -> None:
    connector, transport = _x()
    transport.enqueue(json_response({"data": {"id": "1"}}))
    transport.enqueue(json_response({"data": {"deleted": True}}))
    connector.post_tweet(
        "hello",
        reply_to_tweet_id="111",
        quote_tweet_id="222",
        media_ids=["m1"],
        reply_settings="mentionedUsers",
        poll={"options": ["a", "b"], "duration_minutes": 60},
    )
    connector.delete_tweet("1")
    body = transport.requests[0].json_body
    assert body["text"] == "hello"
    assert body["reply"]["in_reply_to_tweet_id"] == "111"
    assert body["media"] == {"media_ids": ["m1"]}
    assert transport.requests[1].method == "DELETE"
    with pytest.raises(ValueError):
        connector.post_tweet("", media_ids=None)
    with pytest.raises(ValueError):
        connector.delete_tweet("")


def test_x_engagement() -> None:
    connector, transport = _x()
    for _ in range(8):
        transport.enqueue(json_response({"data": {}}))
    connector.like_tweet(user_id="u", tweet=" t")
    connector.unlike_tweet(user_id="u", tweet="t")
    connector.retweet(user_id="u", tweet="t")
    connector.unretweet(user_id="u", tweet="t")
    connector.follow_user(user_id="u", target_user_id="v")
    connector.unfollow_user(user_id="u", target_user_id="v")
    connector.get_followers("u", max_results=25, pagination_token="pt", include_metadata=False)
    connector.get_following("u", max_results=25, pagination_token="pt", include_metadata=False)
    assert transport.requests[1].method == "DELETE"
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.like_tweet(user_id="", tweet="t")
    with pytest.raises(ValueError):
        connector.unlike_tweet(user_id="u", tweet="")
    with pytest.raises(ValueError):
        connector.retweet(user_id="", tweet="t")
    with pytest.raises(ValueError):
        connector.unretweet(user_id="u", tweet="")
    with pytest.raises(ValueError):
        connector.follow_user(user_id="", target_user_id="v")
    with pytest.raises(ValueError):
        connector.unfollow_user(user_id="u", target_user_id="")
    with pytest.raises(ValueError):
        connector.get_followers("")
    with pytest.raises(ValueError):
        connector.get_following("")


def test_x_lists_and_dm() -> None:
    connector, transport = _x()
    for _ in range(4):
        transport.enqueue(json_response({"data": {}}))
    connector.list_owned_lists("u")
    connector.create_list(name="L", description="d", private=True)
    connector.delete_list("L1")
    connector.send_dm(participant_id="p", text="hi")
    with pytest.raises(ValueError):
        connector.list_owned_lists("")
    with pytest.raises(ValueError):
        connector.create_list(name="")
    with pytest.raises(ValueError):
        connector.delete_list("")
    with pytest.raises(ValueError):
        connector.send_dm(participant_id="p", text="")


# MARK: - Meta (Facebook Graph)


def _meta() -> tuple[MetaToolSet, MockTransport]:
    transport = MockTransport()
    return MetaToolSet(access_token="t", transport=transport), transport


def test_meta_requires_token() -> None:
    with pytest.raises(ValueError):
        MetaToolSet(access_token="")


def test_meta_endpoints() -> None:
    connector, transport = _meta()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.get_me(fields=["id", "name"])
    connector.list_accounts()
    connector.get_page("page-1", fields=["name"])
    connector.list_page_posts("page-1", limit=5, after="cursor", fields=["message"])
    connector.publish_page_post(
        "page-1",
        message="hi",
        link="https://x",
        scheduled_publish_time=1234567890,
    )
    connector.delete_post("post-1")
    connector.list_post_comments("post-1", limit=5, after="cur")
    connector.reply_to_comment("comment-1", message="thanks")
    connector.delete_comment("comment-1")
    connector.get_page_insights(
        "page-1",
        metric=["page_impressions"],
        period="week",
        since="2026-01-01",
        until="2026-02-01",
    )
    assert transport.requests[0].params["access_token"] == "t"
    assert "/v24.0/me" in transport.requests[0].url
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_page("")
    with pytest.raises(ValueError):
        connector.list_page_posts("")
    with pytest.raises(ValueError):
        connector.publish_page_post("page-1")
    with pytest.raises(ValueError):
        connector.publish_page_post("")
    with pytest.raises(ValueError):
        connector.delete_post("")
    with pytest.raises(ValueError):
        connector.list_post_comments("")
    with pytest.raises(ValueError):
        connector.reply_to_comment("", message="x")
    with pytest.raises(ValueError):
        connector.reply_to_comment("c", message="")
    with pytest.raises(ValueError):
        connector.delete_comment("")
    with pytest.raises(ValueError):
        connector.get_page_insights("", metric=[])
    with pytest.raises(ValueError):
        connector.get_page_insights("p", metric=[])


def test_meta_post_insights() -> None:
    connector, transport = _meta()
    transport.enqueue(json_response({}))
    connector.get_post_insights("post-1", metric=["post_impressions"])
    with pytest.raises(ValueError):
        connector.get_post_insights("", metric=["x"])


# MARK: - Instagram


def _instagram() -> tuple[InstagramToolSet, MockTransport]:
    transport = MockTransport()
    return InstagramToolSet(access_token="t", transport=transport), transport


def test_instagram_requires_token() -> None:
    with pytest.raises(ValueError):
        InstagramToolSet(access_token="")


def test_instagram_endpoints() -> None:
    connector, transport = _instagram()
    for _ in range(14):
        transport.enqueue(json_response({"data": []}))
    connector.get_account("ig-1", fields=["username", "biography"])
    connector.list_media("ig-1", limit=5, after="cur", fields=["caption"])
    connector.get_media("m1", fields=["caption"])
    connector.create_media_container(
        "ig-1",
        image_url="https://x.png",
        caption="hi",
        media_type="IMAGE",
        is_carousel_item=False,
    )
    connector.create_media_container("ig-1", children=["c1", "c2"], media_type="CAROUSEL")
    connector.publish_media("ig-1", creation_id="cr-1")
    connector.get_container_status("cr-1")
    connector.list_comments("m1", limit=10)
    connector.reply_to_comment("c1", message="thanks")
    connector.delete_comment("c1")
    connector.hide_comment("c1", hide=False)
    connector.get_media_insights("m1", metric=["impressions"])
    connector.get_account_insights(
        "ig-1",
        metric=["reach"],
        period="day",
        since="2026-01-01",
        until="2026-02-01",
    )
    connector.list_stories("ig-1")
    assert transport.requests[0].params["access_token"] == "t"
    with pytest.raises(ValueError):
        connector.get_account("")
    with pytest.raises(ValueError):
        connector.list_media("")
    with pytest.raises(ValueError):
        connector.get_media("")
    with pytest.raises(ValueError):
        connector.create_media_container("")
    with pytest.raises(ValueError):
        connector.create_media_container("ig-1")
    with pytest.raises(ValueError):
        connector.publish_media("ig-1", creation_id="")
    with pytest.raises(ValueError):
        connector.get_container_status("")
    with pytest.raises(ValueError):
        connector.list_comments("")
    with pytest.raises(ValueError):
        connector.reply_to_comment("", message="x")
    with pytest.raises(ValueError):
        connector.reply_to_comment("c", message="")
    with pytest.raises(ValueError):
        connector.delete_comment("")
    with pytest.raises(ValueError):
        connector.hide_comment("")
    with pytest.raises(ValueError):
        connector.get_media_insights("", metric=["x"])
    with pytest.raises(ValueError):
        connector.get_media_insights("m", metric=[])
    with pytest.raises(ValueError):
        connector.get_account_insights("", metric=["x"])
    with pytest.raises(ValueError):
        connector.list_stories("")


# MARK: - LinkedIn


def _linkedin() -> tuple[LinkedInToolSet, MockTransport]:
    transport = MockTransport()
    return LinkedInToolSet(access_token="t", transport=transport), transport


def test_linkedin_requires_token() -> None:
    with pytest.raises(ValueError):
        LinkedInToolSet(access_token="")


def test_linkedin_userinfo_and_me() -> None:
    connector, transport = _linkedin()
    transport.enqueue(json_response({"sub": "abc"}))
    transport.enqueue(json_response({"id": "abc"}))
    connector.get_userinfo()
    connector.get_me(projection="(id)")
    assert transport.requests[0].url.endswith("/v2/userinfo")
    assert transport.requests[0].headers["LinkedIn-Version"] == "202605"


def test_linkedin_posts_lifecycle() -> None:
    connector, transport = _linkedin()
    for _ in range(7):
        transport.enqueue(json_response({"id": "urn:li:share:1"}))
    connector.create_post(
        author_urn="urn:li:person:1",
        commentary="hello world",
        visibility="CONNECTIONS",
        media=[{"id": "urn:li:digitalmediaAsset:1"}],
    )
    connector.create_post(
        author_urn="urn:li:person:1",
        commentary="multi",
        media=[
            {"id": "urn:li:digitalmediaAsset:1"},
            {"id": "urn:li:digitalmediaAsset:2"},
        ],
    )
    connector.get_post("urn:li:share:1")
    connector.delete_post("urn:li:share:1")
    connector.list_posts_for_author(author_urn="urn:li:person:1", count=5, start=0)
    connector.create_comment(
        post_urn="urn:li:share:1",
        actor_urn="urn:li:person:1",
        message="nice",
    )
    connector.list_comments("urn:li:share:1", count=10)
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.create_post(author_urn="", commentary="x")
    with pytest.raises(ValueError):
        connector.create_post(author_urn="x", commentary="x", visibility="bogus")
    with pytest.raises(ValueError):
        connector.get_post("")
    with pytest.raises(ValueError):
        connector.delete_post("")
    with pytest.raises(ValueError):
        connector.list_posts_for_author(author_urn="")
    with pytest.raises(ValueError):
        connector.create_comment(post_urn="", actor_urn="a", message="m")
    with pytest.raises(ValueError):
        connector.list_comments("")


def test_linkedin_orgs() -> None:
    connector, transport = _linkedin()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.get_organization("123")
    connector.list_organization_acls()
    with pytest.raises(ValueError):
        connector.get_organization("")


# MARK: - TikTok


def _tiktok() -> tuple[TikTokToolSet, MockTransport]:
    transport = MockTransport()
    return TikTokToolSet(access_token="t", transport=transport), transport


def test_tiktok_requires_token() -> None:
    with pytest.raises(ValueError):
        TikTokToolSet(access_token="")


def test_tiktok_endpoints() -> None:
    connector, transport = _tiktok()
    for _ in range(8):
        transport.enqueue(json_response({"data": {}}))
    connector.get_user_info(fields=["open_id", "username"])
    connector.list_videos(
        fields=["id", "title"],
        cursor=0,
        max_count=10,
        include_metadata=False,
    )
    connector.query_videos(video_ids=["v1"], fields=["id"])
    connector.get_creator_info()
    connector.init_video_upload(
        post_info={"title": "t", "privacy_level": "PUBLIC_TO_EVERYONE"},
        source_info={"source": "PULL_FROM_URL", "video_url": "https://x.mp4"},
    )
    connector.init_inbox_upload(
        source_info={"source": "PULL_FROM_URL", "video_url": "https://x.mp4"},
    )
    connector.get_publish_status("pub-1")
    connector.init_photo_publish(
        post_info={"title": "p", "privacy_level": "PUBLIC_TO_EVERYONE"},
        photo_images=["https://x.jpg"],
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[1].params["fields"] == "id,title"
    with pytest.raises(ValueError):
        connector.list_videos(fields=[], include_metadata=False)
    with pytest.raises(ValueError):
        connector.list_videos(fields=["id"], max_count=0)
    with pytest.raises(ValueError):
        connector.query_videos(video_ids=[], fields=["id"])
    with pytest.raises(ValueError):
        connector.query_videos(video_ids=["v"], fields=[])
    with pytest.raises(ValueError):
        connector.init_video_upload(post_info={}, source_info={"x": 1})
    with pytest.raises(ValueError):
        connector.init_inbox_upload(source_info={})
    with pytest.raises(ValueError):
        connector.get_publish_status("")
    with pytest.raises(ValueError):
        connector.init_photo_publish(post_info={}, photo_images=[])


# MARK: - YouTube


def _youtube() -> tuple[YouTubeToolSet, MockTransport]:
    transport = MockTransport()
    return YouTubeToolSet(token="t", transport=transport), transport


def test_youtube_channels_videos_search() -> None:
    connector, transport = _youtube()
    for _ in range(4):
        transport.enqueue(json_response({"items": []}))
    connector.list_channels(mine=True, part=["snippet"])
    connector.list_channels(id=["c1", "c2"], for_handle="@mkbhd", for_username="mkbhd")
    connector.list_videos(id=["v1", "v2"], part=["snippet", "statistics"])
    connector.search(
        q="claude",
        channel_id="UC123",
        type=["video"],
        order="date",
        max_results=10,
        page_token="pt",
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[0].params["part"] == "snippet"
    with pytest.raises(ValueError):
        connector.list_videos(id=[])


def test_youtube_playlists() -> None:
    connector, transport = _youtube()
    for _ in range(4):
        transport.enqueue(json_response({"items": []}))
    connector.list_playlists(mine=True, max_results=10, page_token="pt")
    connector.list_playlists(channel_id="UC1", id=["P1"])
    connector.list_playlist_items("P1", max_results=10, page_token="pt")
    connector.add_to_playlist(playlist_id="P1", video_id="V1", position=0)
    with pytest.raises(ValueError):
        connector.list_playlist_items("")
    with pytest.raises(ValueError):
        connector.add_to_playlist(playlist_id="", video_id="V")
    with pytest.raises(ValueError):
        connector.add_to_playlist(playlist_id="P", video_id="")


def test_youtube_video_management() -> None:
    connector, transport = _youtube()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"id": "v1"}))
    transport.enqueue(json_response({}))
    connector.delete_playlist_item("PI1")
    connector.update_video(
        video_id="v1",
        snippet={"title": "new"},
        status={"privacyStatus": "private"},
    )
    connector.delete_video("v1")
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[1].method == "PUT"
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.delete_playlist_item("")
    with pytest.raises(ValueError):
        connector.update_video(video_id="")
    with pytest.raises(ValueError):
        connector.update_video(video_id="v1")
    with pytest.raises(ValueError):
        connector.delete_video("")


def test_youtube_comments() -> None:
    connector, transport = _youtube()
    transport.enqueue(json_response({"items": []}))
    transport.enqueue(json_response({"items": []}))
    transport.enqueue(json_response({"id": "comment-1"}))
    connector.list_comment_threads(video_id="v1", max_results=5, order="relevance")
    connector.list_comment_threads(channel_id="c1", page_token="pt")
    connector.post_comment(video_id="v1", channel_id="c1", text="great video")
    with pytest.raises(ValueError):
        connector.list_comment_threads()
    with pytest.raises(ValueError):
        connector.post_comment(text="")
    with pytest.raises(ValueError):
        connector.post_comment(text="x")


# MARK: - Agent-ready pattern tests


def test_x_search_recent_tweets_summary_default() -> None:
    connector, transport = _x()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "1700000000000000001",
                        "text": "hello world",
                        "author_id": "u1",
                        "created_at": "2026-01-15T10:30:00Z",
                        "public_metrics": {
                            "like_count": 5,
                            "retweet_count": 2,
                            "reply_count": 1,
                        },
                    }
                ],
                "includes": {"users": [{"id": "u1", "username": "alice"}]},
                "meta": {"result_count": 1, "next_token": "nt-1"},
            }
        )
    )
    result = connector.search_recent_tweets("hello")
    assert "tweets" in result
    summary = result["tweets"][0]
    assert summary["tweet_ref"] == "tweet_1"
    assert summary["author"] == "alice"
    assert summary["text"] == "hello world"
    assert summary["like_count"] == 5
    assert summary["repost_count"] == 2
    assert summary["url"].endswith("/alice/status/1700000000000000001")
    assert "tweet_id" not in summary
    assert "author_id" not in summary
    assert result["next_token"] == "nt-1"


def test_x_search_recent_tweets_include_ids() -> None:
    connector, transport = _x()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "1700000000000000002",
                        "text": "hi",
                        "author_id": "u2",
                        "created_at": "2026-01-15T11:00:00Z",
                        "public_metrics": {},
                    }
                ],
                "includes": {"users": [{"id": "u2", "username": "bob"}]},
                "meta": {"result_count": 1},
            }
        )
    )
    result = connector.search_recent_tweets("hi", include_ids=True)
    summary = result["tweets"][0]
    assert summary["tweet_id"] == "1700000000000000002"
    assert summary["author_id"] == "u2"


def test_x_search_recent_tweets_raw_passthrough() -> None:
    connector, transport = _x()
    raw = {"data": [{"id": "1"}], "meta": {"result_count": 1}}
    transport.enqueue(json_response(raw))
    result = connector.search_recent_tweets("hello", include_metadata=False)
    assert result == raw


def test_x_get_user_tweets_summary_default() -> None:
    connector, transport = _x()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "100",
                        "text": "my tweet",
                        "created_at": "2026-02-01T00:00:00Z",
                        "public_metrics": {"like_count": 10, "retweet_count": 1},
                    }
                ],
                "meta": {"result_count": 1},
            }
        )
    )
    result = connector.get_user_tweets("u-1")
    summary = result["tweets"][0]
    assert summary["tweet_ref"] == "tweet_1"
    assert summary["text"] == "my tweet"
    assert summary["like_count"] == 10
    assert "tweet_id" not in summary


def test_x_get_followers_summary_default() -> None:
    connector, transport = _x()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "f1",
                        "username": "follower1",
                        "name": "Follower One",
                        "public_metrics": {
                            "followers_count": 50,
                            "following_count": 10,
                        },
                    }
                ],
                "meta": {"result_count": 1},
            }
        )
    )
    result = connector.get_followers("u1")
    summary = result["users"][0]
    assert summary["user_ref"] == "user_1"
    assert summary["handle"] == "follower1"
    assert summary["follower_count"] == 50
    assert "user_id" not in summary


def test_x_get_followers_include_ids() -> None:
    connector, transport = _x()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "f1",
                        "username": "follower1",
                        "name": "F1",
                        "public_metrics": {},
                    }
                ],
                "meta": {"result_count": 1},
            }
        )
    )
    result = connector.get_followers("u1", include_ids=True)
    assert result["users"][0]["user_id"] == "f1"


def test_x_delete_tweet_tolerant_input() -> None:
    connector, transport = _x()
    transport.enqueue(json_response({"data": {"deleted": True}}))
    transport.enqueue(json_response({"data": {"deleted": True}}))
    transport.enqueue(json_response({"data": {"deleted": True}}))
    connector.delete_tweet("999")
    connector.delete_tweet({"tweet_id": "888"})
    connector.delete_tweet({"id": "777"})
    assert transport.requests[0].url.endswith("/2/tweets/999")
    assert transport.requests[1].url.endswith("/2/tweets/888")
    assert transport.requests[2].url.endswith("/2/tweets/777")
    with pytest.raises(ValueError):
        connector.delete_tweet({"nope": "x"})


def test_x_like_tweet_tolerant_input() -> None:
    connector, transport = _x()
    transport.enqueue(json_response({"data": {"liked": True}}))
    transport.enqueue(json_response({"data": {"liked": True}}))
    connector.like_tweet(user_id="u", tweet="555")
    connector.like_tweet(user_id="u", tweet={"tweet_id": "666"})
    assert transport.requests[0].json_body == {"tweet_id": "555"}
    assert transport.requests[1].json_body == {"tweet_id": "666"}


def test_x_destructive_tags() -> None:
    connector = XToolSet(bearer_token="bt")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_tweet") for name in destructive)
    assert any(name.endswith("unlike_tweet") for name in destructive)
    assert any(name.endswith("unretweet") for name in destructive)
    assert any(name.endswith("unfollow_user") for name in destructive)
    assert any(name.endswith("delete_list") for name in destructive)


# MARK: - Meta agent-ready


def test_meta_list_page_posts_summary_default() -> None:
    connector, transport = _meta()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "page_post_1",
                        "message": "hello fb",
                        "created_time": "2026-03-01T10:00:00Z",
                        "permalink_url": "https://facebook.com/post/1",
                    }
                ],
                "paging": {"cursors": {"after": "next-cur"}},
            }
        )
    )
    result = connector.list_page_posts("page-1")
    summary = result["posts"][0]
    assert summary["post_ref"] == "post_1"
    assert summary["message"] == "hello fb"
    assert summary["permalink_url"] == "https://facebook.com/post/1"
    assert "post_id" not in summary


def test_meta_list_page_posts_include_ids() -> None:
    connector, transport = _meta()
    transport.enqueue(json_response({"data": [{"id": "p1", "message": "hi", "created_time": ""}]}))
    result = connector.list_page_posts("page-1", include_ids=True)
    assert result["posts"][0]["post_id"] == "p1"


def test_meta_delete_post_tolerant_input() -> None:
    connector, transport = _meta()
    transport.enqueue(json_response({"success": True}))
    transport.enqueue(json_response({"success": True}))
    connector.delete_post("p-1")
    connector.delete_post({"post_id": "p-2"})
    assert transport.requests[0].method == "DELETE"
    assert "/v24.0/p-1" in transport.requests[0].url
    assert "/v24.0/p-2" in transport.requests[1].url


def test_meta_list_post_comments_summary_default() -> None:
    connector, transport = _meta()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "c1",
                        "from": {"name": "Alice"},
                        "message": "great",
                        "created_time": "2026-03-01T11:00:00Z",
                        "like_count": 3,
                    }
                ]
            }
        )
    )
    result = connector.list_post_comments("post-1")
    summary = result["comments"][0]
    assert summary["comment_ref"] == "comment_1"
    assert summary["author"] == "Alice"
    assert "comment_id" not in summary


def test_meta_destructive_tags() -> None:
    connector = MetaToolSet(access_token="t")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_post") for name in destructive)
    assert any(name.endswith("delete_comment") for name in destructive)


# MARK: - Instagram agent-ready


def test_instagram_list_media_summary_default() -> None:
    connector, transport = _instagram()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "m-1",
                        "caption": "sunset",
                        "media_type": "IMAGE",
                        "permalink": "https://instagram.com/p/abc",
                        "timestamp": "2026-04-01T08:00:00Z",
                        "like_count": 100,
                        "comments_count": 5,
                    }
                ]
            }
        )
    )
    result = connector.list_media("ig-1")
    summary = result["media"][0]
    assert summary["media_ref"] == "media_1"
    assert summary["caption"] == "sunset"
    assert summary["permalink"].endswith("/p/abc")
    assert summary["like_count"] == 100
    assert "media_id" not in summary


def test_instagram_list_media_include_ids() -> None:
    connector, transport = _instagram()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "m-2",
                        "caption": "x",
                        "media_type": "REELS",
                        "permalink": "",
                        "timestamp": "",
                        "like_count": 0,
                        "comments_count": 0,
                    }
                ]
            }
        )
    )
    result = connector.list_media("ig-1", include_ids=True)
    assert result["media"][0]["media_id"] == "m-2"


def test_instagram_list_comments_summary_default() -> None:
    connector, transport = _instagram()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "c1",
                        "username": "fan",
                        "text": "cool!",
                        "timestamp": "2026-04-01T09:00:00Z",
                        "like_count": 2,
                    }
                ]
            }
        )
    )
    result = connector.list_comments("m-1")
    summary = result["comments"][0]
    assert summary["comment_ref"] == "comment_1"
    assert summary["author"] == "fan"
    assert summary["text"] == "cool!"
    assert "comment_id" not in summary


def test_instagram_destructive_tags() -> None:
    connector = InstagramToolSet(access_token="t")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_comment") for name in destructive)


# MARK: - LinkedIn agent-ready


def test_linkedin_list_posts_for_author_summary_default() -> None:
    connector, transport = _linkedin()
    transport.enqueue(
        json_response(
            {
                "elements": [
                    {
                        "id": "urn:li:share:9876",
                        "author": "urn:li:person:1",
                        "commentary": "hello LI",
                        "publishedAt": 1700000000,
                        "visibility": "PUBLIC",
                        "lifecycleState": "PUBLISHED",
                    }
                ],
                "paging": {"count": 10},
            }
        )
    )
    result = connector.list_posts_for_author(author_urn="urn:li:person:1")
    summary = result["posts"][0]
    assert summary["post_ref"] == "post_1"
    assert summary["commentary"] == "hello LI"
    assert summary["author"] == "urn:li:person:1"
    assert "post_urn" not in summary


def test_linkedin_list_posts_for_author_include_ids() -> None:
    connector, transport = _linkedin()
    transport.enqueue(json_response({"elements": [{"id": "urn:li:share:1", "commentary": "x"}]}))
    result = connector.list_posts_for_author(author_urn="urn:li:person:1", include_ids=True)
    assert result["posts"][0]["post_urn"] == "urn:li:share:1"


def test_linkedin_delete_post_tolerant_input() -> None:
    connector, transport = _linkedin()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.delete_post("urn:li:share:111")
    connector.delete_post({"post_urn": "urn:li:share:222"})
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[1].method == "DELETE"


def test_linkedin_list_comments_summary_default() -> None:
    connector, transport = _linkedin()
    transport.enqueue(
        json_response(
            {
                "elements": [
                    {
                        "id": "comment-1",
                        "actor": "urn:li:person:2",
                        "message": {"text": "nice"},
                        "createdAt": 1700000100,
                    }
                ]
            }
        )
    )
    result = connector.list_comments("urn:li:share:1")
    summary = result["comments"][0]
    assert summary["comment_ref"] == "comment_1"
    assert summary["text"] == "nice"
    assert "comment_id" not in summary


def test_linkedin_destructive_tags() -> None:
    connector = LinkedInToolSet(access_token="t")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_post") for name in destructive)


# MARK: - TikTok agent-ready


def test_tiktok_list_videos_summary_default() -> None:
    connector, transport = _tiktok()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "videos": [
                        {
                            "id": "vid-1",
                            "title": "Cool clip",
                            "username": "creator",
                            "create_time": 1700000000,
                            "view_count": 5000,
                            "like_count": 200,
                            "comment_count": 10,
                            "share_count": 5,
                            "duration": 30,
                            "share_url": "https://tiktok.com/@creator/video/vid-1",
                        }
                    ],
                    "cursor": 1,
                    "has_more": False,
                }
            }
        )
    )
    result = connector.list_videos()
    summary = result["videos"][0]
    assert summary["video_ref"] == "video_1"
    assert summary["title"] == "Cool clip"
    assert summary["view_count"] == 5000
    assert summary["url"] == "https://tiktok.com/@creator/video/vid-1"
    assert "video_id" not in summary


def test_tiktok_list_videos_include_ids() -> None:
    connector, transport = _tiktok()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "videos": [
                        {
                            "id": "vid-2",
                            "title": "x",
                            "username": "u",
                            "create_time": 0,
                            "view_count": 0,
                            "like_count": 0,
                            "comment_count": 0,
                            "share_count": 0,
                            "duration": 0,
                        }
                    ],
                    "cursor": 0,
                    "has_more": False,
                }
            }
        )
    )
    result = connector.list_videos(include_ids=True)
    assert result["videos"][0]["video_id"] == "vid-2"


def test_tiktok_destructive_tags_empty() -> None:
    connector = TikTokToolSet(access_token="t")
    destructive = _destructive_tool_names(connector)
    # TikTok connector does not currently expose destructive tools.
    assert destructive == set()


# MARK: - YouTube agent-ready


def test_youtube_search_summary_default() -> None:
    connector, transport = _youtube()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": {"kind": "youtube#video", "videoId": "abc123"},
                        "snippet": {
                            "title": "Claude tutorial",
                            "channelTitle": "MaivnTV",
                            "channelId": "UCabc",
                            "publishedAt": "2026-05-01T00:00:00Z",
                            "description": "A great tutorial",
                        },
                    }
                ],
                "nextPageToken": "next",
                "pageInfo": {"totalResults": 1},
            }
        )
    )
    result = connector.search(q="claude")
    summary = result["videos"][0]
    assert summary["video_ref"] == "video_1"
    assert summary["title"] == "Claude tutorial"
    assert summary["channel"] == "MaivnTV"
    assert summary["url"] == "https://www.youtube.com/watch?v=abc123"
    assert "video_id" not in summary
    assert "channel_id" not in summary


def test_youtube_search_include_ids() -> None:
    connector, transport = _youtube()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": {"kind": "youtube#video", "videoId": "abc456"},
                        "snippet": {
                            "title": "x",
                            "channelTitle": "x",
                            "channelId": "UC456",
                            "publishedAt": "",
                            "description": "",
                        },
                    }
                ]
            }
        )
    )
    result = connector.search(q="hi", include_ids=True)
    assert result["videos"][0]["video_id"] == "abc456"
    assert result["videos"][0]["channel_id"] == "UC456"


def test_youtube_list_videos_summary_default() -> None:
    connector, transport = _youtube()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "vid-1",
                        "snippet": {
                            "title": "Demo",
                            "channelTitle": "Maivn",
                            "channelId": "UCx",
                            "publishedAt": "2026-05-02T00:00:00Z",
                            "description": "desc",
                        },
                        "statistics": {
                            "viewCount": "100",
                            "likeCount": "10",
                            "commentCount": "1",
                        },
                        "contentDetails": {"duration": "PT5M"},
                    }
                ]
            }
        )
    )
    result = connector.list_videos(id=["vid-1"])
    summary = result["videos"][0]
    assert summary["title"] == "Demo"
    assert summary["view_count"] == 100
    assert summary["like_count"] == 10
    assert summary["duration"] == "PT5M"
    assert "video_id" not in summary


def test_youtube_delete_video_tolerant_input() -> None:
    connector, transport = _youtube()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.delete_video("v1")
    connector.delete_video({"video_id": "v2"})
    connector.delete_video({"id": {"videoId": "v3"}})
    assert transport.requests[0].params["id"] == "v1"
    assert transport.requests[1].params["id"] == "v2"
    assert transport.requests[2].params["id"] == "v3"


def test_youtube_destructive_tags() -> None:
    connector = YouTubeToolSet(token="t")
    destructive = _destructive_tool_names(connector)
    assert any(name.endswith("delete_video") for name in destructive)
    assert any(name.endswith("delete_playlist_item") for name in destructive)
