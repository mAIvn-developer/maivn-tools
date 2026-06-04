# Analytics & BI

Product analytics, customer data platforms, and BI dashboards. Every
connector follows the standard `@toolset` / `@toolify` shape.

## Agent-ready behavior (overview)

List / search tools across this category return compact summaries with
stable display refs (`cohort_ref`, `user_ref`, `event_ref`,
`insight_ref`, `person_ref`, `source_ref`, `destination_ref`,
`warehouse_ref`, `look_ref`, `dashboard_ref`, `card_ref`,
`project_ref`, `workbook_ref`, `view_ref`, `datasource_ref`,
`dataset_ref`, `member_ref`). Raw provider IDs (numeric IDs, UUIDs,
slugs) are hidden by default and exposed via `include_ids=True` when
a follow-up tool (`get_*`, `delete_*`, `cancel_*`) needs them. Default
page size is 25 unless otherwise noted.

Write tools that take an identifier (Hex `get_project`, `run_project`,
`get_run_status`, `list_project_runs`, `cancel_run`; Sigma
`get_workbook`, `export_workbook`; Tableau `get_workbook`,
`refresh_workbook`, `delete_workbook`; Metabase `get_card`,
`run_card_query`, `get_dashboard`; Looker `get_look`, `run_look`,
`get_dashboard`) accept a raw ID string or the dict returned by the
matching list tool.

Mixpanel and the ingest-only paths (Amplitude `upload_events`,
Segment `track`/`identify`/`group`/`page`/`batch`, PostHog
`capture`, Mixpanel `track`/`import_events`/`engage`/`group_update`)
are write tools that take inline payloads rather than identifiers --
no summary treatment is needed.

Destructive tools across this group (require user confirmation):
`cancel_run` (Hex), `delete_workbook` (Tableau).

## AmplitudeToolSet

```python
from maivn_tools import AmplitudeToolSet

connector = AmplitudeToolSet(
    api_key=secrets["AMPLITUDE_API_KEY"],
    secret_key=secrets["AMPLITUDE_SECRET_KEY"],
    region="US",
)
```

Tools: `upload_events`, `identify`, `event_segmentation`,
`funnel_analysis`, `retention_analysis`, `get_user_activity`,
`get_user_search`, `list_cohorts`, `get_cohort`, `export_raw_events`.

**Agent-ready behavior**

- `get_user_search`: summary with `user_ref`, plus user name / email /
  device fields. Pass `include_ids=True` for the raw `user_id` (needed
  by `get_user_activity`).
- `list_cohorts`: summary with `cohort_ref`, name, count, type,
  `last_computed`. Opt in for `cohort_id` (needed by `get_cohort`).

## MixpanelToolSet

```python
from maivn_tools import MixpanelToolSet

connector = MixpanelToolSet(
    project_token=secrets["MIXPANEL_PROJECT_TOKEN"],
    service_account_user=secrets["MIXPANEL_SA_USER"],
    service_account_secret=secrets["MIXPANEL_SA_SECRET"],
    project_id=int(secrets["MIXPANEL_PROJECT_ID"]),
    region="US",
)
```

Tools: `track`, `import_events`, `engage`, `group_update`,
`events_query`, `segmentation`, `funnels`, `retention`,
`export_events`, `query_jql`.

**Agent-ready behavior**

- Mixpanel's surface is ingest + query rather than list/get -- no
  resource-listing tools, so no `_ref` summaries. Read tools
  (`events_query`, `segmentation`, `funnels`, `retention`,
  `export_events`, `query_jql`) return the raw provider responses
  unchanged because the agent typically wants the raw rows / counts.

## SegmentToolSet

```python
from maivn_tools import SegmentToolSet

connector = SegmentToolSet(
    write_key=secrets.get("SEGMENT_WRITE_KEY"),           # for Tracking API
    public_api_token=secrets.get("SEGMENT_PUBLIC_TOKEN"), # for source/destination management
)
```

Either credential works on its own; supply both for full coverage.
Tools: `track`, `identify`, `group`, `page`, `batch`, `list_workspaces`,
`list_sources`, `get_source`, `list_destinations`, `list_warehouses`.

**Agent-ready behavior**

- `list_sources`: summary with `source_ref`, name, slug,
  source-config preview. Raw `source_id` hidden; opt in with
  `include_ids=True` (needed by `get_source`).
- `list_destinations`: summary with `destination_ref`, name, slug,
  enabled state, parent source name. Opt in for `destination_id`.
- `list_warehouses`: summary with `warehouse_ref`, name, slug, enabled
  state. Opt in for `warehouse_id`.

## PostHogToolSet

```python
from maivn_tools import PostHogToolSet

connector = PostHogToolSet(
    personal_api_key=secrets["POSTHOG_PERSONAL_KEY"],
    project_api_key=secrets.get("POSTHOG_PROJECT_KEY"),  # needed for /capture/
    project_id=int(secrets["POSTHOG_PROJECT_ID"]),
    host="app.posthog.com",
)
```

Tools: `capture`, `list_events`, `list_insights`, `get_insight`,
`query_hogql`, `list_feature_flags`, `create_feature_flag`,
`update_feature_flag`, `list_persons`, `list_cohorts`.

**Agent-ready behavior**

