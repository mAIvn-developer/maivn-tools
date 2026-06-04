# Cloud & observability

Toolsets for telemetry pipelines, incident response, on-call, and
infrastructure control planes. Every connector follows the standard
`@toolset` / `@toolify` shape.

## Agent-ready behavior (overview)

All list / search tools in this group return compact summaries by
default with a stable `_ref` field (`log_ref`, `monitor_ref`,
`dashboard_ref`, `issue_ref`, `incident_ref`, `service_ref`,
`schedule_ref`, `oncall_ref`, `user_ref`, `alert_ref`, `app_ref`,
`index_ref`, `search_ref`, `folder_ref`, `component_ref`,
`subscriber_ref`, `zone_ref`, `record_ref`, `worker_ref`,
`bucket_ref`, `pod_ref`, `namespace_ref`, `deployment_ref`).
Raw provider IDs are hidden unless you pass
`include_ids=True`. Where the tool exposes `include_metadata=False`,
that returns the raw provider response untouched. Default page size is
25; some tools cap absolute limits to provider maxima (1000 logs, 100
users, etc.).

Write tools that take an identifier accept either a raw ID/UID/int or
the dict from the corresponding list/get tool. This includes
`get_monitor`, `delete_monitor`, `mute_monitor`, `get_issue`,
`update_issue`, `delete_issue`, `list_events_for_issue`,
`get_incident`, `update_incident`, `acknowledge_incident`,
`delete_alert_policy`, `get_dashboard_by_uid`,
`delete_dashboard_by_uid`, `update_component`, `update_incident`,
`delete_incident`, `get_zone`, `list_dns_records`, `update_dns_record`,
`delete_dns_record`, `purge_cache`.

Destructive tools across this group (require user confirmation):
`delete_monitor`, `delete_issue`, `cancel_search_job`,
`delete_alert_policy`, `delete_dashboard_by_uid`, `delete_incident`,
`delete_dns_record`, `purge_cache`, `delete_pod`.

## DatadogToolSet

```python
from maivn_tools import DatadogToolSet

connector = DatadogToolSet(
    api_key=secrets["DD_API_KEY"],
    app_key=secrets["DD_APP_KEY"],     # required for most read APIs
    site="datadoghq.com",
)
```

Tools: `search_logs`, `submit_logs`, `query_metrics`, `submit_metrics`,
`list_monitors`, `get_monitor`, `create_monitor`, `delete_monitor`
(destructive), `mute_monitor`, `post_event`, `list_dashboards`,
`get_dashboard`.

**Agent-ready behavior**

- `search_logs` (default limit 25, hard max 1000; summaries capped at
  25): summary with `log_ref`, `timestamp`, `service`, `status`,
  `host`, `message`, optional `tags`. Raw Datadog event IDs hidden
  unless `include_ids=True`; pass `include_metadata=False` for the raw
  provider response. Cursor pagination preserved as `next_cursor`.
- `list_monitors` (default page size 25): summary with `monitor_ref`,
  `name`, `type`, `state`, `message`, `tags`. Numeric IDs hidden by
  default; opt in with `include_ids=True` (needed for `get_monitor`,
  `delete_monitor`, `mute_monitor`).
- `list_dashboards`: summary with `dashboard_ref`, `title`,
  `description`, `layout_type`, `url`. Opt in with `include_ids=True`
  for `dashboard_id` (needed for `get_dashboard`).
- Tolerant inputs: `get_monitor`, `delete_monitor`, and `mute_monitor`
  accept an int, a monitor dict, or a list of such.
- Destructive: `delete_monitor`. Confirm before invoking.

```python
hot = connector.search_logs(
    query="status:error service:checkout",
    from_time="now-15m",
    to_time="now",
)
```

## SentryToolSet

```python
from maivn_tools import SentryToolSet

connector = SentryToolSet(auth_token=secrets["SENTRY_TOKEN"])
```

