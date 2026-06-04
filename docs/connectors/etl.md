# ETL & data movement

Sources, destinations, and sync orchestration for analytics pipelines —
Fivetran, Airbyte, dbt Cloud, Hightouch, Census, and Stitch. Every
connector follows the standard `@toolset` / `@toolify` shape.

## Agent-ready behavior (overview)

All list tools across this category return compact summaries with
stable display refs (`group_ref`, `connector_ref`, `destination_ref`,
`user_ref`, `workspace_ref`, `source_ref`, `connection_ref`,
`job_ref`, `project_ref`, `environment_ref`, `model_ref`, `sync_ref`,
`run_ref`). Raw provider IDs (Fivetran connector / group IDs, Airbyte
UUIDs, dbt Cloud numeric IDs, Hightouch / Census IDs, Stitch source
IDs) are hidden by default and exposed via `include_ids=True` when a
follow-up tool needs them.

Follow-up tools (`get_connector`, `update_connector`, `trigger_sync`,
`resync_connector`, `delete_connector`, `get_destination`,
`get_source`, `delete_source`, `get_connection`, `get_job`,
`cancel_job`, `get_project`, `trigger_job_run`, `get_run`,
`cancel_run`, `list_run_artifacts`, `get_run_artifact`, `get_model`,
`get_sync`, `get_sync_run`) accept either the raw ID or the dict from
the matching list tool.

Destructive tools across this group (require user confirmation):
`delete_connector` (Fivetran); `delete_source` and `cancel_job`
(Airbyte); `cancel_run` (dbt Cloud); `delete_source` (Stitch).

## FivetranToolSet

```python
from maivn_tools import FivetranToolSet

connector = FivetranToolSet(
    api_key=secrets["FIVETRAN_API_KEY"],
    api_secret=secrets["FIVETRAN_API_SECRET"],
)
```

Tools: `list_groups`, `list_connectors`, `get_connector`,
`update_connector`, `trigger_sync`, `resync_connector`,
`delete_connector` (destructive), `get_connector_schemas`,
`list_destinations`, `get_destination`, `list_users`.

**Agent-ready behavior**

- `list_groups`: summary with `group_ref`, name, created. Raw
  `group_id` hidden; opt in with `include_ids=True` (needed by
  `list_connectors(group_id=...)`).
- `list_connectors`: summary with `connector_ref`, name, schema,
  service, sync frequency, paused state, status. Opt in for
  `connector_id` (needed by `get_connector`, `update_connector`,
  `trigger_sync`, `resync_connector`, `delete_connector`,
  `get_connector_schemas`).
- `list_destinations`: summary with `destination_ref`, name, service,
  region, time_zone_offset. Opt in for `destination_id` (needed by
  `get_destination`).
- `list_users`: summary with `user_ref`, email, given/family name,
  verified, active, role. Opt in for `user_id`.
- Tolerant inputs: `get_connector`, `update_connector`,
  `trigger_sync`, `resync_connector`, `delete_connector`,
  `get_connector_schemas`, `get_destination` accept a raw ID or the
  resource dict from the matching list tool.
- Destructive: `delete_connector`. Confirm before invoking.

```python
conns = connector.list_connectors(group_id="abc", include_ids=True)
connector.trigger_sync(conns["connectors"][0])  # dict accepted
```

## AirbyteToolSet

```python
from maivn_tools import AirbyteToolSet

connector = AirbyteToolSet(access_token=secrets["AIRBYTE_TOKEN"])
```

Defaults to Airbyte Cloud (`https://api.airbyte.com`); override
`base_url` for self-hosted instances. Tools: `list_workspaces`,
`list_sources`, `get_source`, `create_source`, `delete_source`
(destructive), `list_destinations`, `list_connections`,
`get_connection`, `create_connection`, `trigger_sync`, `trigger_reset`,
`list_jobs`, `get_job`, `cancel_job` (destructive).

**Agent-ready behavior**

- `list_workspaces`: summary with `workspace_ref`, name, data
  residency. Opt in for `workspace_id`.
- `list_sources`: summary with `source_ref`, name, source type. Opt
  in for the raw source UUID (needed by `get_source`,
  `delete_source`).
- `list_destinations`: summary with `destination_ref`, name,
  destination type. Opt in for the raw UUID.
- `list_connections`: summary with `connection_ref`, name, status,
  schedule, source name, destination name. Opt in for the raw UUID
  (needed by `get_connection`, `trigger_sync`, `trigger_reset`).
- `list_jobs`: summary with `job_ref`, job type, status, created /
  ended timestamps, duration. Opt in for the numeric `job_id` (needed
  by `get_job`, `cancel_job`).
- Tolerant inputs: `get_source`, `delete_source`, `get_connection`,
  `trigger_sync`, `trigger_reset`, `get_job`, `cancel_job` accept a
  raw UUID/int or the dict from the matching list tool.
