# Social media

Public social-media platforms. Each toolset exposes the standard
`@toolset` / `@toolify` shape; the snippets below show only the
constructor and the headline tool surface.

> Tip: most agents only need read access (browse + analytics).
> Register with `add_toolset(..., include_tags=["read"])` or
> `exclude_tags=["destructive"]` to drop publish / delete tools.

> **Agent-ready pattern.** Across these connectors, broad list /
> search / feed tools return compact human-readable summaries by
> default with a stable `_ref` field (`tweet_ref`, `post_ref`,
> `media_ref`, `video_ref`, `status_ref`, `comment_ref`, ...) and a
> small default page size (usually 10-25). Raw provider IDs are hidden
> unless you pass `include_ids=True`; pass `include_metadata=False` to
> get the raw provider response. Write tools that target a single item
> (`delete_tweet`, `delete_post`, `like_tweet`, `delete_status`,
> `delete_pin`, `delete_message`, `destroy_update`, ...) accept either
> a raw ID/URN/URI string or the summary dict from the corresponding
> list/search tool.

## XToolSet (formerly Twitter)

```python
from maivn_tools import XToolSet

connector = XToolSet(bearer_token=secrets["X_BEARER_TOKEN"])
```

Tools: `get_me`, `get_user`, `get_user_by_ids`, `get_tweet`,
`get_tweets`, `search_recent_tweets(query, max_results, next_token,
start_time, end_time, tweet_fields, expansions, include_metadata,
include_ids)`, `get_user_tweets(user_id, max_results, pagination_token,
exclude, tweet_fields, include_metadata, include_ids)`,
`get_user_mentions(user_id, max_results, pagination_token,
include_metadata, include_ids)`, `post_tweet`, `delete_tweet`
(destructive), `like_tweet`, `unlike_tweet` (destructive), `retweet`,
`unretweet` (destructive), `follow_user`, `unfollow_user`
(destructive), `get_followers(user_id, max_results, pagination_token,
include_metadata, include_ids)`, `get_following(user_id, max_results,
pagination_token, include_metadata, include_ids)`, `list_owned_lists`,
`create_list`, `delete_list` (destructive), `send_dm`.

### Agent-ready behavior

`search_recent_tweets`, `get_user_tweets`, and `get_user_mentions`
return compact summaries by default with `tweet_ref` (stable
`tweet_1` ...), `author` (@handle), `text`, `posted_at`, like /
repost / reply counts, and `url`. `get_followers` and `get_following`
return `user_ref` summaries (handle, name, follower counts, profile
URL). Raw X tweet/user IDs are omitted unless `include_ids=True`;
`include_metadata=False` returns the raw v2 payload. Default
`max_results` is 10 for tweets, 25 for followers/following.
`delete_tweet`, `like_tweet`, `unlike_tweet`, `retweet`, and
`unretweet` accept either a raw `tweet_id` string or a tweet/search
result dict — the connector extracts the ID for you.

```python
x.search_recent_tweets("anthropic claude")
# { "tweets": [{"tweet_ref": "tweet_1", "author": "@user",
#                "text": "...", "posted_at": "...",
#                "like_count": 12, "url": "https://x.com/..."}],
#   "next_token": "...", "result_count": 10 }
```

### Destructive tools

`delete_tweet`, `unlike_tweet`, `unretweet`, `unfollow_user`, and
`delete_list` are tagged `destructive=True`. `delete_tweet` is not
reversible. Confirm with the user before calling.

## MetaToolSet (Facebook Graph)

```python
from maivn_tools import MetaToolSet

connector = MetaToolSet(access_token=secrets["FB_PAGE_TOKEN"])
```

Pages, posts, comments, and insights via the Graph API. Tools:
`get_me`, `list_accounts`, `get_page`, `list_page_posts(page_id, limit,
after, fields, include_metadata, include_ids)`, `publish_page_post`,
`delete_post` (destructive), `list_post_comments(post_id, limit, after,
include_metadata, include_ids)`, `reply_to_comment`, `delete_comment`
(destructive), `get_page_insights`, `get_post_insights`.

### Agent-ready behavior

