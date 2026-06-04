# Knowledge bases & no-code

Wiki connectors (Notion, Confluence) and the Airtable no-code database
share enough of a workflow shape — read pages / records, write
pages / records, attach metadata — that they're grouped together here.
Every connector follows the agent-ready toolset pattern (compact
summaries by default, opt-in raw IDs, tolerant write inputs).

## NotionToolSet

`NotionToolSet` wraps the [Notion API](https://developers.notion.com/).
It uses an integration secret or OAuth bearer token plus a
`Notion-Version` header.

```python
from maivn_tools import NotionToolSet, register_connector

connector = NotionToolSet(token=secrets["NOTION_TOKEN"])
register_connector(agent, connector)
```

### Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `get_self()` | READ | Return the bot user the token belongs to. |
| `get_user(user_id)` / `list_users()` | READ | User lookup. |
| `search(query, filter_type, sort_direction, page_size, include_metadata, include_ids, ...)` | READ | Search across pages and databases. |
| `get_page(page_id)` / `get_page_property(page_id, property_id, ...)` | READ | Fetch one page or one property. |
| `create_page(parent, properties, children, icon, cover)` | WRITE | Create a page under a database or page parent. |
| `update_page(page_id, properties, archived, icon, cover)` | WRITE | Patch page properties or state. |
| `archive_page(page_id)` | DELETE (destructive) | Soft-delete a page. |
| `get_database(database_id)` | READ | Database metadata. |
| `query_database(database_id, filter, sorts, page_size, include_metadata, include_ids, ...)` | READ | Query database rows. |
| `create_database(parent, title, properties, ...)` | WRITE | Create a database. |
| `update_database(database_id, title, description, properties)` | WRITE | Update title / schema. |
| `get_block(block_id)` / `list_block_children(block_id, ...)` | READ | Fetch blocks. |
| `append_block_children(block_id, children, after)` | WRITE | Append child blocks. |
| `update_block(block_id, fields)` | WRITE | Update one block. |
| `delete_block(block_id)` | DELETE (destructive) | Archive a block. |
| `list_comments(block_id, ...)` | READ | Comments on a page/block. |
| `create_comment(parent, discussion_id, rich_text)` | WRITE | Add a comment. |

### Agent-ready behavior

- `search` and `query_database` return compact summaries by default.
  Each summary carries a stable ref — `page_ref` (`page_1`, ...) for
  page objects, `result_ref` for non-page hits — plus the `object`
  type (`page`/`database`), `title`, `url`, `last_edited_time`,
  `archived`, and `parent_type` (when present).
- Default `page_size` is 25 on both `search` and `query_database`
  (max 100). `list_users` and `list_block_children` retain their
  Notion-native 100 default.
- Notion `id` GUIDs are hidden by default. Pass `include_ids=True`
  to add `page_id` to each summary — needed before calling
  `get_page`, `update_page`, `archive_page`, or `get_page_property`.
- Pass `include_metadata=False` on `search` or `query_database` to
  receive the raw Notion response, including `has_more` and
  `next_cursor` pagination cursors.
- `get_page`, `get_page_property`, `update_page`, and `archive_page`
  accept either a raw Notion ID string, a summary dict from `search`
  or `query_database`, or a list of such dicts. The connector
  resolves the ID from `page_id` or `id`.

### Destructive tools

`archive_page` and `delete_block` carry `destructive=True`. Both move
content to Notion's trash. Confirm with the user, or filter them out
with `exclude_tags=["destructive"]`.

### Example: summary-mode search

```python
agent.add_toolset(NotionToolSet(token=secrets["NOTION_TOKEN"]))

response = connector.search("runbook", filter_type="page", page_size=10)
# response == {
#   "results": [
#     {"page_ref": "page_1", "object": "page",
#      "title": "On-call runbook", "url": "https://www.notion.so/...",
#      "last_edited_time": "...", "archived": False,
#      "parent_type": "database_id"},
#     ...
#   ],
#   "has_more": False, "next_cursor": None,
# }
```

To act on a result, request raw IDs:

```python
hits = connector.search(
    "Q3 plan", filter_type="page", include_ids=True
)["results"]
connector.update_page(hits[0], archived=True)
```

## ConfluenceToolSet

`ConfluenceToolSet` wraps Atlassian Confluence Cloud REST API v1.

```python
from maivn_tools import ConfluenceToolSet

connector = ConfluenceToolSet(
    base_url="https://acme.atlassian.net",
    email="ops@acme.com",
    api_token=secrets["CONFLUENCE_API_TOKEN"],
)
```

### Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `get_current_user()` / `get_user(account_id)` | READ | Identity lookups. |
| `list_spaces(space_key, type, ...)` / `get_space(space_key)` | READ | Spaces. |
| `create_space(key, name, ...)` / `delete_space(space_key)` | WRITE / DELETE (destructive) | Manage spaces. |
| `list_content(type, space_key, title, limit, include_metadata, include_ids, ...)` | READ | List pages, blog posts, comments, or attachments. |
| `get_content(content_id, expand, version)` | READ | Fetch one item. |
| `create_page(space_key, title, body, parent_id, representation)` | WRITE | Create a page. |
| `update_page(content_id, title, body, version, representation)` | WRITE | Update a page. |
| `delete_content(content_id)` | DELETE (destructive) | Trash content. |
| `list_children(content_id, type, ...)` | READ | List child content. |
| `list_versions(content_id, ...)` | READ | Version history. |
| `list_labels(content_id, ...)` / `add_label(content_id, label, prefix)` / `remove_label(content_id, label)` | READ / WRITE / DELETE (destructive) | Labels. |
| `list_comments(content_id, location, depth, ...)` / `create_comment(container_id, body, representation)` | READ / WRITE | Comments. |
| `search(cql, limit, include_metadata, include_ids, ...)` / `search_content(cql, limit, include_metadata, include_ids, ...)` | READ | CQL search. |
| `list_attachments(content_id, media_type, filename, ...)` | READ | List attachments. |

### Agent-ready behavior

- `list_content`, `search`, and `search_content` return compact
  summaries by default. Each summary carries a stable `page_ref`
  (`page_1`, `page_2`, ...) plus `title`, `type`, `status`,
  `space_key`, `version`, and the `url` (webui link). Search results
  additionally include the `excerpt` and `resultGlobalContainer`
  fields when present.
- Default `limit` is 25 on `list_content`, `search`, and
  `search_content`. `list_spaces` defaults to 25 (max 250).
- Confluence numeric content IDs are hidden by default. Pass
  `include_ids=True` to add `content_id` to each summary — needed
  before calling `get_content`, `update_page`, `delete_content`,
  `list_children`, `list_versions`, `list_labels`, `add_label`,
  `remove_label`, `list_comments`, or `list_attachments`.
- Pass `include_metadata=False` on `list_content`, `search`, or
  `search_content` to receive the raw Confluence response, including
  `start`, `limit`, `size`, `totalSize`, and `_links` cursors.
- All of the per-content tools above accept either a raw numeric ID
  string, a summary dict from `list_content` / `search` /
  `search_content` / `get_content`, or a list of such dicts. The
  connector resolves the ID from `content_id`, `page_id`, or `id`.
- Space tools use the human-readable `key` (e.g. `ENG`) — this is the
  canonical handle and is safe to surface in final answers.

### Destructive tools

`delete_space`, `delete_content`, and `remove_label` carry
`destructive=True`. `delete_space` schedules a long-running deletion
of the space and all its content; `delete_content` trashes a page
(call again to purge). Confirm with the user, or filter them out
with `exclude_tags=["destructive"]`.

### Example: summary-mode search

```python
agent.add_toolset(
    ConfluenceToolSet(base_url="https://acme.atlassian.net",
                      email="ops@acme.com",
                      api_token=secrets["CONFLUENCE_API_TOKEN"])
)

response = connector.search(
    "space = ENG AND text ~ 'runbook' ORDER BY lastmodified DESC",
    limit=10,
)
# response == {
#   "results": [
#     {"page_ref": "page_1", "title": "On-call runbook",
#      "type": "page", "status": "current", "space_key": "ENG",
#      "version": 12, "url": "/spaces/ENG/pages/...",
#      "excerpt": "...", "resultGlobalContainer": "Engineering"},
#     ...
#   ],
#   "start": 0, "limit": 10, "size": 4, "totalSize": 4,
# }
```

To follow up with an update, request raw IDs:

```python
hits = connector.search(
    "title = 'On-call runbook'", include_ids=True
)["results"]
page = connector.get_content(hits[0], expand="body.storage,version")
connector.update_page(
    hits[0],
    title=page["title"],
    body=page["body"]["storage"]["value"] + "<p>Updated.</p>",
    version=page["version"]["number"] + 1,
)
```

## AirtableToolSet

`AirtableToolSet` wraps the [Airtable Web + Meta APIs](https://airtable.com/developers/web/api/introduction).
It accepts a personal access token (`pat...`) or an OAuth bearer.

```python
from maivn_tools import AirtableToolSet

connector = AirtableToolSet(access_token=secrets["AIRTABLE_PAT"])
```

### Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `list_bases(offset)` | READ | List bases the token can access. |
| `get_base_schema(base_id, include)` | READ | Tables + fields for a base. |
| `create_table(base_id, name, fields, description)` | WRITE | Add a table to a base. |
| `create_field(base_id, table_id, name, field_type, options, description)` | WRITE | Add a field to a table. |
| `list_records(base_id, table_id_or_name, view, fields, filter_by_formula, sort, max_records, page_size, offset, cell_format, include_metadata, include_ids, ...)` | READ | List records with full filter / sort / pagination support. |
| `get_record(base_id, table_id_or_name, record_id)` | READ | Fetch one record. |
| `create_records(base_id, table_id_or_name, records, typecast, return_fields_by_field_id)` | WRITE | Create up to 10 records per call. |
| `update_records(base_id, table_id_or_name, records, typecast, replace, perform_upsert)` | WRITE | PATCH (partial) or PUT (replace); supports upsert via `perform_upsert.fieldsToMergeOn`. |
| `delete_records(base_id, table_id_or_name, record_ids)` | DELETE (destructive) | Delete up to 10 records per call. |
| `list_comments(base_id, table_id_or_name, record_id, page_size, offset)` | READ | Record comments. |
| `create_comment(base_id, table_id_or_name, record_id, text)` | WRITE | Post a comment. |
| `delete_comment(base_id, table_id_or_name, record_id, comment_id)` | DELETE (destructive) | Delete a comment. |
| `list_webhooks(base_id)` | READ | Webhooks on a base. |
| `create_webhook(base_id, notification_url, specification)` | WRITE | Create a webhook (MAC secret returned once). |
| `delete_webhook(base_id, webhook_id)` | DELETE (destructive) | Delete a webhook. |
| `list_webhook_payloads(base_id, webhook_id, cursor, limit)` | READ | Pull pending webhook payloads. |
| `get_current_user()` | READ | `/v0/meta/whoami`. |

### Agent-ready behavior

- `list_records` returns compact summaries by default. Each summary
  carries a stable `record_ref` (`record_1`, `record_2`, ...), the
  original Airtable `fields` dict for the row, and the
  `created_time`.
- Default `page_size` is 25 on `list_records`. `list_comments` and
  webhook helpers retain their Airtable-native 100 default.
- Raw Airtable record IDs (`rec...`) are hidden by default. Pass
  `include_ids=True` to add `record_id` to each summary — needed
  before calling `update_records`, `delete_records`, `list_comments`,
  `create_comment`, or `delete_comment`.
- Pass `include_metadata=False` to receive the raw Airtable payload
  (records with raw `id` plus `offset` pagination cursor).
- `delete_records` accepts a list whose items can be raw Airtable IDs
  (`"rec..."`), full record dicts from `list_records`
  (`include_ids=True`) or `get_record`, or a mixed list. The
  connector resolves each entry from `record_id` or `id`.

### Destructive tools

`delete_records`, `delete_comment`, and `delete_webhook` carry
`destructive=True`. `delete_records` cannot be undone; the others
remove the underlying resource. Confirm with the user, or filter them
out with `exclude_tags=["destructive"]`.

### Example: summary-mode list

```python
agent.add_toolset(AirtableToolSet(access_token=secrets["AIRTABLE_PAT"]))

response = connector.list_records(
    base_id="appXXXXXXXXXXXXXX",
    table_id_or_name="Customers",
    filter_by_formula="{Status} = 'Active'",
    page_size=10,
)
# response == {
#   "records": [
#     {"record_ref": "record_1",
#      "fields": {"Name": "ACME", "Status": "Active", "MRR": 4500},
#      "created_time": "..."},
#     ...
#   ],
#   "offset": "...",   # only when more results exist
# }
```

To delete matching rows, request raw IDs and pipe them straight
through:

```python
hits = connector.list_records(
    base_id="appXXXXXXXXXXXXXX",
    table_id_or_name="Customers",
    filter_by_formula="{Status} = 'Cancelled'",
    include_ids=True,
)["records"]
connector.delete_records(
    base_id="appXXXXXXXXXXXXXX",
    table_id_or_name="Customers",
    record_ids=hits[:10],   # dicts accepted; the connector resolves IDs
)
```

Airtable enforces a max of 10 records per write call; the connector
raises `ValueError` before the API does. ``table_id_or_name`` accepts
either the stable ``tbl...`` ID or the human-readable table name (the
connector URL-encodes either form).

See [Permissions and dry-run](../permissions.md) for the permission model
shared by all toolsets.
