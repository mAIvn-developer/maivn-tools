# Partner hub connectors

`maivn-tools` ships six connectors that bridge into the major
integration-platform partners. Each one trades direct provider coverage
for breadth: instead of implementing every provider's API natively, the
host platform's catalog (Zapier, Workato, Pipedream, Make, n8n, Composio)
is exposed as Agent-ready tools.

| Connector | Trigger style | Auth |
| --- | --- | --- |
| `ZapierConnector` | Webhooks + Natural Language Actions | Webhook URLs (no auth) and/or NLA API key |
| `WorkatoToolSet` | Recipe metadata + on-demand triggers | Workato API token |
| `PipedreamToolSet` | Workflow metadata + HTTP triggers | Pipedream bearer token |
| `MakeToolSet` | Scenario metadata + webhook URLs | Make API token |
| `N8nToolSet` | Workflow metadata + activate/deactivate + webhooks | n8n API key |
| `ComposioToolSet` | Action catalog + execute | Composio API key |

## Agent-ready behavior (overview)

The five method-based toolsets (Workato, Pipedream, Make, n8n,
Composio) use the standard summary pattern -- list tools return
compact summaries with stable display refs (`recipe_ref`, `job_ref`,
`workflow_ref`, `execution_ref`, `scenario_ref`, `app_ref`,
`action_ref`, `connection_ref`). Raw provider IDs are hidden by
default and exposed via `include_ids=True` when a follow-up tool
(`get_*`, `activate_workflow`, `invoke_http_trigger`,
`execute_action`) needs them.

Write tools that take an identifier (`get_workflow`,
`activate_workflow`, `get_scenario`, `list_executions`,
`execute_action`) accept either a raw ID or the resource dict from
the matching list tool. Webhook-trigger tools (`run_recipe_trigger`,
`invoke_http_trigger`, `trigger_webhook` for Make / n8n) take the
trigger URL directly -- they bypass the catalog by design.

No destructive tools across this group -- workflow / recipe deletes
go through the provider UI, not the API.

## ZapierConnector

Map each Zap's catch URL to a logical name. The connector creates one
`trigger_<name>` callable per entry.

```python
from maivn_tools import ZapierConnector, register_connector

zapier = ZapierConnector(
    webhook_urls={
        "new_lead": "https://hooks.zapier.com/hooks/catch/123/abc",
        "deal_won": "https://hooks.zapier.com/hooks/catch/123/def",
    },
    nla_api_key=secrets["ZAPIER_NLA_KEY"],  # optional
)
```

If `nla_api_key` is supplied the connector also exposes `list_actions`
and `run_action` against Zapier's Natural Language Actions endpoint.

**Agent-ready behavior**

Zapier is the **builder-style** connector in this group: tool names
are dynamic (one `trigger_<name>` per configured webhook URL), so it
does not use `@toolset` / `@toolify`. Instead of `_ref` summaries, the
agent-ready improvements live in the **dynamically generated
docstrings**:

- Each per-webhook `trigger_<name>` tool gets a docstring that:
  - names the specific webhook ("Trigger the 'new_lead' Zapier
    webhook by POSTing the payload."),
  - describes the response contract (`{"status": ..., "url": ...,
    "delivered": True}`),
  - documents the `payload` argument and the meaning of `None`,
  - explains that the Zap definition lives in Zapier -- this tool
    just delivers the payload.
- The NLA `list_actions` docstring calls out that action IDs are
  internal Zapier handles -- they should be passed straight into
  `run_action` and not shown in final answers.
- The NLA `run_action` docstring documents `action_id` (from
  `list_actions`), `instructions`, and the `params` pin-field map.

There is no summary stripper because there is nothing to summarize --
each tool's signature already takes one trigger URL or one action ID.

## WorkatoToolSet

| Tool | Permission | Description |
| --- | --- | --- |
| `list_recipes(page, per_page, include_ids=False)` | READ | Recipes accessible to the token. |
| `list_jobs(recipe_id, page, per_page, status, include_ids=False)` | READ | Job history for a recipe. |
| `run_recipe_trigger(trigger_url, payload)` | WRITE | POST to an on-demand recipe trigger URL. |

**Agent-ready behavior**

- `list_recipes`: summary with `recipe_ref`, name, status, last run.
  Raw recipe IDs hidden; opt in with `include_ids=True` (needed by
  `list_jobs(recipe_id=...)`).
- `list_jobs`: summary with `job_ref`, status, start/end timestamps.
  Tolerant input: `recipe_id` accepts a raw ID or a recipe dict.
- `run_recipe_trigger` takes the trigger URL directly (no catalog
  lookup).

## PipedreamToolSet

| Tool | Permission | Description |
| --- | --- | --- |
| `list_workflows(after, include_ids=False)` | READ | List workflows. |
| `get_workflow(workflow_id)` | READ | Fetch one workflow. |
| `invoke_http_trigger(trigger_url, payload)` | WRITE | POST to a workflow HTTP trigger URL. |

**Agent-ready behavior**

- `list_workflows`: summary with `workflow_ref`, name, active flag,
  trigger URL, last update. Raw workflow IDs hidden; opt in with
  `include_ids=True` (needed by `get_workflow`).
- Tolerant input: `get_workflow` accepts a raw ID or a workflow dict
  from `list_workflows(include_ids=True)`.

## MakeToolSet

| Tool | Permission | Description |
| --- | --- | --- |
| `list_scenarios(team_id, limit, offset, include_ids=False)` | READ | List scenarios. |
| `get_scenario(scenario_id)` | READ | Fetch one scenario. |
| `list_executions(scenario_id, limit, offset, include_ids=False)` | READ | List scenario executions. |
| `trigger_webhook(webhook_url, payload)` | WRITE | POST to a scenario's webhook URL. |

`base_url` is region-specific. Use `https://us1.make.com/api/v2` for the
US zone or `https://eu1.make.com/api/v2` for the EU zone.

**Agent-ready behavior**

- `list_scenarios`: summary with `scenario_ref`, name, active flag,
  team, last edit. Raw scenario IDs hidden; opt in with
  `include_ids=True` (needed by `get_scenario`, `list_executions`).
- `list_executions`: summary with `execution_ref`, status, duration,
  started/finished timestamps. Tolerant input: `scenario_id` accepts
  a raw ID or a scenario dict.

## N8nToolSet

| Tool | Permission | Description |
| --- | --- | --- |
| `list_workflows(active, limit, cursor, include_ids=False)` | READ | List workflows. |
| `get_workflow(workflow_id)` | READ | Fetch one workflow. |
| `activate_workflow(workflow_id, active)` | WRITE | Activate or deactivate. |
| `list_executions(workflow_id, status, limit, cursor, include_ids=False)` | READ | List executions. |
| `trigger_webhook(webhook_url, payload)` | WRITE | POST to a workflow webhook URL. |

n8n is most often self-hosted; configure `base_url` to point at the
instance and create an API key under Settings -> API.

**Agent-ready behavior**

- `list_workflows`: summary with `workflow_ref`, name, active flag,
  tag names, updated timestamp. Raw workflow IDs hidden; opt in with
  `include_ids=True` (needed by `get_workflow`, `activate_workflow`,
  `list_executions(workflow_id=...)`).
- `list_executions`: summary with `execution_ref`, status, mode,
  started/finished timestamps. Opt in for the raw execution ID.
- Tolerant inputs: `get_workflow`, `activate_workflow`,
  `list_executions` accept raw IDs or workflow dicts.

## ComposioToolSet

| Tool | Permission | Description |
| --- | --- | --- |
| `list_apps(include_ids=False)` | READ | List apps in the Composio catalog. |
| `list_actions(app, use_case, limit, include_ids=False)` | READ | List actions, optionally filtered. |
| `list_connections(app, include_ids=False)` | READ | List the user's connected accounts. |
| `execute_action(action_name, connected_account_id, input)` | WRITE | Execute a single action. |

`execute_action` posts to `/v1/actions/<name>/execute` with the supplied
`input` mapping; consult the Composio docs for the per-action schema.

**Agent-ready behavior**

- `list_apps`: summary with `app_ref`, name, description, categories,
  logo URL. Opt in for the raw app ID/slug.
- `list_actions`: summary with `action_ref`, name, app, description,
  use case. The action `name` is what callers pass to
  `execute_action`. Opt in for the raw action ID.
- `list_connections`: summary with `connection_ref`, app name,
  status, created. Opt in for `connected_account_id` (needed by
  `execute_action`).
- Tolerant inputs: `execute_action` accepts a raw action name or an
  action dict from `list_actions(include_ids=True)`, and
  `connected_account_id` accepts a raw ID or a connection dict.

```python
apps = composio.list_apps()  # summaries safe to show
actions = composio.list_actions(app="github", include_ids=True)
composio.execute_action(actions["actions"][0], connected_account_id=conn, input={...})
```