`list_page_posts` returns compact summaries with `post_ref`, `message`,
`posted_at`, and `permalink_url`. `list_post_comments` returns
`comment_ref` with author, message, `posted_at`, and `like_count`.
Default `limit` is 10. Raw Graph post / comment IDs are omitted unless
`include_ids=True`; `include_metadata=False` returns the raw Graph
response. `delete_post` accepts a raw `post_id` string or a post dict
from `list_page_posts`.

```python
meta.list_page_posts(page_id)
# { "posts": [{"post_ref": "post_1", "message": "Launch day!",
#                "posted_at": "...", "permalink_url": "https://..."}],
#   "paging": {...} }
```

### Destructive tools

`delete_post` and `delete_comment` are tagged `destructive=True` and
not reversible. Confirm with the user first.

## InstagramToolSet

```python
from maivn_tools import InstagramToolSet

connector = InstagramToolSet(access_token=secrets["IG_PAGE_TOKEN"])
```

Requires a Business or Creator IG account linked to a Facebook Page.
Tools: `get_account`, `list_media(ig_user_id, limit, after, fields,
include_metadata, include_ids)`, `get_media`, `create_media_container`,
`publish_media`, `get_container_status`, `list_comments(media_id,
limit, include_metadata, include_ids)`, `reply_to_comment`,
`delete_comment` (destructive), `hide_comment`, `get_media_insights`,
`get_account_insights`, `list_stories`.

### Agent-ready behavior

`list_media` returns `media_ref` summaries with caption, media type,
permalink, posted-at, like / comment counts. `list_comments` returns
`comment_ref` summaries (author username, text, posted-at, like
count). Default `limit` is 10 for media, 25 for comments. Raw IG IDs
are omitted unless `include_ids=True`; `include_metadata=False`
returns the raw Graph response.

```python
instagram.list_media(ig_user_id)
# { "media": [{"media_ref": "media_1", "caption": "...",
#               "media_type": "IMAGE", "permalink": "https://...",
#               "like_count": 42, ...}], "paging": {...} }
```

Two-step publish: call `create_media_container(...)` then poll
`get_container_status(container_id)` until the upload finishes, then
`publish_media(creation_id=...)`.

### Destructive tools

`delete_comment` is tagged `destructive=True` and not reversible —
prefer `hide_comment` for soft-removing. `publish_media` posts
publicly to the account's grid; treat it as a high-impact write and
confirm with the user.

## LinkedInToolSet

```python
from maivn_tools import LinkedInToolSet

connector = LinkedInToolSet(access_token=secrets["LI_TOKEN"])
```

Posts, comments, member identity, and organization-level reads.
Tools: `get_userinfo`, `get_me`, `create_post`, `get_post`,
`delete_post` (destructive), `list_posts_for_author(author_urn, count,
start, include_metadata, include_ids)`, `create_comment`,
`list_comments(post_urn, count, include_metadata, include_ids)`,
`get_organization`, `list_organization_acls`.

The Posts API uses URNs (`urn:li:person:...`, `urn:li:organization:...`,
`urn:li:share:...`); pass them through directly.

### Agent-ready behavior

`list_posts_for_author` returns `post_ref` summaries with author URN,
commentary, posted-at, visibility, and lifecycle state.
`list_comments` returns `comment_ref` with actor, text, posted-at.
Default `count` is 10 for posts, 25 for comments. Raw post URNs and
comment IDs are omitted unless `include_ids=True`;
`include_metadata=False` returns the raw REST response. `delete_post`
accepts a raw URN string or a post dict from `list_posts_for_author`.

```python
linkedin.list_posts_for_author(author_urn="urn:li:person:...")
# { "posts": [{"post_ref": "post_1", "author": "urn:li:person:...",
#                "commentary": "...", "visibility": "PUBLIC", ...}],
#   "paging": {...} }
```

### Destructive tools

`delete_post` is tagged `destructive=True` and not reversible. Confirm
with the user first.

## TikTokToolSet

```python
from maivn_tools import TikTokToolSet

connector = TikTokToolSet(access_token=secrets["TT_TOKEN"])
```

Content Posting + Display APIs. Tools: `get_user_info`,
`list_videos(fields, cursor, max_count, include_metadata, include_ids)`,
`query_videos`, `get_creator_info`, `init_video_upload`,
`init_inbox_upload`, `get_publish_status`, `init_photo_publish`.

