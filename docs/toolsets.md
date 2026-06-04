# Writing your own toolset

A toolset is just a plain Python class whose methods become agent tools.
If you already have a class that talks to a service — a database client,
an internal API wrapper, a reporting helper — you can expose its methods
to an `Agent` by adding two decorators, no boilerplate in between. That
is exactly how every provider connector in `maivn-tools` is built, and
the same pattern works in your own code.

The `@toolset` and `@toolify` decorators in `maivn` are the recommended way
to expose a configured class as a collection of Agent tools. Every provider
connector in `maivn-tools` follows this pattern; the same decorators work
in your own code.

```python
from maivn import Agent, toolify, toolset
from maivn_tools import PermissionFlag, PermissionSet


@toolset(prefix="reports")
class WeeklyReportsToolSet:
    """Pull weekly KPI reports from an internal SQLite warehouse."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def weekly_signups(self, week_of: str) -> list[dict]:
        """Signup counts by source for the week starting ``week_of`` (YYYY-MM-DD)."""
        ...

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def revenue_per_signup(self, week_of: str) -> float:
        """Compute revenue per signup for ``week_of``."""
        ...


agent = Agent(model="auto")
agent.add_toolset(WeeklyReportsToolSet("/srv/warehouse.db"))
```

After `add_toolset` returns, the agent has two new tools — `REPORTS_weekly_signups`
and `REPORTS_revenue_per_signup` — with parameters and descriptions inferred from
the methods. The toolset prefix is uppercased and joined to the method name with
an underscore so the generated names match the OpenAI/Anthropic tool-name regex
(`^[a-zA-Z0-9_-]{1,64}$`).

## Agent-ready toolset checklist

The success criterion for a toolset is simple: a developer should be able to
plug it into an agent and get useful behavior from an ordinary user request:

```python
agent.add_toolset(MyToolSet(...))
```

If the toolset needs a custom DAG, a long system prompt, or demo-specific
wrappers to work, improve the toolset interface first.

Use this checklist when creating or reviewing a toolset:

- **Permissions are accurate.** Every method has the right
  `permissions=PermissionSet(...)`; irreversible tools also use
  `destructive=True`.
- **Filtering works.** Read-only agents can use `include_tags=["read"]`;
  non-destructive agents can use `exclude_tags=["destructive"]`.
- **Docstrings are operational.** Each tool explains when to use it, what
  arguments mean, what it returns, and which returned values are intended for
  follow-up calls.
- **List/search defaults are human-readable.** Broad tools return compact
  summaries by default instead of full provider payloads.
- **IDs are not noise.** Raw provider IDs are omitted by default unless a
  follow-up tool needs them. Prefer an opt-in flag such as
  `include_ids=False`.
- **Broad calls are bounded.** Defaults use small useful limits, usually 10 or
  25, and expensive metadata expansion has its own cap.
- **Write tools accept natural read results when safe.** If a read tool returns
  a record with `record_id`, a write tool can accept either the raw ID or that
  record shape when the mapping is obvious and non-dangerous.
- **Structured outputs are documented.** Pydantic model/final tools should use
  short `Field(description=...)` values on every field.
- **Provider code stays generic.** Use SDK `ToolOverride` registration options
  for app-specific names, descriptions, default args, dependencies, or
  final-tool behavior.

For example, a search tool should favor compact summaries:

```python
@toolify(permissions=PermissionSet(PermissionFlag.READ))
def search_records(
    query: str,
    *,
    limit: int = 10,
    include_ids: bool = False,
) -> dict:
    """Search records and return compact summaries.

    Returns `record_ref`, title, owner, status, and updated time. Raw provider
    IDs are omitted unless `include_ids=True`; use IDs only for follow-up tool
    calls, not final answers.
    """
    ...
```

And a related write tool can accept the natural output shape when safe:

```python
@toolify(permissions=PermissionSet(PermissionFlag.WRITE))
def update_record(
    record: str | dict,
    *,
    status: str,
) -> dict:
    """Update one record by provider ID or by a record returned from search."""
    ...
```

## Naming convention

Toolset classes use the **`XToolSet`** suffix:

