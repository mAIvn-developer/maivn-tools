# AWS core

Core AWS service connectors. All four use a shared
`SigV4Auth` (Signature Version 4) implementation so requests are signed
in-process and don't require `boto3` as a runtime dependency.

> The toolsets default to `region="us-east-1"`. Override via the
> constructor for every service except IAM, which is global.

## Agent-ready behavior (overview)

All list / describe tools return compact summaries by default with a
stable display ref (`bucket_ref`, `object_ref`, `function_ref`,
`log_group_ref`, `log_stream_ref`, `user_ref`, `role_ref`,
`policy_ref`). The user-facing identifier -- bucket name, object key,
function name, log group name, IAM user/role/policy name -- is kept
because it is what most subsequent AWS calls take. Opaque or secondary
identifiers (function ARN, IAM `UserId` / `RoleId` / policy ARN, raw
XML) are hidden by default and exposed when needed:

- `include_metadata=False` returns the raw provider response (XML for
  S3, JSON for Lambda / Logs / IAM).
- `include_ids=True` adds opaque IDs (`function_arn`, `user_id`,
  `arn`, `role_id`, `policy_arn`, `policy_id`) into the summaries when
  a follow-up call needs them.

Write tools that take an identifier (`get_function`, `invoke_function`,
`update_function_configuration`, `update_function_code`,
`delete_function`, `list_versions`, `publish_version`, `list_aliases`,
`put_function_concurrency`, `delete_log_group`, `put_retention_policy`,
`describe_log_streams`, `get_log_events`, `filter_log_events`,
`put_log_events`, `get_user`, `delete_user`, `get_role`, `delete_role`,
`get_policy`, `attach_user_policy`, `attach_role_policy`,
`detach_user_policy`, `create_access_key`, `delete_access_key`) accept
the dict from the corresponding list tool as well as the raw name /
ARN.

Destructive tools across this group (require user confirmation):
`delete_bucket`, `delete_object`, `delete_function`, `delete_log_group`,
`delete_user`, `delete_role`, `detach_user_policy`,
`delete_access_key`.

## AmazonS3ToolSet

```python
from maivn_tools import AmazonS3ToolSet

connector = AmazonS3ToolSet(
    access_key=secrets["AWS_ACCESS_KEY_ID"],
    secret_key=secrets["AWS_SECRET_ACCESS_KEY"],
    region="us-west-2",
    session_token=secrets.get("AWS_SESSION_TOKEN"),
)
```

Tools: `list_buckets`, `create_bucket`, `delete_bucket` (destructive),
`list_objects_v2`, `head_object`, `get_object`, `put_object`,
`delete_object` (destructive), `copy_object`, `get_bucket_location`,
`get_bucket_policy`.

**Agent-ready behavior**

- `list_buckets`: summary with `bucket_ref`, `name`, `creation_date`
  (capped at 25). Pass `include_metadata=False` for the raw XML body.
- `list_objects_v2` (default `max_keys=25`, hard max 1000; summaries
  capped at 25): summary with `object_ref`, `key`, `size`,
  `last_modified`, `etag`, `storage_class`. Pagination
  (`is_truncated`, `next_continuation_token`) preserved.
  `include_metadata=False` returns the raw XML.
- Destructive: `delete_bucket`, `delete_object`. Confirm with the
  user before invoking.

```python
listing = connector.list_objects_v2("my-bucket", prefix="invoices/")
```

## AmazonLambdaToolSet

```python
from maivn_tools import AmazonLambdaToolSet

connector = AmazonLambdaToolSet(
    access_key=secrets["AWS_ACCESS_KEY_ID"],
    secret_key=secrets["AWS_SECRET_ACCESS_KEY"],
    region="us-east-1",
)
```

Tools: `list_functions`, `get_function`, `invoke_function`,
`update_function_configuration`, `update_function_code`,
`delete_function` (destructive), `list_versions`, `publish_version`,
`list_aliases`, `put_function_concurrency`.

`invoke_function` decodes the `X-Amz-Log-Result` header (base64) when
`log_type="Tail"` so callers can read CloudWatch tail output without
a second request.

**Agent-ready behavior**

- `list_functions` (default `max_items=25`, hard max 10000; summaries
  capped at 25): summary with `function_ref`, `name`, `runtime`,
  `memory_size`, `timeout`, `last_modified`, `handler`. The function
  name is the primary identifier so it is kept; the `function_arn` is
  hidden unless `include_ids=True`. Pagination `next_marker`
  preserved.