### Agent-ready behavior

`list_videos` returns `video_ref` summaries with title, author
username, posted-at, view / like / comment / share counts, duration,
and a constructed `url`. Default `max_count` is 10 (TikTok caps at
20). Raw TikTok video IDs are omitted unless `include_ids=True`;
`include_metadata=False` returns the raw TikTok response.
`query_videos` is the explicit ID-lookup tool — pass it the
`video_id` list obtained from `list_videos(include_ids=True)`.

```python
tiktok.list_videos()
# { "videos": [{"video_ref": "video_1", "title": "...",
#                "author": "...", "view_count": 1234,
#                "url": "https://www.tiktok.com/@.../video/..."}],
#   "cursor": ..., "has_more": true }
```

`init_video_upload` and `init_photo_publish` start an asynchronous
upload; poll `get_publish_status(publish_id)` until the job reports
`status: PUBLISHED`.

## YouTubeToolSet

```python
from maivn_tools import YouTubeToolSet

connector = YouTubeToolSet(token=token_cache)
```

YouTube Data API v3. Tools: `list_channels`, `list_videos(id, part,
include_metadata, include_ids)`, `search(q, channel_id, type, order,
max_results, page_token, include_metadata, include_ids)`,
`list_playlists`, `list_playlist_items`, `add_to_playlist`,
`delete_playlist_item` (destructive), `update_video`, `delete_video`
(destructive), `list_comment_threads(video_id, channel_id, max_results,
page_token, order, include_metadata, include_ids)`, `post_comment`.

### Agent-ready behavior

`search`, `list_videos`, and `list_comment_threads` return compact
summaries by default. `video_ref` summaries include title, channel
name, posted-at, description, view / like / comment counts, duration,
and a `url`. `comment_ref` summaries include author, text, posted-at,
like / reply counts. Default `max_results` is 10. Raw YouTube video /
channel / comment IDs are omitted unless `include_ids=True`;
`include_metadata=False` returns the raw YouTube response.
`delete_video` accepts a raw `video_id` string or a search/list result
dict.

```python
youtube.search(q="claude api demo")
# { "videos": [{"video_ref": "video_1", "title": "...",
#                "channel": "...", "url": "https://www.youtube.com/watch?v=..."}],
#   "next_page_token": "...", "page_info": {...} }
```

### Destructive tools

`delete_video` and `delete_playlist_item` are tagged
`destructive=True`. `delete_video` is not reversible.

> The YouTube Data API has tight daily quota costs (e.g.
> `search` is 100 units). Cache results and prefer narrowly-scoped
> `list_videos` / `list_channels` calls when you can.

## RedditToolSet

```python
from maivn_tools import RedditToolSet

connector = RedditToolSet(
    access_token=secrets["REDDIT_TOKEN"],
    user_agent="maivn-app:1.0 (by /u/your-handle)",
)
```

Reddit requires a descriptive `User-Agent`. Tools: `get_me`,
`list_subscribed_subreddits`, `get_subreddit_about`,
`list_subreddit_posts(subreddit, sort, limit, after, time,
include_metadata, include_ids)`, `search(query, subreddit, sort, limit,
after, include_metadata, include_ids)`, `get_post`, `submit_post`,
`submit_comment`, `vote`, `save`, `unsave`, `subscribe`, `delete_thing`
(destructive).

### Agent-ready behavior

`list_subreddit_posts` and `search` return compact summaries with
`post_ref`, title, author, subreddit, posted-at (Unix epoch), score,
comment count, URL, and a truncated `selftext` (first 500 chars).
Default `limit` is 10. Raw Reddit fullnames (`t3_...`) are omitted
unless `include_ids=True`; `include_metadata=False` returns the raw
Reddit listing. `submit_comment`, `vote`, `save`, `unsave`, and
`delete_thing` accept either a raw `thing_id` (fullname) or a post /
comment dict from a listing.

```python
reddit.list_subreddit_posts("python", sort="hot")
# { "posts": [{"post_ref": "post_1", "title": "...",
#               "author": "...", "subreddit": "python",
#               "score": 1234, "num_comments": 56,
#               "url": "https://www.reddit.com/r/python/..."}],
#   "after": "...", "before": null }
```