| Service | Class |
| --- | --- |
| Local filesystem | `LocalFilesToolSet` |
| SQLite / PostgreSQL | `SQLiteToolSet`, `PostgresToolSet` |
| Email | `IMAPToolSet`, `SMTPToolSet` |
| GitHub / Slack | `GitHubToolSet`, `SlackToolSet` |
| Google Workspace | `GmailToolSet`, `GoogleCalendarToolSet`, `GoogleDriveToolSet` |
| Microsoft 365 | `OutlookMailToolSet`, `OutlookCalendarToolSet`, `MicrosoftFilesToolSet` |
| Atlassian / CRM | `JiraToolSet`, `ZendeskToolSet`, `HubSpotToolSet`, `SalesforceToolSet` |
| Partner hubs | `WorkatoToolSet`, `PipedreamToolSet`, `MakeToolSet`, `N8nToolSet`, `ComposioToolSet` |
| **Builder (special)** | `ZapierConnector`, `GenericHttpConnector`, `OpenAPIConnector`, `GraphQLConnector`, `WebhookListener`, `MCPBridge` |

The builder classes keep the `Connector` suffix because their tool surface
is dynamic (e.g. Zapier exposes one tool per configured webhook URL) and
they don't fit the `@toolset` class-walk model. `register_connector`
dispatches to the right path automatically.

## Decorator semantics

### `@toolset(...)`

Marks a class as a toolset. Two forms:

```python
@toolset
class Plain: ...

@toolset(prefix="github", tags=["developer"], require_marker=True)
class Configured: ...
```

| Argument | Default | Effect |
| --- | --- | --- |
| `prefix` | snake_case class name | Prepended to each method-tool name. The prefix is uppercased and joined with `_` (e.g. `prefix='gmail'` + method `get_message` → `GMAIL_get_message`). Keeps tool names within the OpenAI/Anthropic tool-name regex and makes the namespace boundary readable. |
| `tags` | `()` | Tags applied to every method-tool produced. |
| `require_marker` | `True` | When True, only `@toolify`-marked methods are tools. Setting `False` exposes every public method — discouraged for new code. |
| `metadata` | `{}` | Free-form metadata merged into every method-tool. |

### `@toolify(...)`

Marks an individual method as a tool. Two forms:

```python
class Example:
    @toolify
    def simple(self) -> None:
        """Bare form. No permission tags, no destructive marker."""

    @toolify(
        name="renamed",                           # override exposed tool name
        description="...",                        # override the docstring
        permissions=PermissionSet(PermissionFlag.WRITE),
        destructive=False,
        always_execute=False,
        final_tool=False,
        tags=["payments"],
        metadata={"audit_zone": "high"},
        before_execute=...,
        after_execute=...,
    )
    def write_payment(self, ...): ...
```

`@toolify` coexists with the existing dependency decorators
(`@depends_on_tool`, `@depends_on_agent`, `@compose_artifact_policy`, etc.).
Order doesn't matter — each decorator attaches its own attribute and the
dependency collector reads them all at registration time.

## Registration

```python
agent.add_toolset(instance)         # register every @toolify method
agent.add_toolset(other_instance)   # multiple toolsets accumulate
```

The SDK walks the class, finds every `@toolify`-marked method, and creates
one `MethodTool` per method bound to the instance. Tools are appended to
`agent.tools` so anything that inspects the agent's tool list sees them
the same way it sees free-callable tools.

## Filtering at registration

`add_toolset` accepts four optional filter keywords. Each toolset class
ships its **complete tool surface**; filters let callers narrow that
surface to just what a given agent needs.

```python
agent.add_toolset(instance, *,
    include=None,        # list[str]: only these method names register
    exclude=None,        # list[str]: skip these method names
    include_tags=None,   # list[str]: only methods with any matching tag
    exclude_tags=None,   # list[str]: skip methods with any matching tag
)
```

Filters compose: a method must pass every active filter.

### Examples

**Whitelist one method:**

```python
# An agent that should only be able to send Gmail, not read it.
agent.add_toolset(
    GmailToolSet(token=cache),
    include=["send_email"],
)
```

**Blacklist destructive methods:**

```python
# Keep everything except the destructive operations.
agent.add_toolset(
    GoogleDriveToolSet(token=cache),
    exclude_tags=["destructive"],
)
```

**Only read tools:**

```python
# Read-only Google Drive access.
agent.add_toolset(
    GoogleDriveToolSet(token=cache),
    include_tags=["read"],
)
```

**Combine include + exclude:**

```python
# All Slack tools EXCEPT post_message and search_messages.
agent.add_toolset(
    SlackToolSet(token=bot_token),
    exclude=["post_message", "search_messages"],
)
```

**By user-defined tags:**

```python
@toolset(prefix="dispatch")
class DispatchToolSet:
    @toolify(tags=["email"])
    def send_alert(self, ...): ...

    @toolify(tags=["sms"])
    def send_sms(self, ...): ...

    @toolify(tags=["push"])
    def send_push(self, ...): ...

# Only email + SMS, no push.
agent.add_toolset(DispatchToolSet(), include_tags=["email", "sms"])
```

