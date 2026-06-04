# Collaboration & messaging

Group messaging, meetings, and video conferencing. Every connector
follows the standard `@toolset` / `@toolify` shape.

> Tip: read-only registration is usually enough for triage/notification
> agents. Use `add_toolset(..., include_tags=["read"])` to drop write
> tools, or `exclude_tags=["destructive"]` to keep writes but drop the
> irreversible ones.

> **Agent-ready pattern.** Across all four connectors, broad list /
> search / history tools return compact human-readable summaries by
> default with a stable `_ref` field (`channel_ref`, `message_ref`,
> `team_ref`, `space_ref`, `meeting_ref`, etc.) and a small default page
> size (usually 10-25). Raw provider IDs are omitted unless you pass
> `include_ids=True`; pass `include_metadata=False` to get the raw
> provider response with every field. Write tools that target a single
> item (`update_message`, `delete_message`, `send_chat_message`, ...)
> accept either the raw ID string or the summary dict directly — the
> connector extracts the ID for you.

## SlackToolSet

`SlackToolSet` wraps the Slack Web API. It authenticates with a bot
(`xoxb-...`) or user (`xoxp-...`) token and exposes identity, channel /
IM lifecycle, messaging, threads, reactions, pins, files, reminders,
and search.

```python
from maivn import Agent
from maivn_tools import SlackToolSet, register_connector

connector = SlackToolSet(token="xoxb-...")
agent = Agent(model="auto")
register_connector(agent, connector)
```

The connector forwards the token as a bearer credential. Scope
enforcement happens on Slack's side; advertised scopes include
`channels:read`, `channels:history`, `chat:write`, `chat:write.public`,
`reactions:read`, `reactions:write`, `pins:read`, `pins:write`,
`files:read`, `files:write`, `search:read`, `users:read`,
`users:read.email`, `users.profile:read`, `users.profile:write`,
`reminders:read`, `reminders:write`, `emoji:read`, `team:read`.

### Tools

**Identity and presence.** `auth_test`, `user_lookup`, `list_users`,
`get_user_profile`, `get_user_presence`, `set_user_status`, `team_info`,
`emoji_list`.

**Channels and conversations.** `list_channels(types, exclude_archived,
limit, cursor, include_metadata, include_ids)`, `channel_info`,
`channel_members`, `channel_history(channel, limit, cursor, oldest,
latest, include_metadata, include_ids)`, `thread_replies`,
`create_channel`, `rename_channel`, `set_channel_topic`,
`set_channel_purpose`, `join_channel`, `leave_channel`,
`invite_to_channel`, `kick_from_channel`, `archive_channel`,
`unarchive_channel`, `open_im`.

**Messages, pins, reactions.** `post_message`, `post_ephemeral`,
`update_message`, `schedule_message`, `get_permalink`, `delete_message`
(destructive), `add_reaction`, `remove_reaction`, `pin_message`,
`unpin_message`, `list_pins`.

**Files.** `list_files`, `file_info`, `delete_file` (destructive).

**Search.** `search_messages(query, sort, sort_dir, count, page,
include_metadata, include_ids)`, `search_files`.

**Reminders.** `add_reminder`, `list_reminders`, `delete_reminder`
(destructive).

Every Slack response is checked for `ok=false`. The connector raises
`SlackApiError` (a subclass of `ProviderError`) with the original Slack
error string and response body in `detail`.

### Agent-ready behavior

`list_channels`, `channel_history`, and `search_messages` default to
compact summaries with `channel_ref` / `message_ref` and the friendly
fields an agent can quote (name, sender, text, ts, permalink). Raw
Slack IDs (`C0123`, user IDs) are hidden — pass `include_ids=True`
when a write tool needs them, or `include_metadata=False` to bypass
summarization entirely. `list_channels` populates a name -> ID cache
so write tools (`post_message`, `update_message`, `delete_message`,
etc.) accept a friendly channel name, the raw ID, or the
channel-summary dict from `list_channels`. `update_message` /
`delete_message` / `add_reaction` similarly accept a raw `ts` string
or a message-summary dict from `channel_history`.

```python
# Summaries — safe for final answers, channel_ref is stable across calls.
slack.search_messages("from:alice db migration")
# { "messages": [{"message_ref": "message_1", "username": "alice",
#                  "channel_name": "ops", "text": "...", "ts": "...",
#                  "permalink": "https://..."}], "total": 3, ... }

# Opt-in raw IDs (only when a follow-up tool needs them).
slack.search_messages("from:alice db migration", include_ids=True)
```

### Destructive tools

`delete_message`, `delete_file`, and `delete_reminder` are tagged
`destructive=True`. They are not reversible — confirm with the user
before invoking, or drop them at registration with
`exclude_tags=["destructive"]`.

### Pagination

Slack pagination uses opaque `cursor` values. The connector accepts a
`cursor` argument on `list_channels`, `list_users`, `channel_members`,
`channel_history`, and `thread_replies`, and returns the raw
`response_metadata.next_cursor` in the response body. Use
`CursorPaginator` from the runtime layer to walk multiple pages:

```python
from maivn_tools import CursorPaginator


def fetch(cursor):
    page = connector.list_channels(cursor=cursor)
    return page, page.get("response_metadata", {}).get("next_cursor") or None


paginator = CursorPaginator(fetch, items_key="channels")
all_channels = list(paginator.iter_items())
```

## MicrosoftTeamsToolSet

Microsoft Teams via Microsoft Graph v1.0.

