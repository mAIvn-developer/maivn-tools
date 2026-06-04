# Identity & security

Connectors for identity providers, secret managers, MFA, and security
scanners. Every connector follows the standard `@toolset` / `@toolify`
shape and the agent-ready toolset pattern (compact summaries by default,
opt-in raw IDs, tolerant write inputs) — and secret values are never
returned in list/summary mode (see below).

## Agent-ready behavior (overview)

This category covers identity (Auth0, Okta, JumpCloud, OneLogin, Duo),
secret managers (Vault, 1Password, Bitwarden, Doppler, Infisical),
security scanning (Snyk), and verification (Twilio). Across the group:

- **List tools** return compact summaries with stable display refs
  (`user_ref`, `role_ref`, `connection_ref`, `app_ref`, `org_ref`,
  `vault_ref`, `item_ref`, `secret_ref`, `project_ref`, `config_ref`,
  `system_ref`, `group_ref`, `vuln_ref`, `message_ref`,
  `subscriber_ref`). Raw provider IDs (`user_id`, `role_id`,
  `vault_id`, `item_id`, `secret_id`, `org_id`, `policy_arn`,
  `connection_id`, `client_id`, `org_slug`/`project_slug`,
  `workspace_id`, etc.) are hidden by default and opt-in via
  `include_ids=True`.
- **Write tools that take an identifier accept either a raw ID/email
  or the dict from the corresponding list/get tool** (Auth0:
  `_resolve_user_id`; Okta: `_resolve_user_id`; OnePassword:
  `_resolve_vault_id`/`_resolve_item_id`; Bitwarden: project and
  secret resolvers; JumpCloud: `_resolve_user_id`; OneLogin user
  resolver; Snyk: org/project string ids; Twilio: SID strings).
- Default page size is generally 25; some tools cap at provider
  maxima (Auth0 / Okta / JumpCloud / OneLogin: 100-200; Twilio:
  1000).

### Secret values are NEVER returned in list/summary mode

For every secret-store toolset (Vault, 1Password, Bitwarden, Doppler,
Infisical), the **list** tools (`kv_list`, `list_items`,
`list_secrets`) return metadata only -- keys, names, comments, types,
timestamps -- never the secret value itself. Even when the underlying
provider response carries the value, the summary stripper drops it.

Two opt-in paths exist for cases where the agent really does need the
values:

- `DopplerToolSet.list_secrets(..., include_values=True)` -- returns
  the raw Doppler payload (with values) for the requested config.
- `InfisicalToolSet.list_secrets(..., include_values=True)` -- returns
  the raw Infisical payload (with values) for the requested
  workspace/environment/path.

Use either flag only when the agent's task is "fetch all the secrets
and pass them to X." Treat the result as sensitive and do not echo it
into a final user-facing answer.

For one-off reads, prefer the targeted `get_secret`/`kv_get`/`get_item`
tool -- they read a single value at a time and make the access pattern
explicit. They still return the value (that is the point of the
tool), so the same sensitivity rule applies.

### Destructive tools (require user confirmation)

Identity: `delete_user` (Auth0, JumpCloud, OneLogin, Duo),
`suspend_user` / `deactivate_user` (Okta), `lock_user` (OneLogin),
`disable_user` (Duo), `remove_user_from_group` (Okta).

Secrets: `kv_delete`, `kv_destroy` (Vault), `delete_item`
(1Password), `delete_projects`, `delete_secrets` (Bitwarden),
`delete_project` (Doppler), `delete_secret` (Infisical).

Security / messaging: `deactivate_project` (Snyk), `send_message`,
`start_verification`, `make_call` (Twilio -- call out separately:
these trigger real billable messages / calls to real phone numbers
and emails. Confirm the recipient and body with the user before
invoking).

## Auth0ToolSet

```python
from maivn_tools import Auth0ToolSet

connector = Auth0ToolSet(
    domain="tenant.us.auth0.com",
    access_token=secrets["AUTH0_MGMT_TOKEN"],
)
```

Tools: `list_users`, `get_user`, `create_user`, `update_user`,
`delete_user` (destructive), `list_roles`, `assign_roles_to_user`,
`list_connections`, `list_clients`, `list_organizations`, `list_logs`.

**Agent-ready behavior**

- `list_users` (default `per_page=25`, hard max 100): summary with
  `user_ref`, `email`, `name`, `blocked`, `email_verified`,
  `last_login`, `logins_count`. Raw `user_id` hidden; opt in with
  `include_ids=True` (needed by `update_user`, `delete_user`,
  `assign_roles_to_user`).