- Destructive: `delete_source`, `cancel_job`. Confirm before
  invoking.

## DbtCloudToolSet

```python
from maivn_tools import DbtCloudToolSet

connector = DbtCloudToolSet(
    account_id=int(secrets["DBT_ACCOUNT_ID"]),
    api_token=secrets["DBT_TOKEN"],
)
```

Tools: `list_projects`, `get_project`, `list_environments`,
`list_jobs`, `get_job`, `trigger_job_run`, `list_runs`, `get_run`,
`cancel_run` (destructive), `list_run_artifacts`, `get_run_artifact`.

**Agent-ready behavior**

- `list_projects`: summary with `project_ref`, name, state, created.
  Raw numeric project IDs hidden; opt in with `include_ids=True`
  (needed by `get_project`, `list_environments`, `list_jobs`).
- `list_environments`: summary with `environment_ref`, name, type
  (dev / prd), `dbt_version`, project name. Opt in for the raw
  numeric ID.
- `list_jobs`: summary with `job_ref`, name, schedule, state. Opt in
  for the numeric `job_id` (needed by `get_job`, `trigger_job_run`,
  `list_runs`).
- `list_runs`: summary with `run_ref`, human-readable status,
  schedule trigger, duration, finished timestamp. Opt in for
  `run_id` (needed by `get_run`, `cancel_run`,
  `list_run_artifacts`).
- Destructive: `cancel_run`. Confirm before invoking.

## HightouchToolSet

```python
from maivn_tools import HightouchToolSet

connector = HightouchToolSet(api_key=secrets["HIGHTOUCH_KEY"])
```

Reverse-ETL: pulls modeled data from your warehouse out to SaaS tools.
Tools: `list_sources`, `get_source`, `list_destinations`,
`list_models`, `get_model`, `list_syncs`, `get_sync`, `trigger_sync`,
`list_sync_runs`, `get_sync_run`.

**Agent-ready behavior**

- `list_sources`: summary with `source_ref`, name, type, created.
  Raw source IDs hidden; opt in with `include_ids=True` (needed by
  `get_source`).
- `list_destinations`: summary with `destination_ref`, name, type,
  created. Opt in for the raw ID.
- `list_models`: summary with `model_ref`, name, source name. Opt in
  for `model_id` (needed by `get_model`).
- `list_syncs`: summary with `sync_ref`, name, destination, model,
  schedule. Opt in for `sync_id` (needed by `get_sync`,
  `trigger_sync`, `list_sync_runs`).
- `list_sync_runs`: summary with `run_ref`, status, start / finish
  timestamps. Opt in for the raw run ID.

## CensusToolSet

```python
from maivn_tools import CensusToolSet

connector = CensusToolSet(secret_token=secrets["CENSUS_TOKEN"])
```

Census uses HTTP Basic with `bearer:<secret>`; the toolset handles
that internally. Tools: `list_sources`, `get_source`,
`list_destinations`, `list_models`, `get_model`, `list_syncs`,
`get_sync`, `trigger_sync`, `list_sync_runs`, `get_sync_run`.

**Agent-ready behavior**

- `list_sources`: summary with `source_ref`, name, type, created.
  Raw IDs hidden; opt in with `include_ids=True`.
- `list_destinations`: summary with `destination_ref`, name, type.
  Opt in for the raw ID.
- `list_models`: summary with `model_ref`, name, created. Opt in for
  `model_id`.
- `list_syncs`: summary with `sync_ref`, name, destination, model,
  schedule. Opt in for `sync_id` (needed by `get_sync`,
  `trigger_sync`, `list_sync_runs`).
- `list_sync_runs`: summary with `run_ref`, status, start / finish
  timestamps. Opt in for the run ID.

## StitchToolSet

```python
from maivn_tools import StitchToolSet

connector = StitchToolSet(
    access_token=secrets["STITCH_TOKEN"],
    region="na",
)
```

Tools: `list_sources`, `get_source`, `create_source`, `update_source`,
`delete_source` (destructive), `list_streams`, `update_stream`,
`get_destination`, `trigger_extraction`, `get_replication_summary`.

**Agent-ready behavior**

- `list_sources`: summary with `source_ref`, name, type, schedule
  (frequency in minutes), paused state. Raw source IDs hidden; opt
  in with `include_ids=True` (needed by `get_source`,
  `update_source`, `delete_source`, `list_streams`,
  `trigger_extraction`, `get_replication_summary`).
- Tolerant inputs: `get_source`, `update_source`, `delete_source`,
  `list_streams`, `trigger_extraction`, `get_replication_summary`
  accept a raw source ID or a source dict from
  `list_sources(include_ids=True)`.
- Destructive: `delete_source`. Confirm before invoking.