### Destructive tools

`delete_thing` is tagged `destructive=True` and not reversible (the
post or comment is removed permanently). Confirm with the user.

## PinterestToolSet

```python
from maivn_tools import PinterestToolSet

connector = PinterestToolSet(access_token=secrets["PINTEREST_TOKEN"])
```

Pinterest API v5: boards, pins, and analytics. Tools: `get_user_account`,
`list_boards(bookmark, page_size, privacy, include_metadata,
include_ids)`, `get_board`, `create_board`, `delete_board`
(destructive), `list_board_pins(board_id, bookmark, page_size,
include_metadata, include_ids)`, `list_pins(bookmark, page_size,
include_metadata, include_ids)`, `get_pin`, `create_pin`, `delete_pin`
(destructive), `get_pin_analytics`, `get_user_analytics`.

### Agent-ready behavior

`list_boards` returns `board_ref` summaries with name, description,
privacy, owner, pin / follower counts, created-at.
`list_board_pins` / `list_pins` return `pin_ref` summaries with
title, description, alt text, link, created-at, and a constructed
`url`. Default `page_size` is 25. Raw Pinterest board / pin IDs are
omitted unless `include_ids=True`; `include_metadata=False` returns
the raw Pinterest response. `delete_pin` accepts either a raw
`pin_id` string or a pin dict.

```python
pinterest.list_pins()
# { "pins": [{"pin_ref": "pin_1", "title": "...",
#              "url": "https://www.pinterest.com/pin/..."}],
#   "bookmark": "..." }
```

### Destructive tools

`delete_board` (removes board + all pins) and `delete_pin` are tagged
`destructive=True` and not reversible.

## DiscordToolSet

```python
from maivn_tools import DiscordToolSet

connector = DiscordToolSet(token=secrets["DISCORD_BOT_TOKEN"])
```

Defaults to `token_type="Bot"`; set `token_type="Bearer"` for user
OAuth tokens. Tools: `get_current_user`, `list_current_user_guilds(before,
after, limit, include_metadata, include_ids)`, `get_guild`,
`list_guild_channels(guild_id, include_metadata, include_ids)`,
`list_guild_members`, `get_channel`, `list_messages(channel_id, limit,
before, after, around, include_metadata, include_ids)`, `get_message`,
`create_message`, `edit_message`, `delete_message` (destructive),
`create_reaction`, `create_dm`, `add_guild_member_role`,
`remove_guild_member` (destructive), `execute_webhook`.

### Agent-ready behavior

`list_current_user_guilds`, `list_guild_channels`, and `list_messages`
return compact summaries. `guild_ref` carries name + owner +
permissions; `channel_ref` carries name + type + topic; `message_ref`
carries author username, content, timestamp, and `has_attachments`.
Default `limit` is 25 for guilds, 20 for messages. Raw Discord
snowflakes are omitted unless `include_ids=True`;
`include_metadata=False` returns the raw response. `list_guild_channels`
populates a channel name -> ID cache; `create_message`, `edit_message`,
`delete_message`, `create_reaction`, and `get_message` accept a channel
name, raw snowflake, or channel-summary dict for `channel_id`, and the
message dict or raw ID for `message_id`.

```python
discord.list_messages("general")
# { "messages": [{"message_ref": "message_1", "author": "alice",
#                  "content": "...", "timestamp": "...",
#                  "has_attachments": false}] }
```

### Destructive tools

`delete_message` (not reversible) and `remove_guild_member` (kicks
the user) are tagged `destructive=True`. Confirm with the user before
invoking.

## TelegramToolSet

```python
from maivn_tools import TelegramToolSet

connector = TelegramToolSet(bot_token=secrets["TG_BOT_TOKEN"])
```

The bot token is embedded in the request path (`/bot<TOKEN>/...`), as
required by the Bot API. Tools: `get_me`, `get_updates(offset, limit,
timeout, allowed_updates, include_metadata, include_ids)`, `send_message`,
`edit_message_text`, `delete_message` (destructive), `send_photo`,
`answer_callback_query`, `get_chat`, `get_chat_member`, `set_webhook`,
`delete_webhook`, `get_webhook_info`.

### Agent-ready behavior