```python
from maivn_tools import MicrosoftTeamsToolSet

connector = MicrosoftTeamsToolSet(token=token_cache)
```

Tools: `list_joined_teams(include_metadata, include_ids)`, `get_team`,
`list_channels(team_id, include_metadata, include_ids)`, `get_channel`,
`create_channel`, `delete_channel` (destructive),
`list_channel_messages(team_id, channel_id, top, include_metadata,
include_ids)`, `send_channel_message`, `list_channel_replies`,
`reply_to_channel_message`, `list_members`, `add_member`,
`remove_member` (destructive), `list_chats(top, include_metadata,
include_ids)`, `get_chat`, `list_chat_messages(chat_id, top,
include_metadata, include_ids)`, `send_chat_message`.

### Agent-ready behavior

`list_joined_teams`, `list_channels`, `list_chats`,
`list_channel_messages`, and `list_chat_messages` return compact
summaries by default (`team_ref`, `channel_ref`, `chat_ref`,
`message_ref` with friendly display names, content previews, sender,
and `created_at`). Graph GUIDs are omitted unless `include_ids=True`;
`include_metadata=False` returns the raw Graph response. Default page
size is 25. `list_joined_teams` and `list_channels` populate name
caches so `get_team`, `get_channel`, `send_channel_message`, and
`reply_to_channel_message` accept a display name, a raw GUID, or the
summary dict directly.

```python
teams.list_channel_messages(team_id="Engineering", channel_id="general")
# { "messages": [{"message_ref": "message_1", "sender": "Alice",
#                  "content_preview": "Build is green", ...}] }
```

### Destructive tools

`delete_channel` and `remove_member` are tagged `destructive=True` and
remove user access / channel history. Filter them out with
`exclude_tags=["destructive"]` for read-mostly agents.

## GoogleChatToolSet

Google Chat (Workspace) v1.

```python
from maivn_tools import GoogleChatToolSet

connector = GoogleChatToolSet(token=token_cache)
```

Tools: `list_spaces(page_size, page_token, include_metadata,
include_ids)`, `get_space`, `create_space`, `delete_space`
(destructive), `search_spaces(query, page_size, page_token,
include_metadata, include_ids)`, `list_messages(space, page_size,
page_token, filter, include_metadata, include_ids)`, `get_message`,
`send_message`, `update_message`, `delete_message` (destructive),
`list_members`, `add_member`, `remove_member` (destructive),
`create_reaction`, `delete_reaction` (destructive).

### Agent-ready behavior

`list_spaces`, `search_spaces`, and `list_messages` return compact
summaries by default with `space_ref` / `message_ref` plus display
name, space type, sender, and a 200-char text preview. Default page
size is 25 (20 for messages). Provider resource names
(`spaces/AAA`, `spaces/AAA/messages/m1`) are hidden unless
`include_ids=True`; `include_metadata=False` returns the raw response.
`list_spaces` and `search_spaces` populate a display-name cache so
`get_space`, `send_message`, `list_messages`, etc. accept the friendly
display name, the raw resource name, or the summary dict.
`update_message` / `delete_message` / `create_reaction` accept the
message dict from `list_messages` directly.

```python
google_chat.list_messages("Eng on-call")
# { "messages": [{"message_ref": "message_1", "sender": "Alice",
#                  "text_preview": "Pager fired again ...", ...}],
#   "next_page_token": null }
```

### Destructive tools

`delete_space`, `delete_message`, `remove_member`, and
`delete_reaction` are tagged `destructive=True`. Confirm with the user
before invoking — `delete_space` removes the entire message history.

## ZoomToolSet

Zoom Meetings + Webinars via the v2 REST API.

```python
from maivn_tools import ZoomToolSet

connector = ZoomToolSet(token=secrets["ZOOM_TOKEN"])
```

Tools: `list_users`, `get_user`, `create_user`, `delete_user`
(destructive), `list_meetings(user_id, type, page_size,
next_page_token, include_metadata, include_ids)`, `get_meeting`,
`create_meeting`, `update_meeting`, `delete_meeting` (destructive),
`list_meeting_participants`, `list_meeting_registrants`,
`list_webinars`, `get_webinar`, `create_webinar`, `list_recordings`,
`get_meeting_recordings`, `delete_meeting_recordings` (destructive).

### Agent-ready behavior

`list_meetings` returns compact summaries by default with
`meeting_ref`, `topic`, `start_time`, `duration`, and `join_url` and
a default page size of 25. Raw Zoom meeting IDs are omitted unless
`include_ids=True`; `include_metadata=False` returns the raw Zoom
response. `get_meeting`, `update_meeting`, `delete_meeting`,
`list_meeting_participants`, `list_meeting_registrants`, and
`get_meeting_recordings` accept either a raw meeting ID or the
meeting-summary dict from `list_meetings(include_ids=True)`.

```python
zoom.list_meetings()
# { "meetings": [{"meeting_ref": "meeting_1", "topic": "Eng standup",
#                  "start_time": "2026-05-16T15:00:00Z",
#                  "duration": 30, "join_url": "https://..."}], ... }
```

### Destructive tools

`delete_user`, `delete_meeting`, and `delete_meeting_recordings` are
tagged `destructive=True`. `delete_meeting_recordings` defaults to
`action="trash"` (reversible until purged); `action="delete"` is
irreversible. `delete_user` defaults to `disassociate` (keeps the
user) rather than full `delete`. Confirm any of these with the user.