Tools: `list_organizations`, `list_projects`, `get_project`,
`list_issues`, `get_issue`, `update_issue`, `delete_issue`
(destructive), `list_events_for_issue`, `list_releases`,
`create_release`, `list_alert_rules`.

**Agent-ready behavior**

- `list_issues` (default limit 25, hard max 100; summaries capped at
  25): summary with `issue_ref`, `title`, `culprit`, `status`,
  `level`, `count`, `last_seen`, `permalink`. Raw Sentry issue IDs
  hidden; opt in with `include_ids=True` (needed for `get_issue`,
  `update_issue`, `delete_issue`). `include_metadata=False` returns
  the raw provider payload.
- `list_alert_rules`: summary with `alert_ref`, `name`, `environment`,
  `frequency`, `conditions_count`, `actions_count`. Opt in for
  `alert_id`.
- Tolerant inputs: `get_issue`, `update_issue`, `delete_issue`, and
  `list_events_for_issue` accept a string ID, an issue dict, or a
  list of issue dicts.
- Destructive: `delete_issue`. Confirm before invoking.

## PagerDutyToolSet

```python
from maivn_tools import PagerDutyToolSet

connector = PagerDutyToolSet(
    api_key=secrets["PD_TOKEN"],
    from_email="oncall@example.com",        # required for ack / resolve writes
    events_routing_key=secrets["PD_RK"],   # required for Events v2 trigger / resolve
)
```

REST + Events v2 in one toolset. Tools: `list_incidents`, `get_incident`,
`update_incident`, `acknowledge_incident`, `create_incident`,
`trigger_event`, `resolve_event`, `list_services`, `list_schedules`,
`list_on_calls`, `list_users`.

**Agent-ready behavior**

- `list_incidents` (default limit 25, hard max 200; summaries capped
  at 25): summary with `incident_ref`, `incident_number`, `title`,
  `status`, `urgency`, `created_at`, `service_name`. Raw incident IDs
  hidden; opt in with `include_ids=True` for `incident_id` (needed
  for `get_incident`, `update_incident`).
- `list_services` (default 25): summary with `service_ref`, `name`,
  `description`, `status`. Opt in for `service_id` (needed by
  `create_incident`).
- `list_schedules` (default 25): summary with `schedule_ref`, `name`,
  `description`, `time_zone`. Opt in for `schedule_id` (needed by
  `list_on_calls(schedule_ids=...)`).
- `list_on_calls`: summary with `oncall_ref`, `user_name`,
  `escalation_level`, `schedule_name`, `start`, `end`. Opt in for
  `user_id` / `schedule_id`. Best for "who is on call?" questions.
- `list_users` (default 25): summary with `user_ref`, `name`, `email`,
  `role`, `time_zone`. Opt in for `user_id`.
- Tolerant inputs: `get_incident`, `update_incident`, and
  `acknowledge_incident` accept a string ID, an incident dict, or a
  list of such.
- No destructive tools -- incident deletion is intentionally not
  exposed (use `update_incident(status="resolved")` instead).

```python
hot = connector.list_incidents(statuses=["triggered", "acknowledged"])
connector.acknowledge_incident(hot["incidents"][0])  # dict accepted
```

## NewRelicToolSet

```python
from maivn_tools import NewRelicToolSet

connector = NewRelicToolSet(
    api_key=secrets["NEW_RELIC_USER_KEY"],
    account_id=int(secrets["NEW_RELIC_ACCOUNT_ID"]),
    ingest_license_key=secrets.get("NEW_RELIC_LICENSE_KEY"),
    region="US",
)
```

NerdGraph + REST + Insights ingest. `submit_logs` / `submit_metrics`
require `ingest_license_key`. Tools: `nerdgraph_query`, `nrql_query`,
`submit_logs`, `submit_metrics`, `list_alert_policies`,
`create_alert_policy`, `delete_alert_policy` (destructive),
`list_applications`.

**Agent-ready behavior**

