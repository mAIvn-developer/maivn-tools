# Microsoft Graph connectors

Three connectors cover the Microsoft 365 / Outlook surfaces most agents
need:

- `OutlookMailToolSet` — mail.
- `OutlookCalendarToolSet` — calendars and events.
- `MicrosoftFilesToolSet` — OneDrive and SharePoint documents.

All three authenticate with an Azure AD-issued OAuth 2.0 bearer token. Use
`OAuth2Flow` against the v2 endpoint:

```python
from maivn_tools import OAuth2EndpointConfig, OAuth2Flow

flow = OAuth2Flow(
    client_id=AZURE_CLIENT_ID,
    client_secret=AZURE_CLIENT_SECRET,
    endpoints=OAuth2EndpointConfig(
        authorize_url=f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize",
        token_url=f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
    ),
)
```

The connectors accept a token string, an `OAuth2Token`, or a callable
returning one — the same shape as the Google Workspace connectors.

> **Agent-ready pattern.** Across the three connectors, list / search
> tools return compact human-readable summaries by default with a
> stable `_ref` field (`folder_ref`, `message_ref`, `calendar_ref`,
> `event_ref`, `item_ref`). Default page size is 25.
> Raw Graph GUIDs are hidden unless you pass `include_ids=True`; pass
> `include_metadata=False` to get the raw Graph response with every
> field. Write tools that target a single item (`get_message`,
> `move_message`, `delete_message`, `update_event`, `delete_event`,
> `download_file`, `delete_item`, ...) accept either a raw ID string
> or the summary dict from the corresponding list/search tool — the
> connector extracts the ID for you. Well-known folder names
> (`inbox`, `drafts`, `sentitems`, `deleteditems`, `junkemail`,
> `outbox`, `archive`) are also accepted wherever `folder_id` is
> expected.

## OutlookMailToolSet

```python
from maivn_tools import OutlookMailToolSet

mail = OutlookMailToolSet(token=token_cache)
```

| Tool | Permission | Description |
| --- | --- | --- |
| `list_folders(top, include_ids)` | READ | List mail folders; compact `folder_ref` summaries. |
| `get_folder(folder_id)` | READ | Fetch one mail folder. Accepts raw ID or folder dict. |
| `list_messages_in_folder(folder_id, top, filter, select, order_by, include_metadata, include_ids)` | READ | List messages inside a folder; compact `message_ref` summaries. |
| `search_messages(search, filter, top, select, order_by, include_metadata, include_ids)` | READ | Search via `$search` or `$filter`; compact `message_ref` summaries. |
| `get_message(message_id)` | READ | Fetch one message. Accepts raw ID or message dict. |
| `list_attachments(message_id)` | READ | Attachments on a message. Accepts raw ID or message dict. |
| `get_attachment(message_id, attachment_id)` | READ | One attachment (base64 content). |
| `list_mail_rules(folder_id)` | READ | Message rules attached to a folder (default Inbox). |
| `list_categories()` | READ | User's master category list. |
| `send_email(to, subject, body_text, body_html, cc, bcc, save_to_sent)` | WRITE | Submit via `sendMail`. |
| `create_draft(to, subject, body_text, body_html, cc, bcc)` | WRITE | Create a draft message. |
| `send_draft(message_id)` | WRITE | Send a previously-created draft. Accepts raw ID or draft dict. |
| `update_message(message_id, patch)` | WRITE | Patch fields like `isRead`, `flag`, `categories`. Accepts raw ID or message dict. |
| `mark_read(message_id, is_read)` | WRITE | Toggle `isRead`. Accepts raw ID or message dict. |
| `flag_message(message_id, flag_status)` | WRITE | Set follow-up flag (`notFlagged`/`flagged`/`complete`). |
| `reply_to_message(message_id, comment, reply_all)` | WRITE | Reply or reply-all. Accepts raw ID or message dict. |
| `forward_message(message_id, to, comment)` | WRITE | Forward to recipients. Accepts raw ID or message dict. |
| `copy_message(message_id, destination_folder_id)` | WRITE | Copy a message to another folder. Both args accept dicts. |
| `move_message(message_id, destination_folder_id)` | WRITE | Move a message. Both args accept dicts. |
| `add_attachment(message_id, name, content_base64, content_type)` | WRITE | Attach base64 content to a draft. |
| `create_folder(display_name, parent_folder_id)` | WRITE | Create a mail folder (optionally nested). |
| `update_folder(folder_id, patch)` | WRITE | Patch folder fields (typically rename). |
| `create_mail_rule(rule, folder_id)` | WRITE | Add a message rule to a folder. |
| `delete_message(message_id)` | DELETE (destructive) | Move to Deleted Items. Accepts raw ID or message dict. |
| `delete_folder(folder_id)` | DELETE (destructive) | Delete a folder and its messages. |
| `delete_mail_rule(rule_id, folder_id)` | DELETE (destructive) | Remove a message rule. |

The connector defaults to `me` as the user identifier; pass
`user="ops@example.test"` to act against a different mailbox when the
token has the required admin scope.