- `list_roles`: summary with `role_ref`, `name`, `description`. Opt
  in for `role_id` (needed by `assign_roles_to_user`).
- `list_connections`: summary with `connection_ref`, `name`,
  `strategy`, `is_domain_connection`. `name` is what `create_user`
  takes -- opt in only for `connection_id` if you need it.
- `list_clients`: summary with `app_ref`, `name`, `app_type`,
  `is_first_party`. Raw `client_id` is sensitive and hidden by
  default.
- `list_organizations`: summary with `org_ref`, `name`,
  `display_name`. Opt in for `org_id`.
- Tolerant inputs: `update_user`, `delete_user`,
  `assign_roles_to_user` accept a raw `user_id` string or a user dict
  from `list_users(include_ids=True)`.

```python
users = connector.list_users(q='email:"alice@example.com"', include_ids=True)
connector.update_user(users["users"][0], blocked=True)  # dict accepted
```

## OktaToolSet

```python
from maivn_tools import OktaToolSet

connector = OktaToolSet(
    org_url="https://my-tenant.okta.com",
    api_token=secrets["OKTA_TOKEN"],
)
```

Tools: `list_users`, `get_user`, `create_user`, `update_user`,
`suspend_user` (destructive), `unsuspend_user`, `deactivate_user`
(destructive), `list_groups`, `add_user_to_group`,
`remove_user_from_group` (destructive), `list_applications`,
`list_factors`, `list_system_logs`.

**Agent-ready behavior**

- `list_users` (default limit 25, hard max 200): summary with
  `user_ref`, `email`, `name`, `login`, `status`, `last_login`. Raw
  Okta `user_id` hidden; opt in with `include_ids=True` (needed by
  write tools).
- `list_groups` (default limit 25, hard max 200): summary with
  `group_ref`, `name`, `description`, `type`. Opt in for `group_id`
  (needed by `add_user_to_group` / `remove_user_from_group`).
- `list_applications` (default limit 25, hard max 200): summary with
  `app_ref`, `name`, `label`, `status`, `sign_on_mode`. Opt in for
  `app_id`.
- Tolerant inputs: `update_user`, `suspend_user`, `unsuspend_user`,
  `deactivate_user`, `add_user_to_group`, `remove_user_from_group`
  accept a string ID / login / email or a user dict.
- Destructive: `suspend_user`, `deactivate_user`,
  `remove_user_from_group`. Confirm before invoking.

## VaultToolSet

```python
from maivn_tools import VaultToolSet

connector = VaultToolSet(
    base_url="https://vault.example:8200",
    token=secrets["VAULT_TOKEN"],
    namespace="org/team",  # optional enterprise namespace
)
```

KV v2 + transit + token operations. Tools: `get_health`, `list_mounts`,
`kv_get`, `kv_put`, `kv_patch`, `kv_delete` (destructive), `kv_destroy`
(destructive), `kv_list`, `lookup_token_self`, `renew_token_self`,
`transit_encrypt`, `transit_decrypt`.

**Agent-ready behavior**

- `kv_list`: summary with `secret_ref`, `key`, `is_directory`. **Never
  returns secret values** -- only child key names. Set
  `include_ids=True` to also attach the full `path` for each key
  (handy for follow-up `kv_get` calls).
- `kv_get` returns Vault's raw payload with `data.data` (the actual
  secret material) -- treat the result as sensitive.
- Destructive: `kv_delete` (soft-delete, reversible via undelete) and
  `kv_destroy` (permanent). Confirm before invoking.

## OnePasswordToolSet

```python
from maivn_tools import OnePasswordToolSet

connector = OnePasswordToolSet(
    base_url="https://op-connect.example.com",
    access_token=secrets["OP_CONNECT_TOKEN"],
)
```

1Password Connect (self-hosted). Tools: `list_vaults`, `get_vault`,
`list_items`, `get_item`, `create_item`, `update_item`, `patch_item`,
`delete_item` (destructive), `get_item_files`, `get_heartbeat`.

**Agent-ready behavior**

- `list_vaults`: summary with `vault_ref`, `name`, `description`,
  `type`, `item_count`. Raw `vault_id` hidden; opt in with
  `include_ids=True`.
- `list_items`: summary with `item_ref`, `title`, `category`, `tags`,
  `updated_at`, optional `primary_url`. **Item values are not in the
  list response** -- even if a value-bearing field leaks in, the
  stripper drops it. Use `get_item` for a single item's full payload
  (which does include secret fields -- treat as sensitive).
