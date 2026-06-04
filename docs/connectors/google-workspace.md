# Google Workspace connectors

Three connectors cover the most common Google Workspace surfaces:

- `GmailToolSet` — mail.
- `GoogleCalendarToolSet` — calendars and events.
- `GoogleDriveToolSet` — files.

All three authenticate with a Google-issued OAuth 2.0 bearer token. The
recommended pattern is to obtain a refresh token once via the auth-code
flow, then plug it into `OAuth2Flow.refresh_token_cache(...)` so the
connector never sees a refresh secret directly.

```python
from maivn_tools import (
    OAuth2EndpointConfig,
    OAuth2Flow,
    GmailToolSet,
    GoogleCalendarToolSet,
    GoogleDriveToolSet,
)

flow = OAuth2Flow(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    endpoints=OAuth2EndpointConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
    ),
)
cache = flow.refresh_token_cache(refresh_token, scope=" ".join([
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]))

gmail = GmailToolSet(token=cache)
calendar = GoogleCalendarToolSet(token=cache)
drive = GoogleDriveToolSet(token=cache)
```

Each connector also accepts a static `OAuth2Token` or a raw token string
for one-off scripts.

> **Agent-ready pattern (Gmail is the reference implementation).**
> Across all three connectors, list / search / lookup tools return
> compact human-readable summaries by default with a stable `_ref`
> field (`message_ref`, `calendar_ref`, `event_ref`, `file_ref`,
> `folder_ref`). Raw Google IDs are hidden unless you pass
> `include_ids=True`; pass `include_metadata=False` to get the raw
> Google response with every field. Default page sizes are small (10
> for Gmail's metadata mode, 25 for everything else). Calendar and
> Drive write tools (`get_event`, `update_event`, `delete_event`,
> `download_file`, `delete_file`, `update_file_metadata`, ...) accept
> either a raw ID or the dict from the corresponding list/get tool.

## GmailToolSet tools

| Tool | Permission | Description |
| --- | --- | --- |
| `validate_connection()` | READ | Verify the token via `/users/me/profile`. |
| `get_profile()` | READ | Mailbox profile (address, counts, history id). |
| `list_labels()` | READ | List labels in the mailbox. |
| `get_label(label_id)` | READ | Fetch one label by id. |
| `search_messages(query, label_ids, max_results, page_token, include_metadata, include_ids)` | READ | Search via Gmail query syntax; compact `message_ref` summaries by default. |
| `get_message(message_id, format)` | READ | Fetch one message (`minimal`/`metadata`/`full`/`raw`). |
| `list_threads(query, label_ids, max_results, page_token)` | READ | Search threads. |
| `get_thread(thread_id, format)` | READ | Fetch one thread. |
| `list_drafts(max_results, page_token, query)` | READ | List drafts. |
| `get_draft(draft_id, format)` | READ | Fetch one draft. |
| `get_attachment(message_id, attachment_id)` | READ | Base64 attachment bytes. |
| `list_history(start_history_id, label_id, history_types, max_results, page_token)` | READ | Mailbox history since `start_history_id`. |
| `list_filters()` | READ | List Gmail filters. |
| `list_send_as()` | READ | List send-as aliases. |
| `get_vacation_settings()` | READ | Vacation auto-responder settings. |
| `send_email(to, subject, body_text, body_html, cc, bcc, sender, reply_to, thread_id)` | WRITE | Send a message via the `raw` endpoint. |
| `modify_labels(message_id, add_label_ids, remove_label_ids)` | WRITE | Add/remove labels on one message. |
| `modify_thread_labels(thread_id, add_label_ids, remove_label_ids)` | WRITE | Add/remove labels on every message in a thread. |
| `untrash_message(message_id)` | WRITE | Restore a message from Trash. |
| `untrash_thread(thread_id)` | WRITE | Restore a thread from Trash. |
| `create_draft(...)` | WRITE | Create a new draft. |
| `update_draft(draft_id, ...)` | WRITE | Replace a draft. |
| `send_draft(draft_id)` | WRITE | Send an existing draft. |
| `create_label(name, label_list_visibility, message_list_visibility)` | WRITE | Create a user label. |
| `update_label(label_id, patch)` | WRITE | Patch a user label. |
| `batch_modify_messages(message_ids, add_label_ids, remove_label_ids)` | WRITE | Up to 1000 messages per call. |
| `create_filter(criteria, action)` | WRITE | Create a Gmail filter. |
| `update_vacation_settings(settings)` | WRITE | Patch the vacation auto-responder. |
| `trash_message(message_id)` | DELETE (destructive) | Move to Trash. |
| `trash_thread(thread_id)` | DELETE (destructive) | Move a whole thread to Trash. |
| `delete_draft(draft_id)` | DELETE (destructive) | Permanently delete a draft. |
| `delete_label(label_id)` | DELETE (destructive) | Delete a user label. |
| `batch_delete_messages(message_ids)` | DELETE (destructive) | Permanently delete up to 1000 messages. |
| `delete_filter(filter_id)` | DELETE (destructive) | Delete a Gmail filter. |

### Agent-ready behavior (Gmail — gold-standard)

`search_messages` is the canonical reference for the agent-ready
pattern. By default it returns compact summaries: each match gets a
stable `message_ref` (`message_1`, `message_2`, ...), `sender`, `to`,
`subject`, `received_at` (Date header), `snippet`, and `label_ids`.
Summary mode caps `max_results` at 10 because each candidate requires
a per-message `format=metadata` fetch — set `include_metadata=False`
to skip summarization and receive the raw Gmail wire format
(`{"messages": [{"id": ...}], "nextPageToken": ...}`).

Raw Gmail message and thread IDs are omitted by default because they
are internal handles, not useful for final-answer text. Set
`include_ids=True` only when a follow-up Gmail tool needs a raw
`message_id` or `thread_id` (for example before calling
`get_message`, `modify_labels`, or `trash_message`). When the
summary mode trims `max_results`, the response carries
`requestedMaxResults` and `summaryLimit` so the caller can detect the
cap.

```python
# Summary mode — safe for final answers, no internal IDs.
gmail.search_messages("is:unread")
# { "messages": [{"message_ref": "message_1",
#                  "sender": "Alice <alice@example>",
#                  "subject": "Q3 plan", "received_at": "...",
#                  "snippet": "...", "label_ids": ["UNREAD", "INBOX"]}],
#   "nextPageToken": "...", "resultSizeEstimate": 42 }

# Opt-in raw IDs (only when a follow-up tool needs them).
gmail.search_messages("is:unread", include_ids=True)

# Raw API passthrough (no summarization, no per-message fetch).
gmail.search_messages("is:unread", include_metadata=False)
```

### Destructive tools (Gmail)

`trash_message` / `trash_thread` move to Trash (recoverable until
purged via `untrash_*`). `delete_draft`, `delete_label`,
`batch_delete_messages`, and `delete_filter` are tagged
`destructive=True` and are **not** reversible. `batch_delete_messages`
in particular wipes up to 1000 messages with no Trash hop — confirm
with the user before invoking. Filter them out at registration with
`exclude_tags=["destructive"]`.

## GoogleCalendarToolSet tools

| Tool | Permission | Description |
| --- | --- | --- |
| `list_calendars(max_results, include_ids)` | READ | Calendars in the user's calendar list; compact `calendar_ref` summaries. |
| `get_calendar(calendar_id)` | READ | Fetch a calendar resource. Accepts ID, calendar dict, or `"primary"`. |
| `list_events(calendar_id, time_min, time_max, q, max_results, page_token, single_events, order_by, include_metadata, include_ids)` | READ | List events; compact `event_ref` summaries by default. |
| `get_event(event_id, calendar_id)` | READ | Fetch one event. Accepts raw ID or event dict. |
| `list_event_instances(event_id, calendar_id, time_min, time_max, max_results, page_token, include_metadata, include_ids)` | READ | Instances of a recurring event. |
| `free_busy(time_min, time_max, calendars, timezone)` | READ | Free/busy intervals across calendars. Each entry accepts a calendar dict. |
| `list_acl(calendar_id)` | READ | Access-control rules on a calendar. |
| `list_settings()` | READ | User-level Calendar settings. |
| `get_colors()` | READ | Event/calendar color palette. |
| `create_event(summary, start, end, calendar_id, description, location, attendees, send_updates)` | WRITE | Create an event. |
| `update_event(event_id, patch, calendar_id, send_updates)` | WRITE | Patch an event. Accepts raw ID or event dict. |
| `quick_add_event(text, calendar_id, send_updates)` | WRITE | Create an event from natural-language text. |
| `move_event(event_id, destination_calendar_id, calendar_id, send_updates)` | WRITE | Move an event between calendars. |
| `respond_to_event(event_id, response_status, attendee_email, calendar_id, send_updates)` | WRITE | RSVP via attendee patch. |
| `create_calendar(summary, description, time_zone, location)` | WRITE | Create a secondary calendar. |
| `update_calendar(calendar_id, patch)` | WRITE | Patch a calendar's metadata. |
| `clear_calendar(calendar_id)` | WRITE | Clear all events from the primary calendar. |
| `create_acl_rule(calendar_id, scope_type, role, scope_value, send_notifications)` | WRITE | Grant a role on a calendar. |
| `delete_event(event_id, calendar_id, send_updates)` | DELETE (destructive) | Delete an event. Accepts raw ID or event dict. |
| `delete_calendar(calendar_id)` | DELETE (destructive) | Delete a secondary calendar (refuses `primary`). |
| `delete_acl_rule(calendar_id, rule_id)` | DELETE (destructive) | Revoke an ACL rule. |

### Agent-ready behavior (Calendar)

`list_calendars` returns `calendar_ref` summaries with display name,
description, time zone, access role, and a `primary` flag. Default
`max_results` is 25. `list_events` and `list_event_instances` return
`event_ref` summaries with summary, start/end times, location,
organizer, attendees, status, and `html_link` (which is safe to surface
to the user). Default `max_results` is 25. Raw Google calendar /
event IDs are hidden unless `include_ids=True`;
`include_metadata=False` returns the raw Google response.

Calendar IDs are tolerantly resolved everywhere: `calendar_id`
arguments accept a raw email-like ID, the literal `"primary"`, or the
calendar dict from `list_calendars(include_ids=True)`. `event_id`
arguments accept a raw ID or the event dict from `list_events`.

```python
calendar.list_events(time_min="2026-05-16T00:00:00Z",
                     time_max="2026-05-17T00:00:00Z")
# { "events": [{"event_ref": "event_1", "summary": "Standup",
#                "start_time": "...", "end_time": "...",
#                "organizer": "Alice <...>", "attendees": [...],
#                "html_link": "https://calendar.google.com/..."}] }
```

### Destructive tools (Calendar)

`delete_event`, `delete_calendar`, and `delete_acl_rule` are tagged
`destructive=True`. `delete_calendar` refuses to delete the primary
calendar. `clear_calendar` is irreversible in effect (drops every
event from the calendar) even though it is a plain WRITE — confirm
with the user.

## GoogleDriveToolSet tools

| Tool | Permission | Description |
| --- | --- | --- |
| `search_files(query, page_size, page_token, order_by, include_metadata, include_ids, fields)` | READ | Drive v3 search; compact `file_ref` / `folder_ref` summaries. |
| `get_file(file_id, fields)` | READ | Metadata for one file. Accepts raw ID or file dict. |
| `download_file(file_id)` | READ | Download as base64 bytes. Accepts raw ID or file dict. |
| `list_revisions(file_id, page_size, page_token)` | READ | List revisions of a file. |
| `get_revision(file_id, revision_id)` | READ | Metadata for one revision. |
| `list_permissions(file_id)` | READ | Permissions on a file. |
| `list_drives(page_size, page_token)` | READ | Shared drives accessible to the user. |
| `list_changes(page_token, include_removed, page_size)` | READ | Drive change events since a page token. |
| `get_changes_start_page_token()` | READ | Start page token for the changes feed. |
| `get_about(fields)` | READ | Drive `about` info (user, quota, max upload size). |
| `export_file(file_id, mime_type)` | EXPORT | Export a Google Doc/Sheet/Slide. Accepts raw ID or file dict. |
| `create_folder(name, parent_id)` | WRITE | Create a folder. |
| `trash_file(file_id)` | WRITE | Move to Trash (recoverable). Accepts raw ID or file dict. |
| `untrash_file(file_id)` | WRITE | Restore from Trash. Accepts raw ID or file dict. |
| `rename_file(file_id, new_name)` | WRITE | Patch `name`. Accepts raw ID or file dict. |
| `update_file_metadata(file_id, patch)` | WRITE | Patch arbitrary metadata fields. Accepts raw ID or file dict. |
| `copy_file(file_id, name, parent_id)` | WRITE | Copy to a parent with optional new name. |
| `move_file(file_id, add_parent_id, remove_parent_id)` | WRITE | Change parents via `addParents`/`removeParents`. |
| `empty_trash()` | DELETE (destructive) | Permanently delete every file in the trash. |
| `create_shortcut(target_id, name, parent_id)` | WRITE | Create a Drive shortcut. |
| `share_file(file_id, permission_type, role, email_address, domain, send_notification_email)` | WRITE | Add a permission. |
| `update_permission(file_id, permission_id, patch)` | WRITE | Patch a permission (typically `role`). |
| `delete_file(file_id)` | DELETE (destructive) | Permanently delete a file or folder. Accepts raw ID or file dict. |
| `delete_revision(file_id, revision_id)` | DELETE (destructive) | Delete a revision. |
| `revoke_permission(file_id, permission_id)` | DELETE (destructive) | Revoke a permission. |

### Agent-ready behavior (Drive)

`search_files` returns compact summaries by default: each item has a
stable `file_ref` (or `folder_ref` for folders), `name`, `mime_type`,
`modified_time`, `size`, and `owner`. Default `page_size` is 25. Raw
Drive IDs are hidden unless `include_ids=True` (needed for
`download_file`, `delete_file`, `update_file_metadata`, etc.);
`include_metadata=False` returns the raw Google response unchanged.
`nextPageToken` is preserved for pagination.

Most read/write tools (`get_file`, `download_file`, `export_file`,
`trash_file`, `untrash_file`, `rename_file`, `update_file_metadata`,
`copy_file`, `move_file`, `delete_file`, revision and permission
tools) accept either a raw `file_id` string or the file dict from
`search_files(include_ids=True)` — the connector extracts the ID for
you.

```python
drive.search_files("mimeType='application/vnd.google-apps.spreadsheet'")
# { "files": [{"file_ref": "file_1", "name": "Q3 plan",
#               "mime_type": "application/vnd.google-apps.spreadsheet",
#               "modified_time": "...", "owner": "Alice"}],
#   "nextPageToken": null }
```

### Destructive tools (Drive)

`delete_file`, `empty_trash`, `delete_revision`, and
`revoke_permission` are tagged `destructive=True` and are not
reversible — `delete_file` is a hard delete (use `trash_file` for the
recoverable equivalent), and `empty_trash` wipes the entire trash for
the user. Confirm with the user before invoking, or filter at
registration with `exclude_tags=["destructive"]`.

## Filtering tools at registration

Each toolset above ships its **full** Gmail/Calendar/Drive tool surface.
When an agent only needs a slice, narrow at registration time:

```python
# Read-only Gmail for a summarization agent.
agent.add_toolset(GmailToolSet(token=cache), include_tags=["read"])

# Send-only Gmail for a notification agent.
agent.add_toolset(GmailToolSet(token=cache), include=["send_email"])

# Calendar without the destructive deletes.
agent.add_toolset(
    GoogleCalendarToolSet(token=cache),
    exclude_tags=["destructive"],
)

# Drive minus exports/downloads (which produce large payloads).
agent.add_toolset(
    GoogleDriveToolSet(token=cache),
    exclude=["export_file", "download_file"],
)
```

See [Writing your own toolset](../toolsets.md#filtering-at-registration)
for the full filter API.

## Notes

- `download_file` and `export_file` return their payloads as base64-encoded
  strings so they remain JSON-safe when piped through agent tools.
- Google APIs return paginated results via `nextPageToken`. The Drive and
  Gmail tools accept the token directly; combine with `PageTokenPaginator`
  for unbounded iteration.
- For domain-wide delegation, configure the OAuth flow with a service
  account that has the necessary scope and use the resulting bearer token
  with these connectors unchanged.