- `list_alert_policies`: summary with `alert_ref`, `name`,
  `incident_preference`, `created_at`. Raw numeric policy IDs hidden;
  opt in with `include_ids=True` for `policy_id` (needed by
  `delete_alert_policy`). `include_metadata=False` returns the raw
  response.
- `list_applications`: summary with `app_ref`, `name`, `language`,
  `health_status`, `reporting`. Opt in for `application_id`.
- Tolerant inputs: `delete_alert_policy` accepts an int, a policy
  dict, or a list of such.
- Destructive: `delete_alert_policy`. Confirm before invoking.

## SplunkToolSet

```python
from maivn_tools import SplunkToolSet

connector = SplunkToolSet(
    token=secrets["SPLUNK_TOKEN"],
    base_url="https://splunk.example.com:8089",
)
```

REST API for the splunkd management port. Tools: `create_search_job`,
`get_search_job`, `get_search_results`, `cancel_search_job`
(destructive), `list_indexes`, `list_saved_searches`,
`create_saved_search`, `update_saved_search`.

**Agent-ready behavior**

- `list_indexes`: summary with `index_ref`, `name`,
  `total_event_count`, `current_db_size_mb`, `disabled` (capped at
  25). `include_metadata=False` returns the raw response.
- `list_saved_searches`: summary with `search_ref`, `name`, `search`,
  `is_scheduled`, `cron_schedule` (capped at 25). Saved-search names
  are user-facing and are kept (they are also the API key used by
  `update_saved_search`).
- Destructive: `cancel_search_job`. Confirm before invoking (results
  are unrecoverable once cancelled).

## GrafanaToolSet

```python
from maivn_tools import GrafanaToolSet

connector = GrafanaToolSet(
    api_key=secrets["GRAFANA_TOKEN"],   # service-account or API key
    base_url="https://stack.grafana.net",
)
```

Tools: `search_dashboards`, `get_dashboard_by_uid`,
`create_or_update_dashboard`, `delete_dashboard_by_uid` (destructive),
`list_folders`, `create_folder`, `list_datasources`,
`create_annotation`, `list_alert_rules`, `get_health`.

**Agent-ready behavior**

- `search_dashboards` (default limit 25, hard max 5000; summaries
  capped at 25): summary with `dashboard_ref`, `title`, `type`, `url`,
  `folder_title`, `tags`. Dashboard UIDs hidden; opt in with
  `include_ids=True` for `dashboard_uid` / `dashboard_id` (needed by
  `get_dashboard_by_uid`, `delete_dashboard_by_uid`).
- `list_folders` (default limit 25): summary with `folder_ref`,
  `title`, `parent_uid`. Opt in for `folder_uid` / `folder_id`.
- `list_alert_rules`: summary with `alert_ref`, `title`, `folder_uid`,
  `rule_group`, `condition`, `no_data_state`, `exec_err_state`. Opt in
  for `alert_uid`.
- Tolerant inputs: `get_dashboard_by_uid` and
  `delete_dashboard_by_uid` accept a UID string or a dashboard dict
  from `search_dashboards(include_ids=True)`.
- Destructive: `delete_dashboard_by_uid`. Confirm before invoking.

## StatuspageToolSet

```python
from maivn_tools import StatuspageToolSet

connector = StatuspageToolSet(
    api_key=secrets["STATUSPAGE_KEY"],
    page_id="my-page-id",
)
```

Tools: `get_page`, `list_components`, `update_component`,
`list_incidents`, `create_incident`, `update_incident`,
`delete_incident` (destructive), `schedule_maintenance`,
`list_subscribers`.

**Agent-ready behavior**

- `list_components`: summary with `component_ref`, `name`, `status`,
  `description`, `group_id`. Raw component IDs hidden; opt in with
  `include_ids=True` for `component_id` (needed by
  `update_component`).
- `list_incidents` (default per_page 25, hard max 100; summaries
  capped at 25): summary with `incident_ref`, `name`, `status`,
  `impact`, `created_at`, `resolved_at`, `shortlink`. Opt in for
  `incident_id` (needed by `update_incident`, `delete_incident`).