### Agent-ready behavior

`list_folders` returns `folder_ref` summaries with `display_name`,
`total_item_count`, `unread_item_count`. `search_messages` and
`list_messages_in_folder` return `message_ref` summaries with sender,
to-list, subject, `received_at`, `preview` (Graph's `bodyPreview`),
and `is_read`. Default `top` is 25. Raw Graph IDs are hidden unless
`include_ids=True`; `include_metadata=False` returns the raw Graph
response.

```python
outlook_mail.search_messages(search="invoice")
# { "messages": [{"message_ref": "message_1",
#                  "sender": "Alice <alice@example>",
#                  "subject": "May invoice", "received_at": "...",
#                  "preview": "...", "is_read": false}],
#   "nextLink": null }
```

`get_message`, `move_message`, `copy_message`, `update_message`,
`mark_read`, `flag_message`, `reply_to_message`, `forward_message`,
`list_attachments`, `add_attachment`, `delete_message`, and
`send_draft` all accept either a raw `message_id` string or a message
dict from a list response. `folder_id` arguments
(`list_messages_in_folder`, `move_message`, etc.) accept a raw ID, a
folder dict, or a well-known name (`inbox`, `drafts`, ...).

### Destructive tools

`delete_message`, `delete_folder`, and `delete_mail_rule` are tagged
`destructive=True`. `delete_message` moves the message to Deleted
Items (recoverable from there); `delete_folder` removes the folder
and all messages it contains. Confirm with the user before invoking.

## OutlookCalendarToolSet

| Tool | Permission | Description |
| --- | --- | --- |
| `list_calendars(include_ids)` | READ | List user calendars; compact `calendar_ref` summaries. |
| `get_calendar(calendar_id)` | READ | Return a calendar (`primary` for default). |
| `list_calendar_groups()` | READ | Calendar groups for the user. |
| `list_events(calendar_id, start, end, top, filter, include_metadata, include_ids)` | READ | List events; switches to `calendarView` when `start`+`end` supplied. Compact `event_ref` summaries. |
| `get_event(event_id)` | READ | Fetch one event. Accepts raw ID or event dict. |
| `list_event_instances(event_id, start, end, top, include_metadata, include_ids)` | READ | Instances of a recurring event. |
| `free_busy(start, end, schedules, interval)` | READ | `getSchedule` free/busy. |
| `find_meeting_times(attendees, meeting_duration_minutes, time_constraint, location_constraint, max_candidates)` | READ | Suggest free slots across attendees. |
| `create_event(subject, start, end, body, attendees, location, calendar_id)` | WRITE | Create an event. |
| `update_event(event_id, patch)` | WRITE | Patch an event. Accepts raw ID or event dict. |
| `respond_to_event(event_id, response, comment, send_response)` | WRITE | RSVP (`accept`/`decline`/`tentativelyAccept`). Accepts raw ID or event dict. |
| `cancel_event(event_id, comment)` | WRITE | Cancel an organized event (sends notices). Accepts raw ID or event dict. |
| `forward_event(event_id, to_recipients, comment)` | WRITE | Forward an event to additional recipients. |
| `create_calendar(name, color)` | WRITE | Create a new calendar. |
| `update_calendar(calendar_id, patch)` | WRITE | Patch a calendar's metadata. |
| `delete_event(event_id)` | DELETE (destructive) | Delete an event. Accepts raw ID or event dict. |
| `delete_calendar(calendar_id)` | DELETE (destructive) | Delete a calendar. |

### Agent-ready behavior

`list_calendars` returns `calendar_ref` summaries with name, color,
`is_default`, `can_edit`. `list_events` and `list_event_instances`
return `event_ref` summaries with subject, start/end times, location
(display name), organizer, attendees, `is_online_meeting`,
`is_all_day`. Default `top` is 25. Raw Graph event/calendar IDs are
hidden unless `include_ids=True`; `include_metadata=False` returns
the raw Graph response. `get_calendar` accepts a raw ID, a calendar
dict, or the literal `"primary"`.

```python
outlook_calendar.list_events(start="2026-05-16T00:00:00",
                              end="2026-05-17T00:00:00")
# { "events": [{"event_ref": "event_1", "subject": "Standup",
#                "start_time": "...", "end_time": "...",
#                "organizer": "Alice <...>", "attendees": [...],
#                "is_online_meeting": true}] }
```

`get_event`, `update_event`, `respond_to_event`, `cancel_event`,
`forward_event`, `delete_event`, and `list_event_instances` all
accept either a raw `event_id` string or an event dict from
`list_events`. `calendar_id` similarly accepts raw IDs or calendar
dicts.

### Destructive tools

`delete_event` and `delete_calendar` are tagged `destructive=True`.
`cancel_event` sends cancellation notices and is irreversible in
effect — confirm with the user before calling.

## MicrosoftFilesToolSet

```python
from maivn_tools import MicrosoftFilesToolSet

drive = MicrosoftFilesToolSet(token=token_cache, drive_root="me/drive")
sharepoint = MicrosoftFilesToolSet(token=token_cache, drive_root="sites/<site-id>/drive")
```

| Tool | Permission | Description |
| --- | --- | --- |
| `list_root_children(top, include_metadata, include_ids)` | READ | List items at the drive root; compact `item_ref` / `folder_ref` summaries. |
| `list_children(item_id, top, include_metadata, include_ids)` | READ | List items in a specific folder. Accepts raw ID or item dict. |
| `get_item(item_id)` | READ | Metadata for one item. Accepts raw ID or item dict. |
| `get_item_by_path(path)` | READ | Look up an item by path relative to the drive root. |
| `search_files(query, top, include_metadata, include_ids)` | READ | Drive-wide search; compact `item_ref` / `folder_ref` summaries. |
| `download_file(item_id)` | READ | Download as base64 bytes. Accepts raw ID or item dict. |
| `list_versions(item_id, top)` | READ | List versions of an item. Accepts raw ID or item dict. |
| `list_permissions(item_id)` | READ | Permissions on an item. Accepts raw ID or item dict. |
| `get_drive()` | READ | Drive metadata (quota, owner, drive type). |
| `list_recent(top)` | READ | Recently-accessed items (raw response). |
| `list_shared_with_me(top)` | READ | Items shared with the user (raw response). |
| `upload_small_file(parent_id, name, content_base64, content_type)` | WRITE | Single-shot upload up to 4 MB. |
| `create_upload_session(parent_id, name, conflict_behavior)` | WRITE | Open a resumable session for files >4 MB. |
| `create_folder(parent_id, name, conflict_behavior)` | WRITE | Create a folder. |
| `rename_item(item_id, new_name)` | WRITE | Patch `name`. Accepts raw ID or item dict. |
| `update_item_metadata(item_id, patch)` | WRITE | Patch arbitrary drive-item fields. Accepts raw ID or item dict. |
| `move_item(item_id, new_parent_id)` | WRITE | Move under a new parent. Accepts raw ID or item dict. |
| `copy_item(item_id, new_parent_id, new_name)` | WRITE | Async copy (returns monitor URL). Accepts raw ID or item dict. |
| `restore_version(item_id, version_id)` | WRITE | Restore a previous version. Accepts raw ID or item dict. |
| `create_share_link(item_id, link_type, scope, password, expiration_datetime)` | WRITE | Create a sharing link. Accepts raw ID or item dict. |
| `invite_to_item(item_id, recipients, roles, require_sign_in, send_invitation, message)` | WRITE | Invite specific recipients. Accepts raw ID or item dict. |
| `delete_item(item_id)` | DELETE (destructive) | Delete a file or folder (moves to user's recycle bin). Accepts raw ID or item dict. |
| `revoke_permission(item_id, permission_id)` | DELETE (destructive) | Revoke a permission. |

### Agent-ready behavior

`list_root_children`, `list_children`, and `search_files` return
compact summaries by default. Each item has `item_ref` (or
`folder_ref` for folders), `name`, `kind` (`file` / `folder`),
`size`, `modified_time`, `owner`, `web_url`, and `mime_type` for
files. Default `top` is 25. Raw Graph item IDs are hidden unless
`include_ids=True`; `include_metadata=False` returns the raw provider
response.

```python
ms_files.search_files("invoice")
# { "items": [{"item_ref": "item_1", "name": "May invoice.xlsx",
#               "kind": "file", "size": 12345,
#               "modified_time": "...", "owner": "Alice",
#               "web_url": "https://...",
#               "mime_type": "application/vnd.openxmlformats-..."}],
#   "next_link": null }
```

`get_item`, `download_file`, `list_children`, `list_versions`,
`list_permissions`, `rename_item`, `update_item_metadata`,
`move_item`, `copy_item`, `restore_version`, `create_share_link`,
`invite_to_item`, and `delete_item` all accept either a raw item ID
string or the item dict from `search_files` / `list_root_children` /
`list_children`.

### Destructive tools

`delete_item` and `revoke_permission` are tagged `destructive=True`.
`delete_item` moves the item to the user's recycle bin (recoverable
from there); `revoke_permission` removes a share with no undo.
Confirm with the user before invoking.

## Filtering at registration

```python
# Read-only Outlook for a triage agent.
agent.add_toolset(OutlookMailToolSet(token=cache), include_tags=["read"])

# Calendar without destructive operations.
agent.add_toolset(OutlookCalendarToolSet(token=cache), exclude_tags=["destructive"])

# Drive read + safe writes only (no deletes, no permission revocation).
agent.add_toolset(MicrosoftFilesToolSet(token=cache), exclude_tags=["destructive"])
```

See [Writing your own toolset](../toolsets.md#filtering-at-registration)
for the full filter API.

### Scopes

The connectors advertise the standard Graph scopes through
`metadata.scopes`. At minimum, request the `*.Read` scope for read-only
agents and `*.ReadWrite` for write tools. SharePoint Files require the
`Sites.Read.All` / `Sites.ReadWrite.All` scopes on the application
registration.