- `list_events`: summary with `event_ref`, event name, distinct ID,
  timestamp, properties preview. Raw event UUIDs hidden; opt in with
  `include_ids=True`.
- `list_insights`: summary with `insight_ref`, name, description,
  type, dashboard count. Opt in for the numeric `insight_id` (needed
  by `get_insight`).
- `list_persons`: summary with `person_ref`, name, email, properties
  preview, `created_at`. Opt in for the person `id` / `distinct_id`.

## LookerToolSet

```python
from maivn_tools import LookerToolSet

connector = LookerToolSet(
    base_url="https://acme.cloud.looker.com:19999",
    access_token=token,
)
```

Looker login (`POST /login` to exchange client-id/secret for an access
token) is left to the caller. Tools: `me`, `list_looks`, `get_look`,
`run_look`, `list_dashboards`, `get_dashboard`, `create_query`,
`run_query`, `list_users`, `search_content`.

**Agent-ready behavior**

- `list_looks`: summary with `look_ref`, title, description, view
  count, `updated_at`. Raw `look_id` hidden; opt in with
  `include_ids=True` (needed by `get_look`, `run_look`).
- `list_dashboards`: summary with `dashboard_ref`, title, description,
  view count, `updated_at`. Opt in for `dashboard_id` (needed by
  `get_dashboard`).
- `list_users`: summary with `user_ref`, display name, email, role
  count. Opt in for `user_id`.

```python
looks = connector.list_looks(include_ids=True)
data = connector.run_look(looks["looks"][0], result_format="json")
```

## TableauToolSet

```python
from maivn_tools import TableauToolSet

connector = TableauToolSet(
    server_url="https://us-east-1.online.tableau.com",
    site_id=session["site_id"],
    auth_token=session["token"],
)
```

Sign-in (personal access token / username+password) is left to the
caller -- supply `auth_token` + `site_id` already exchanged. Tools:
`get_server_info`, `list_sites`, `list_projects`, `list_workbooks`,
`get_workbook`, `list_views_for_workbook`, `query_view_data`,
`list_datasources`, `refresh_datasource`, `refresh_workbook`,
`get_job`, `delete_workbook` (destructive).

**Agent-ready behavior**

- `list_projects`: summary with `project_ref`, name, description,
  parent project name. Opt in for `project_id`.
- `list_workbooks`: summary with `workbook_ref`, name, description,
  owner name, project name, `updated_at`. Raw workbook UUID hidden;
  opt in with `include_ids=True` (needed by `get_workbook`,
  `refresh_workbook`, `delete_workbook`).
- `list_views_for_workbook`: summary with `view_ref`, name,
  `content_url`, view count. Opt in for `view_id` (needed by
  `query_view_data`).
- `list_datasources`: summary with `datasource_ref`, name, type,
  owner, project. Opt in for `datasource_id`.
- Tolerant inputs: `get_workbook`, `refresh_workbook`,
  `delete_workbook` accept a raw UUID or a workbook dict from
  `list_workbooks(include_ids=True)`.
- Destructive: `delete_workbook`. Confirm before invoking.

## MetabaseToolSet

```python
from maivn_tools import MetabaseToolSet

connector = MetabaseToolSet(
    base_url="https://metabase.example",
    api_key=secrets["METABASE_API_KEY"],
)
```

For session-based auth use `key_kind="session"`. Tools:
`get_current_user`, `list_databases`, `list_cards`, `get_card`,
`run_card_query`, `list_dashboards`, `get_dashboard`,
`list_collections`, `query_dataset`, `search`.

**Agent-ready behavior**

- `list_cards`: summary with `card_ref`, name, description, display
  type, collection name. Raw numeric `card_id` hidden; opt in with
  `include_ids=True` (needed by `get_card`, `run_card_query`).
- `list_dashboards`: summary with `dashboard_ref`, name, description,
  collection name. Opt in for `dashboard_id`.

## HexToolSet

```python
from maivn_tools import HexToolSet

connector = HexToolSet(api_token=secrets["HEX_TOKEN"])
```

Tools: `list_projects`, `get_project`, `run_project`, `get_run_status`,
`list_project_runs`, `cancel_run` (destructive).

**Agent-ready behavior**

- `list_projects`: summary with `project_ref`, title, description,
  state. Raw Hex project IDs hidden; opt in with `include_ids=True`
  (needed by `get_project`, `run_project`, `get_run_status`,
  `list_project_runs`, `cancel_run`).
- Destructive: `cancel_run`. Confirm before invoking (in-progress
  runs cannot be resumed).

## SigmaToolSet

```python
from maivn_tools import SigmaToolSet

connector = SigmaToolSet(access_token=token)
```

Defaults to the AWS-US region. Tools: `list_workbooks`, `get_workbook`,
`export_workbook`, `list_datasets`, `get_dataset`, `list_members`,
`list_schedules`, `create_embed`.

**Agent-ready behavior**

- `list_workbooks`: summary with `workbook_ref`, name, description,
  owner email, `updated_at`. Raw workbook IDs hidden; opt in with
  `include_ids=True` (needed by `get_workbook`, `export_workbook`).
- `list_datasets`: summary with `dataset_ref`, name, description,
  `updated_at`. Opt in for `dataset_id`.
- `list_members`: summary with `member_ref`, full name, email,
  member type. Opt in for `member_id`.
