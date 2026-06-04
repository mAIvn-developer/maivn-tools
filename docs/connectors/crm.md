# CRM

Sales and revenue CRMs. Each toolset gives an agent a uniform surface
over contacts, companies, deals, and pipeline records for one platform.
Every connector follows the standard `@toolset` / `@toolify` shape and
the agent-ready toolset pattern (compact summaries by default, opt-in
raw IDs, tolerant write inputs).

## HubSpotToolSet

`HubSpotToolSet` wraps the HubSpot CRM v3 API. It authenticates with a
bearer token — either a private-app token (recommended) or an
OAuth-issued access token.

```python
from maivn_tools import HubSpotToolSet, register_connector

connector = HubSpotToolSet(token=secrets["HUBSPOT_TOKEN"])
```

`metadata.scopes` lists the most common scope keys
(`crm.objects.contacts.read`, `crm.objects.deals.write`, etc.).
Configure your private app with the scopes the agent needs.

### Object types

The standard CRM tools take an `object_type` argument from the allowed
set: `contacts`, `companies`, `deals`, `tickets`. Engagement tools take
an `engagement_type` argument from: `notes`, `calls`, `emails`,
`meetings`, `tasks`. Any other value raises `ValueError`.

### Tools

**Object CRUD.** `list_objects`, `get_object`, `search_objects`,
`create_object`, `update_object`, `archive_object` (destructive).

**Engagements.** `list_engagements`, `create_note`, `create_task`,
`create_email_engagement` (logs only — does not send).

**Pipelines, owners, properties.** `list_pipelines`, `get_pipeline`,
`list_owners`, `get_owner`, `list_properties`, `get_property`.

**Associations.** `associate_objects`, `remove_association`
(destructive).

**Batch operations.** `batch_read_objects`, `batch_create_objects`,
`batch_update_objects`, `batch_archive_objects` (destructive).

### Agent-ready behavior

- `list_objects` and `search_objects` return compact summaries by
  default. Each summary carries a stable `object_ref`
  (`object_1`, `object_2`, ...), the `object_type`, an `updated_at`
  timestamp, and a small set of useful display properties chosen per
  object type (e.g. `email`/`firstname`/`lastname` for contacts,
  `dealname`/`dealstage`/`amount` for deals).
- Default `limit` is 25 for both `list_objects` and `search_objects`
  (max 100). `list_engagements` and `list_owners` use the same 25
  default.
- Raw HubSpot record IDs are hidden by default. Pass `include_ids=True`
  to add `object_id` to each summary — only do this when a follow-up
  tool needs the raw handle, not for human-facing answers.
- Pass `include_metadata=False` to receive the raw HubSpot
  `{"results": [...], "paging": {...}}` payload unchanged.
- `get_object`, `update_object`, `archive_object`,
  `batch_read_objects`, and `batch_archive_objects` all accept either a
  raw ID string, a summary dict returned by the list/search tools
  (`include_ids=True` mode), or a list of such dicts. The connector
  resolves the canonical HubSpot ID from `object_id` or `id`.

### Destructive tools

`archive_object`, `remove_association`, and `batch_archive_objects`
carry `destructive=True`. Filter them out with
`exclude_tags=["destructive"]` when constructing a non-destructive
agent. Archive moves records to the HubSpot recycle bin; batch archive
removes every listed record in one call.

### Example: summary-mode search

```python
agent.add_toolset(HubSpotToolSet(token=secrets["HUBSPOT_TOKEN"]))

# Default: compact summaries, IDs hidden, safe to show in final answers.
response = connector.search_objects(
    "deals",
    query="acme",
    limit=10,
)
# response == {
#   "objects": [
#     {"object_ref": "object_1", "object_type": "deals",
#      "dealname": "ACME renewal", "dealstage": "negotiation",
#      "amount": "45000", "updated_at": "..."},
#     ...
#   ],
#   "paging": {...},
# }
```

To pipe a summary straight into a write tool:

```python
hits = connector.search_objects(
    "deals", query="acme", include_ids=True
)["objects"]
connector.update_object("deals", hits[0], {"dealstage": "closedwon"})
```