- Tolerant inputs: `get_function`, `invoke_function`,
  `update_function_configuration`, `update_function_code`,
  `delete_function`, `list_versions`, `publish_version`,
  `list_aliases`, and `put_function_concurrency` accept a name
  string, an ARN, or a function dict from `list_functions`.
- Destructive: `delete_function`. Confirm before invoking.

## AmazonCloudWatchLogsToolSet

```python
from maivn_tools import AmazonCloudWatchLogsToolSet

connector = AmazonCloudWatchLogsToolSet(
    access_key=secrets["AWS_ACCESS_KEY_ID"],
    secret_key=secrets["AWS_SECRET_ACCESS_KEY"],
    region="us-east-1",
)
```

The CloudWatch Logs API is JSON-RPC over HTTPS (with an `X-Amz-Target`
header) rather than the REST style. The toolset handles the dispatch
internally. Tools: `describe_log_groups`, `create_log_group`,
`delete_log_group` (destructive), `put_retention_policy`,
`describe_log_streams`, `get_log_events`, `filter_log_events`,
`put_log_events`, `start_query` (Logs Insights), `get_query_results`.

**Agent-ready behavior**

- `describe_log_groups` (default limit 25, hard max 50; summaries
  capped at 25): summary with `log_group_ref`, `name`,
  `retention_in_days`, `stored_bytes`, `creation_time`,
  `metric_filter_count`. Log group names are the primary identifier.
  Pagination `next_token` preserved. `include_metadata=False` returns
  the raw response (which carries ARNs and additional fields).
- `describe_log_streams` (default limit 25, hard max 50): summary with
  `log_stream_ref`, `name`, `first_event_timestamp`,
  `last_event_timestamp`, `stored_bytes`.
- Tolerant inputs: `delete_log_group`, `put_retention_policy`,
  `describe_log_streams`, `get_log_events`, `filter_log_events`, and
  `put_log_events` accept a name string, an ARN, or a log-group dict.
- Destructive: `delete_log_group`. Confirm before invoking (removes
  the group and all its streams).

## AmazonIAMToolSet

```python
from maivn_tools import AmazonIAMToolSet

connector = AmazonIAMToolSet(
    access_key=secrets["AWS_ACCESS_KEY_ID"],
    secret_key=secrets["AWS_SECRET_ACCESS_KEY"],
)
```

IAM is global; requests are signed against `us-east-1`. The Query
protocol returns JSON when `Accept: application/json` is set, which
the toolset does for you. Tools: `list_users`, `get_user`,
`create_user`, `delete_user` (destructive), `list_roles`, `get_role`,
`create_role`, `delete_role` (destructive), `list_policies`,
`get_policy`, `attach_user_policy`, `attach_role_policy`,
`detach_user_policy` (destructive), `create_access_key`,
`delete_access_key` (destructive).

**Agent-ready behavior**

- `list_users` (default `max_items=25`, hard max 1000; summaries
  capped at 25): summary with `user_ref`, `user_name`, `path`,
  `create_date`, `password_last_used`. Opaque `UserId` and `Arn`
  hidden unless `include_ids=True`.
- `list_roles` (default `max_items=25`): summary with `role_ref`,
  `role_name`, `path`, `description`, `create_date`,
  `max_session_duration`. Opaque `RoleId` and `Arn` opt-in via
  `include_ids=True`.
- `list_policies` (default `max_items=25`): summary with `policy_ref`,
  `policy_name`, `path`, `attachment_count`, `description`,
  `create_date`, `is_attachable`. `policy_arn` and `policy_id` hidden
  by default; opt in via `include_ids=True` (needed by
  `attach_user_policy`, `attach_role_policy`, `detach_user_policy`).
- Tolerant inputs: `get_user`, `delete_user`, `get_role`,
  `delete_role`, `get_policy`, `attach_user_policy`,
  `attach_role_policy`, `detach_user_policy`, `create_access_key`,
  and `delete_access_key` accept the relevant resource string or the
  dict from the corresponding list tool.
- Destructive: `delete_user`, `delete_role`, `detach_user_policy`,
  `delete_access_key`. Confirm before invoking -- these revoke
  permissions or invalidate credentials in use.
- Note: `create_access_key` returns the secret once and once only --
  treat the response as sensitive.

```python
policies = connector.list_policies(scope="Local", include_ids=True)
connector.attach_role_policy(role_name="my-role", policy_arn=policies["policies"][0])
```