### Auto-derived tags

When evaluating `include_tags` / `exclude_tags`, the SDK augments the
method's user-supplied tags with values derived from `permissions` and
`destructive`:

| Source | Auto-tag added |
| --- | --- |
| `permissions=PermissionSet(PermissionFlag.READ)` | `"read"` |
| `permissions=PermissionSet(PermissionFlag.WRITE)` | `"write"` |
| `permissions=PermissionSet(PermissionFlag.DELETE)` | `"delete"`, `"destructive"` |
| `permissions=PermissionSet(PermissionFlag.EXPORT)` | `"export"` |
| `permissions=PermissionSet(PermissionFlag.IMPORT)` | `"import"`, `"destructive"` |
| `permissions=PermissionSet(PermissionFlag.ADMIN)` | `"admin"`, `"destructive"` |
| `permissions=PermissionSet(PermissionFlag.IMPERSONATE)` | `"impersonate"`, `"destructive"` |
| `destructive=True` | `"destructive"` |

That's why `include_tags=["read"]` and `exclude_tags=["destructive"]`
work without you having to add those strings to every method's `tags=`
list manually. The auto-tags are filter-only — the `MethodTool.tags`
attribute still reflects exactly what you declared.

### Names use the *post-resolution* method name

`include` / `exclude` match against:

* The method's Python attribute name (default), or
* The `name=` override on `@toolify(name=...)`.

Match is on the **unprefixed** name — no need to know the toolset prefix
when narrowing.

### Filter-to-zero behavior

If filtering removes every method and the toolset has
`require_marker=True` (the default), `add_toolset` raises `ValueError`
with a clear hint that filters dropped everything. Set
`require_marker=False` if you want filter-to-zero to silently pass.

## Tool inspection

Each `MethodTool` produced by `add_toolset` carries:

| Attribute | Source |
| --- | --- |
| `name` | `f"{PREFIX}_{method_name}"` (prefix uppercased, joined with `_`) or `@toolify(name=...)` override. |
| `description` | The method's docstring or `@toolify(description=...)`. |
| `qualified_name` | `"OwnerClass.method_name"` — used in audit logs. |
| `owner` | The toolset instance. Useful for cleanup; the runtime never inspects it. |
| `func` | The bound method (`instance.method`). |
| `metadata["permissions"]` | `PermissionSet` from `@toolify(permissions=...)`. |
| `metadata["destructive"]` | `True` when `@toolify(destructive=True)`. |
| `tags` | Tags merged from `@toolset(tags=...)` + `@toolify(tags=...)`. |
| `dependencies` | Resolved from any stacked `@depends_on_*` decorators. |

The SDK's runtime treats `MethodTool` exactly like `FunctionTool` for
execution — bound methods invoke just like free callables, so `self`
binding is preserved without any custom logic.

## What does NOT become a tool

`add_toolset` skips, in order:

1. Names starting with `_` (private convention).
2. `@property`, `@classmethod`, `@staticmethod` declarations.
3. Nested classes.
4. Non-callable attributes.
5. Public methods without `@toolify` — when `require_marker=True` (default).

## Errors at registration

`add_toolset` raises clear errors before any tool is registered:

| Condition | Exception |
| --- | --- |
| Class missing `@toolset` decorator | `TypeError` |
| No `@toolify`-marked methods (with `require_marker=True`) | `ValueError` |
| All methods removed by filters (with `require_marker=True`) | `ValueError` (mentions filters) |
| Two methods resolve to the same tool name | `ValueError` |
| Method missing a docstring and no `description=` override | `ValueError` from `ToolifyService` |

## Builder-style connectors

For backwards compatibility and for connectors whose tool surface is
**data-driven** rather than method-driven, the `Connector` suffix and
`tools() -> list[Callable]` pattern still works. `register_connector`
detects the absence of `@toolset` and falls through to that path.

Builder connectors in `maivn-tools`:

* `GenericHttpConnector` — tools come from a runtime list of `HttpEndpoint`.
* `OpenAPIConnector` — tools come from a parsed OpenAPI document.
* `GraphQLConnector` — tools come from a runtime list of `GraphQLOperation`.
* `WebhookListener`, `MCPBridge` — single-purpose adapters with no
  classical method-tool surface.
* `ZapierConnector` — dynamic per-webhook tool names.

These do **not** accept `include`/`exclude` / tag filters through
`add_toolset`. If you need to narrow a builder, filter the input list
before construction (e.g., pass a subset of `HttpEndpoint`s).