- Tolerant inputs: `get_vault`, `list_items`, `get_item`,
  `create_item`, `update_item`, `patch_item`, `delete_item`,
  `get_item_files` accept the relevant ID string or a vault/item dict.
- Destructive: `delete_item`. Confirm before invoking (item cannot be
  recovered).

## BitwardenToolSet

```python
from maivn_tools import BitwardenToolSet

connector = BitwardenToolSet(
    access_token=secrets["BWS_ACCESS_TOKEN"],
    organization_id="org-uuid",
)
```

Bitwarden Secrets Manager. Tools: `list_projects`, `create_project`,
`get_project`, `update_project`, `delete_projects` (destructive),
`list_secrets`, `get_secret`, `create_secret`, `update_secret`,
`delete_secrets` (destructive).

**Agent-ready behavior**

- `list_projects`: summary with `project_ref`, `name`, `created_at`,
  `revised_at`. Raw `project_id` hidden; opt in with
  `include_ids=True`.
- `list_secrets`: summary with `secret_ref`, `key`, `note`,
  `created_at`, `revised_at`. **Never returns the `value`**. Use
  `get_secret` for a single targeted read (which does include the
  value -- treat as sensitive).
- Tolerant inputs: `get_project`, `update_project`,
  `delete_projects`, `get_secret`, `update_secret`, `delete_secrets`
  accept the relevant ID string, a resource dict, or a list of either
  (for the bulk delete tools).
- Destructive: `delete_projects`, `delete_secrets`. Confirm before
  invoking.

## DopplerToolSet

```python
from maivn_tools import DopplerToolSet

connector = DopplerToolSet(token=secrets["DOPPLER_TOKEN"])
```

Tools: `list_projects`, `create_project`, `delete_project`
(destructive), `list_configs`, `list_secrets`, `get_secret`,
`update_secrets`, `download_secrets`.

**Agent-ready behavior**

- `list_projects` (default `per_page=20`): summary with `project_ref`,
  `name`, `description`, `created_at`. Raw `project_slug` hidden;
  opt in with `include_ids=True`.
- `list_configs`: summary with `config_ref`, `name`, `environment`,
  `root`, `locked`.
- `list_secrets`: summary with `secret_ref`, `key`, optional
  `value_type`, `note`. **Never returns secret values unless you pass
  `include_values=True`** -- that is the explicit opt-in path for
  bulk-reading values; treat the result as sensitive.
- `get_secret` and `download_secrets` both return values; treat as
  sensitive.
- Destructive: `delete_project` (removes the project and all its
  configs + secrets). Confirm before invoking.

```python
secrets = connector.list_secrets(project="my-app", config="prd")  # metadata only
values = connector.list_secrets(project="my-app", config="prd", include_values=True)
```

## InfisicalToolSet

```python
from maivn_tools import InfisicalToolSet

connector = InfisicalToolSet(access_token=secrets["INFISICAL_TOKEN"])
```

Tools: `list_projects`, `get_project`, `list_secrets`, `get_secret`,
`create_secret`, `update_secret`, `delete_secret` (destructive).

**Agent-ready behavior**

- `list_projects`: summary with `project_ref`, `name`, `slug`,
  `environments`. Raw `workspace_id` hidden; opt in with
  `include_ids=True`.
- `list_secrets`: summary with `secret_ref`, `key`, `type`,
  `comment`, `updated_at`. **Never returns secret values unless you
  pass `include_values=True`** -- that is the explicit opt-in path;
  treat the result as sensitive. Set `include_ids=True` to also
  attach `secret_id` and `secret_path`.
- `get_secret` returns the value; treat as sensitive.
- Destructive: `delete_secret`. Confirm before invoking.

## SnykToolSet

```python
from maivn_tools import SnykToolSet

connector = SnykToolSet(api_token=secrets["SNYK_TOKEN"])
```

Tools: `list_organizations`, `list_projects`, `get_project`,
`list_issues`, `list_aggregated_issues`, `trigger_test`,
`deactivate_project` (destructive), `list_dependencies`.

**Agent-ready behavior**

- `list_organizations` (default limit 25, hard max 100): summary with
  `org_ref`, `name`, `slug`. Opt in for `org_id`.
- `list_projects` (default limit 25, hard max 100): summary with
  `project_ref`, `name`, `origin`, `type`, `target_reference`,
  `status`. Opt in for `project_id`.
- `list_issues` (default limit 25, hard max 100): summary with
  `vuln_ref`, `title`, `severity`, `type`, `status`, `ignored`,
  `created_at`. Opt in for `vuln_id` / `key`.
- Destructive: `deactivate_project` (stops scans; reversible via the
  Snyk UI). Confirm before invoking.