- `list_subscribers` (default 25): summary with `subscriber_ref`,
  `mode`, `email`, `phone_number`, `endpoint`, `quarantined_at`. Opt
  in for `subscriber_id`.
- Tolerant inputs: `update_component`, `update_incident`, and
  `delete_incident` accept a string ID or a resource dict.
- Destructive: `delete_incident`. Confirm before invoking.

## CloudflareToolSet

```python
from maivn_tools import CloudflareToolSet

connector = CloudflareToolSet(api_token=secrets["CLOUDFLARE_TOKEN"])
```

v4 REST API. Tools: `verify_token`, `list_zones`, `get_zone`,
`list_dns_records`, `create_dns_record`, `update_dns_record`,
`delete_dns_record` (destructive), `purge_cache` (destructive),
`list_workers`, `list_r2_buckets`, `create_r2_bucket`.

**Agent-ready behavior**

- `list_zones` (default per_page 25, hard max 50): summary with
  `zone_ref`, `name`, `status`, `plan`. Zone IDs hidden; opt in with
  `include_ids=True` for `zone_id` (needed for `list_dns_records`,
  `purge_cache`, etc.).
- `list_dns_records` (default per_page 25, hard max 100): summary with
  `record_ref`, `type`, `name`, `content`, `ttl`, `proxied`. Opt in
  for `record_id` (needed for `update_dns_record`,
  `delete_dns_record`).
- `list_workers`: summary with `worker_ref`, `name`, `created_on`,
  `modified_on`, `etag`. Opt in for `script_id`.
- `list_r2_buckets`: summary with `bucket_ref`, `name`,
  `creation_date`, `location`. Bucket names are the primary identifier
  in R2 so no `include_ids` flag is needed.
- Tolerant inputs: `get_zone`, `list_dns_records`,
  `update_dns_record`, `delete_dns_record`, and `purge_cache` accept
  a string ID or a resource dict from the corresponding list call.
- Destructive: `delete_dns_record`, `purge_cache`. Confirm before
  invoking (purge causes user-facing latency until cache repopulates).

## KubernetesToolSet

```python
from maivn_tools import KubernetesToolSet

connector = KubernetesToolSet(
    api_server="https://my-cluster:6443",
    token=secrets["K8S_SA_TOKEN"],
)
```

Talks to the Kubernetes API server directly. Tools: `get_version`,
`list_namespaces`, `list_pods`, `get_pod`, `get_pod_logs`,
`list_deployments`, `scale_deployment`, `delete_pod` (destructive),
`list_services`, `list_events`, `list_nodes`, `apply_manifest`.

**Agent-ready behavior**

- `list_namespaces`: summary with `namespace_ref`, `name`, `phase`,
  `created_at`. Namespace `name` is the user-facing identifier and is
  kept; cluster UID is opt-in via `include_ids=True`.
- `list_pods` (default limit 25, hard max 1000; summaries capped at
  25): summary with `pod_ref`, `name`, `namespace`, `phase`, `ready`,
  `node`, `start_time`. Pod UIDs are opt-in.
- `list_deployments`: summary with `deployment_ref`, `name`,
  `namespace`, `replicas`, `ready_replicas`, `available_replicas`.
  UIDs opt-in.
- `list_services`: summary with `service_ref`, `name`, `namespace`,
  `type`, `cluster_ip`, `ports`. UIDs opt-in.
- `list_events` returns the raw event list (already useful for
  diagnosing Pending/Failed pods); cap with `limit` (default 25, hard
  max 1000).
- Destructive: `delete_pod`. Confirm before invoking (one-off pods
  are not respawned).

> `apply_manifest` uses server-side apply
> (`Content-Type: application/apply-patch+yaml` + `fieldManager`) so the
> caller can ship arbitrary resources without crafting per-kind tooling.