`get_updates` returns compact summaries by default with `update_ref`,
update `type` (`message` / `callback_query` / `channel_post` / ...),
`chat_title`, `sender`, and `text`. Default `limit` is 25. Telegram
update_id / message_id / chat_id integers are omitted unless
`include_ids=True`; `include_metadata=False` returns the raw Telegram
response. `send_message`, `edit_message_text`, `delete_message`,
`send_photo`, `get_chat`, `get_chat_member`, and the
`reply_to_message_id` argument all accept either a raw int/string ID
or the update / message dict from `get_updates`.

```python
telegram.get_updates()
# { "ok": true,
#   "updates": [{"update_ref": "update_1", "type": "message",
#                 "chat_title": "Alice", "sender": "alice",
#                 "text": "hi"}] }
```

### Destructive tools

`delete_message` is tagged `destructive=True` — the message is removed
for everyone in the chat and cannot be recovered.

## WhatsAppBusinessToolSet

```python
from maivn_tools import WhatsAppBusinessToolSet

connector = WhatsAppBusinessToolSet(
    access_token=secrets["WABA_TOKEN"],
    phone_number_id="123456789",
)
```

WhatsApp Business Cloud API (Meta Graph). Tools: `send_text`,
`send_template`, `send_media`, `mark_message_read`, `get_media_metadata`,
`delete_media` (destructive), `list_phone_numbers`,
`list_message_templates(waba_id, limit, include_metadata, include_ids)`,
`create_message_template`.

### Agent-ready behavior

`list_message_templates` returns `template_ref` summaries with name,
language, category, status. Default `limit` is 25. Raw template IDs
are omitted unless `include_ids=True`; `include_metadata=False`
returns the raw Graph response. `mark_message_read` accepts either a
raw `wamid` string or the message-summary dict returned by a previous
`send_*` call (extracts `messages[0].id`).

```python
whatsapp.list_message_templates(waba_id)
# { "templates": [{"template_ref": "template_1", "name": "welcome",
#                   "language": "en_US", "category": "MARKETING",
#                   "status": "APPROVED"}], "paging": {...} }
```

### Destructive tools

`delete_media` is tagged `destructive=True` — the uploaded asset is
removed and cannot be recovered.

## MastodonToolSet

```python
from maivn_tools import MastodonToolSet

connector = MastodonToolSet(
    access_token=secrets["MASTODON_TOKEN"],
    instance_url="https://mastodon.social",
)
```

Tools: `verify_credentials`, `get_account`, `lookup_account`,
`home_timeline(limit, max_id, since_id, include_metadata, include_ids)`,
`public_timeline(local, remote, only_media, limit, include_metadata,
include_ids)`, `hashtag_timeline(hashtag, limit, max_id, include_metadata,
include_ids)`, `get_status`, `post_status`, `delete_status` (destructive),
`favourite_status`, `reblog_status`, `follow_account`,
`unfollow_account`, `list_notifications`, `search`.

### Agent-ready behavior

All three timeline tools (`home_timeline`, `public_timeline`,
`hashtag_timeline`) return compact `status_ref` summaries by default
with author (acct handle), display name, HTML content, posted-at,
visibility, favourites / reblogs / replies counts, and `url`. Default
`limit` is 20. Raw Mastodon status IDs are omitted unless
`include_ids=True`; `include_metadata=False` returns the raw response.
`delete_status`, `favourite_status`, and `reblog_status` accept
either a raw `status_id` or a status dict from a timeline.

```python
mastodon.home_timeline()
# { "statuses": [{"status_ref": "status_1", "author": "alice@example",
#                  "content": "...", "favourites_count": 5,
#                  "url": "https://..."}] }
```

### Destructive tools

`delete_status` is tagged `destructive=True` and not reversible.

## BlueskyToolSet

```python
from maivn_tools import BlueskyToolSet

connector = BlueskyToolSet(
    access_jwt=session["accessJwt"],
    did=session["did"],
)
```