## TwilioToolSet

```python
from maivn_tools import TwilioToolSet

connector = TwilioToolSet(
    account_sid=secrets["TWILIO_ACCOUNT_SID"],
    auth_token=secrets["TWILIO_AUTH_TOKEN"],
)
```

Programmable Messaging, Verify, and Voice in one toolset. Tools:
`send_message`, `list_messages`, `get_message`, `start_verification`,
`check_verification`, `make_call`, `lookup_phone_number`.

**Agent-ready behavior**

- `list_messages` (default `page_size=25`, hard max 1000): summary
  with `message_ref`, `from`, `to`, `status`, `direction`, `body`,
  `date_sent`, `price`. Raw `message_sid` hidden; opt in with
  `include_ids=True`.
- **Destructive (real billable side effects):** `send_message`,
  `start_verification`, `make_call`. Each one sends a real SMS / OTP
  / phone call to a real number -- always confirm the recipient and
  content with the user before invoking. The `destructive=True`
  marker also makes them filterable via `exclude_tags=["destructive"]`
  for fully autonomous runs.

## JumpCloudToolSet

```python
from maivn_tools import JumpCloudToolSet

connector = JumpCloudToolSet(api_key=secrets["JUMPCLOUD_KEY"])
```

Tools: `list_users`, `get_user`, `create_user`, `update_user`,
`delete_user` (destructive), `list_user_groups`,
`manage_user_group_member`, `list_systems`, `list_applications`.

**Agent-ready behavior**

- `list_users` (default limit 25, hard max 100): summary with
  `user_ref`, `email`, `username`, `name`, `suspended`, `activated`,
  `last_login`. Raw `user_id` hidden; opt in with `include_ids=True`.
- `list_user_groups`: summary with `group_ref`, `name`,
  `description`, `type`. Opt in for `group_id`.
- `list_systems`: summary with `system_ref`, `hostname`, `os`,
  `version`, `active`, `last_contact`. Opt in for `system_id`.
- `list_applications`: summary with `app_ref`, `name`, `sso_type`,
  `active`. Opt in for `app_id`.
- Tolerant inputs: `update_user`, `delete_user`,
  `manage_user_group_member` accept a user-id string or a user dict.
- Destructive: `delete_user`. Confirm before invoking (terminates
  sessions and removes group membership).

## OneLoginToolSet

```python
from maivn_tools import OneLoginToolSet

connector = OneLoginToolSet(
    access_token=token,           # via OAuth client-credentials
    subdomain="my-tenant",
    region="us",                  # "us" or "eu"
)
```

Tools: `list_users`, `get_user`, `create_user`, `update_user`,
`delete_user` (destructive), `lock_user` (destructive), `list_roles`,
`assign_role_to_user`, `list_apps`, `list_events`.

**Agent-ready behavior**

- `list_users`: summary with `user_ref`, `email`, `username`, `name`,
  `status`, `last_login`, `locked_until`. Raw numeric `user_id`
  hidden; opt in with `include_ids=True`.
- `list_roles`: summary with `role_ref`, `name` (and admin metadata).
  Opt in for `role_id`.
- `list_apps`: summary with `app_ref`, `name`, `connector_id`.
- Destructive: `delete_user`, `lock_user`. Confirm before invoking.

## DuoToolSet

```python
from maivn_tools import DuoToolSet

connector = DuoToolSet(
    ikey=secrets["DUO_IKEY"],
    skey=secrets["DUO_SKEY"],
    api_host="api-abc123.duosecurity.com",
)
```

The toolset computes the per-request HMAC-SHA512 signature in-process
so callers only provide `ikey` / `skey` / `api_host`. Tools:
`list_users`, `get_user`, `create_user`, `disable_user` (destructive),
`delete_user` (destructive), `list_phones`, `list_groups`,
`associate_group_with_user`, `list_integrations`,
`list_authentication_logs`.

**Agent-ready behavior**

- `list_users`: summary with `user_ref`, `username`, `email`,
  `status`, `last_login`. Raw `user_id` hidden; opt in with
  `include_ids=True`.
- `list_phones`: summary with `phone_ref`, `number`, `type`,
  `platform`, `activated`. Opt in for `phone_id`.
- `list_groups`: summary with `group_ref`, `name`, `desc`,
  `status`. Opt in for `group_id`.
- `list_integrations`: summary with `integration_ref`, `name`,
  `type`, `enroll_policy`. Opt in for `integration_key`.
- Destructive: `disable_user`, `delete_user`. Confirm before invoking
  (Duo deletes are permanent).