## SalesforceToolSet

`SalesforceToolSet` wraps the Salesforce REST API. It authenticates
with an OAuth bearer token. Use `OAuth2Flow` against the Salesforce
token URL (or the JWT-bearer flow) to obtain the access token; the
connector accepts a string, an `OAuth2Token`, or a token callable.

```python
from maivn_tools import SalesforceToolSet, register_connector

connector = SalesforceToolSet(
    instance_url="https://acme.my.salesforce.com",
    token=token_cache,
    api_version="v59.0",
)
```

### Tools

**Schema and identity.** `describe_global`, `describe_object`,
`list_versions`, `list_limits`, `get_user_info`, `get_recent_items`.

**Queries.** `soql_query` (`SELECT` / `FIND`; mutations rejected),
`query_more`, `query_all` (incl. soft-deleted records), `sosl_search`.

**Record CRUD.** `get_record`, `create_record`, `update_record`,
`upsert_record`, `delete_record` (destructive).

**Reports and dashboards.** `list_reports`, `get_report`, `run_report`,
`list_dashboards`.

**Composite (batch).** `composite_request`,
`composite_sobjects_create`, `composite_sobjects_update`,
`composite_sobjects_delete` (destructive).

### Agent-ready behavior

- `soql_query` returns compact summaries by default. Each summary
  carries a stable `record_ref` (`record_1`, `record_2`, ...), the
  `object_type` (taken from the record's `attributes.type`), and any
  of the common display fields that were actually selected (`Name`,
  `Subject`, `Title`, `FirstName`, `LastName`, `Email`, `Phone`,
  `Status`, `StageName`, `Amount`, `CloseDate`, `Type`).
- Salesforce `Id` values are hidden by default. Pass `include_ids=True`
  to add `record_id` to each summary — needed before calling
  `get_record`, `update_record`, `delete_record`, or
  `composite_sobjects_delete`.
- Pass `include_metadata=False` on `soql_query` to receive the raw
  Salesforce response, including `nextRecordsUrl` for pagination via
  `query_more`. `query_all` and `sosl_search` always return the raw
  Salesforce payload.
- `get_record`, `update_record`, `delete_record`, and
  `composite_sobjects_delete` accept a raw `Id` string, a record dict
  returned by `soql_query` (with `include_ids=True`), or a list of
  such dicts. The connector resolves the ID from `Id`, `id`, or
  `record_id`.

### Destructive tools

`delete_record` and `composite_sobjects_delete` carry
`destructive=True`. Both move rows to the recycle bin (or destroy them
if the bin is purged). Confirm with the user before invoking either,
or filter them with `exclude_tags=["destructive"]`.

### Example: summary-mode SOQL

```python
agent.add_toolset(SalesforceToolSet(instance_url=..., token=token_cache))

response = connector.soql_query(
    "SELECT Id, Name, StageName, Amount FROM Opportunity "
    "WHERE StageName = 'Negotiation' LIMIT 20"
)
# response == {
#   "records": [
#     {"record_ref": "record_1", "object_type": "Opportunity",
#      "Name": "ACME renewal", "StageName": "Negotiation",
#      "Amount": 45000},
#     ...
#   ],
#   "totalSize": 12, "done": True,
# }
```

To follow up with an update, request raw IDs:

```python
hits = connector.soql_query(
    "SELECT Id, Name FROM Opportunity WHERE Name LIKE 'ACME%'",
    include_ids=True,
)["records"]
connector.update_record("Opportunity", hits[0], {"StageName": "Closed Won"})
```

### Safety

- `soql_query` rejects any statement whose first token is not `SELECT`
  or `FIND`. Use the explicit CRUD tools for writes.
- `query_all` rejects anything other than `SELECT`; `sosl_search`
  rejects anything other than `FIND`.
- `object_name` and external-id field names are validated against
  `^[A-Za-z][A-Za-z0-9_]*$` so they cannot inject path segments.
- The connector advertises only the standard `api` and `refresh_token`
  scopes; configure your Connected App accordingly.
