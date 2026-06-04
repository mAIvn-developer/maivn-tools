# Support & ITSM

Customer-support helpdesks and IT-service-management platforms. Every
connector follows the standard `@toolset` / `@toolify` shape and the
agent-ready toolset pattern (compact summaries by default, opt-in raw
IDs, tolerant write inputs).

## ZendeskToolSet

`ZendeskToolSet` wraps the Zendesk Support REST API v2. It
authenticates with HTTP Basic using `<email>/token` as the username and
an API token created from the Zendesk admin console.

```python
from maivn_tools import ZendeskToolSet, register_connector

connector = ZendeskToolSet(
    subdomain="acme",
    email="ops@acme.com",
    api_token=secrets["ZENDESK_API_TOKEN"],
)
```

Either supply `subdomain` (and the connector will target
`https://<subdomain>.zendesk.com`) or override `base_url` for sandbox
instances.

### Tools

**Tickets.** `list_tickets`, `search_tickets`, `get_ticket`,
`list_ticket_comments`, `create_ticket`, `update_ticket`, `add_comment`,
`merge_tickets`, `add_tags_to_ticket`, `remove_tags_from_ticket`,
`delete_ticket` (destructive).

**Users, organizations, groups.** `list_users`, `search_users`,
`get_user`, `create_user`, `update_user`, `delete_user` (destructive),
`list_organizations`, `get_organization`, `create_organization`,
`list_groups`, `get_group`.

**Macros and views.** `list_macros`, `show_macro_application`
(preview-only), `list_views`, `execute_view`.

**Field definitions.** `list_ticket_fields`, `list_user_fields`.

### Agent-ready behavior

- `search_tickets` and `list_tickets` return compact summaries by
  default. Each summary carries a stable `ticket_ref`
  (`ticket_1`, `ticket_2`, ...), plus `subject`, `status`, `priority`,
  `requester_id`, `updated_at`, and `tags`. The search summary filters
  the heterogeneous `/search` response down to ticket-shaped hits.
- Default `per_page` is 25 for both `search_tickets` and `list_tickets`
  (max 100).
- Raw Zendesk numeric IDs are hidden by default. Pass
  `include_ids=True` to add `ticket_id` to each summary — needed
  before calling `get_ticket`, `update_ticket`, `add_comment`,
  `merge_tickets`, or `delete_ticket`.
- Pass `include_metadata=False` on either tool to receive the raw
  Zendesk payload, including `next_page` / `previous_page` /
  `count` pagination cursors. `search_users` uses
  `include_metadata=False` under the hood so it always returns the
  raw search response.
- `get_ticket`, `update_ticket`, `add_comment`, `delete_ticket`, and
  the source / target arguments of `merge_tickets` all accept a raw
  integer ID, a numeric string, a ticket summary dict, or a list of
  such dicts. The connector reads `ticket_id` or `id` to resolve the
  canonical integer.

### Destructive tools

`delete_ticket` and `delete_user` carry `destructive=True`. Delete
operations soft-delete (recoverable from the deleted-records view) but
should still be confirmed with the user, or filtered out with
`exclude_tags=["destructive"]`.

### Example: summary-mode search

```python
agent.add_toolset(
    ZendeskToolSet(subdomain="acme", email="ops@acme.com",
                   api_token=secrets["ZENDESK_API_TOKEN"])
)

response = connector.search_tickets("status:open priority:high")
# response == {
#   "tickets": [
#     {"ticket_ref": "ticket_1", "subject": "Login broken",
#      "status": "open", "priority": "high",
#      "requester_id": 12345, "updated_at": "...", "tags": [...]},
#     ...
#   ],
#   "count": 7,
# }
```

To act on a result, request raw IDs:

```python
hits = connector.search_tickets(
    "status:open assignee:me", include_ids=True
)["tickets"]
connector.add_comment(hits[0], "Investigating now.", public=False)
```

## ServiceNowToolSet

`ServiceNowToolSet` wraps the ServiceNow Now Platform Table REST API.

```python
from maivn_tools import ServiceNowToolSet

connector = ServiceNowToolSet(
    instance_url="https://acme.service-now.com",
    username="ops",
    password=secrets["SNOW_PASSWORD"],
)
```

Table names are validated against `^[A-Za-z][A-Za-z0-9_]*$` so they
cannot inject URL path segments.

### Tools

`list_records`, `get_record`, `create_record`, `update_record`,
`delete_record` (destructive), `list_incidents`, `create_incident`,
`create_change_request`, `aggregate`, `list_attachments`,
`delete_attachment` (destructive), `find_user`.

### Agent-ready behavior

- `list_records` and `list_incidents` return compact summaries by
  default. Each summary carries a stable `record_ref`
  (`record_1`, `record_2`, ...), the source `table`, and any of the
  common user-facing fields that are present on the row
  (`number`, `short_description`, `state`, `priority`, `urgency`,
  `assigned_to`, `assignment_group`, `category`, `sys_updated_on`).
  `find_user` reuses `list_records` against `sys_user`, so it returns
  the same summary shape.
- Default `limit` is 25 on both `list_records` and `list_incidents`
  (max 1000).
- ServiceNow `sys_id` GUIDs are hidden by default. Pass
  `include_ids=True` to add `sys_id` to each summary — needed before
  calling `get_record`, `update_record`, or `delete_record`.
- Pass `include_metadata=False` to receive the raw ServiceNow
  `{"result": [...]}` payload unchanged.
- `get_record`, `update_record`, and `delete_record` accept a raw
  `sys_id` GUID string, a record summary dict, or a list of such
  dicts. The connector resolves the ID from `sys_id` or `id`.

### Destructive tools

`delete_record` and `delete_attachment` carry `destructive=True`.
`delete_record` removes the row from the table; `delete_attachment`
cannot be undone. Filter them out with
`exclude_tags=["destructive"]` for non-destructive agents.

### Example: summary-mode list

```python
agent.add_toolset(
    ServiceNowToolSet(instance_url="https://acme.service-now.com",
                      username="ops", password=secrets["SNOW_PASSWORD"])
)

response = connector.list_incidents(
    query="active=true^priority<=2",
    limit=10,
)
# response == {
#   "records": [
#     {"record_ref": "record_1", "table": "incident",
#      "number": "INC0010101", "short_description": "Email outage",
#      "state": "2", "priority": "1", "assigned_to": {...},
#      "sys_updated_on": "..."},
#     ...
#   ],
# }
```

To follow up with an update, request raw IDs:

```python
hits = connector.list_incidents(
    query="number=INC0010101", include_ids=True
)["records"]
connector.update_record("incident", hits[0], {"state": "6"})
```