AT Protocol XRPC. Obtain the JWT + DID via
`com.atproto.server.createSession` (or any of the standard atproto
clients) and pass them in. Tools: `get_profile`, `get_timeline(limit,
cursor, include_metadata, include_ids)`, `get_author_feed(actor, limit,
cursor, include_metadata, include_ids)`, `search_posts(query, limit,
cursor, author, include_metadata, include_ids)`, `create_post`,
`delete_post` (destructive), `like`, `repost`, `follow`,
`get_followers(actor, limit, cursor, include_metadata, include_ids)`,
`get_follows(actor, limit, cursor, include_metadata, include_ids)`.

### Agent-ready behavior

`get_timeline`, `get_author_feed`, and `search_posts` return
`post_ref` summaries with author handle, display name, text,
posted-at, like / repost / reply counts, and `url`. `get_followers` /
`get_follows` return `user_ref` summaries (handle, name, description,
profile URL). Default `limit` is 25. Raw `at://` URIs, CIDs, and DIDs
are omitted unless `include_ids=True`; `include_metadata=False`
returns the raw XRPC response. `delete_post` accepts a raw `rkey`, a
full `at://` URI, or a post dict. `like` and `repost` accept either
a feed-view/post dict or explicit `uri` + `cid` arguments.

```python
bluesky.search_posts("agent ready toolsets")
# { "posts": [{"post_ref": "post_1", "author": "alice.bsky.social",
#                "text": "...", "like_count": 12,
#                "url": "https://bsky.app/profile/.../post/..."}],
#   "cursor": "..." }
```

### Destructive tools

`delete_post` is tagged `destructive=True` and not reversible.

## ThreadsToolSet

```python
from maivn_tools import ThreadsToolSet

connector = ThreadsToolSet(access_token=secrets["THREADS_TOKEN"])
```

Threads (Meta) Graph API. Two-step publish: call
`create_media_container(...)` then poll `get_container_status(creation_id)`,
then `publish_media(creation_id=...)`. Tools: `get_me`,
`list_threads(user_id, fields, limit, after, since, until,
include_metadata, include_ids)`, `get_thread`, `create_media_container`,
`publish_media`, `get_container_status`, `list_replies(media_id,
fields, reverse, include_metadata, include_ids)`, `hide_reply`,
`get_media_insights`, `get_user_insights`.

### Agent-ready behavior

`list_threads` returns `post_ref` summaries with author username,
text, posted-at, media type, and permalink. `list_replies` returns
`reply_ref` summaries (author, text, posted-at, permalink). Default
`limit` is 10. Raw thread / reply IDs are omitted unless
`include_ids=True`; `include_metadata=False` returns the raw Graph
response.

```python
threads.list_threads(user_id)
# { "posts": [{"post_ref": "post_1", "author": "alice",
#                "text": "...", "permalink": "https://www.threads.net/..."}],
#   "paging": {...} }
```

### Destructive tools

This connector does not expose a hard delete; `hide_reply` (with
`hide=False` to unhide) is a soft alternative.

## BufferToolSet

```python
from maivn_tools import BufferToolSet

connector = BufferToolSet(access_token=secrets["BUFFER_TOKEN"])
```

Buffer Publish + Profiles API for cross-network scheduling. Tools:
`get_user`, `list_profiles`, `get_profile`,
`list_pending_updates(profile_id, page, count, include_metadata,
include_ids)`, `list_sent_updates(profile_id, page, count,
include_metadata, include_ids)`, `get_update`, `create_update`,
`update_update`, `share_update_now`, `destroy_update` (destructive),
`get_update_interactions`.

### Agent-ready behavior

`list_pending_updates` and `list_sent_updates` return `update_ref`
summaries with text, status, scheduled-at, sent-at, service,
author. Default `count` is 10. Raw Buffer update IDs are omitted
unless `include_ids=True`; `include_metadata=False` returns the raw
Buffer response. `update_update`, `share_update_now`, and
`destroy_update` accept either a raw `update_id` string or an update
dict from `list_pending_updates` / `list_sent_updates`.

```python
buffer.list_pending_updates(profile_id)
# { "updates": [{"update_ref": "update_1", "text": "Launch day!",
#                  "status": "buffer", "scheduled_at": 1716000000,
#                  "service": "twitter"}], "total": 3 }
```

### Destructive tools

`destroy_update` is tagged `destructive=True` and not reversible —
the update is removed from the queue or revoked if already sent.
`share_update_now` publishes immediately, bypassing the schedule;
treat it as a high-impact write.
