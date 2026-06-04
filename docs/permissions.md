# Permissions and dry-run

A tool that reads your calendar is very different from a tool that empties
it. mAIvn makes that difference explicit: every tool declares what kind of
work it does, so the agent host can enforce least privilege, warn a user
before something irreversible runs, or refuse to register a destructive
tool without operator approval. By default `maivn-tools` assumes a tool is
read-only — anything that mutates provider state has to opt in.

This page covers the two mechanisms behind that contract: **permission
flags** (what a tool is allowed to touch) and **dry-run** (let a tool
describe its changes without making them).

The permission types live in the core SDK (`maivn`), so a custom toolset
does **not** need to install `maivn-tools` just to declare permissions on
its own methods:

```python
from maivn import PermissionFlag, PermissionSet, require_permissions, toolify, toolset
```

For callers that depend on the original layout, `maivn_tools.core.permissions`
re-exports `PermissionFlag`, `PermissionSet`, and `require_permissions`. New
code should import the permission types and decorators from `maivn` directly.

## Permission flags

`PermissionFlag` is a `Flag` enum: combine values with `|`.

| Flag | Meaning |
| --- | --- |
| `READ` | Reads existing data. |
| `WRITE` | Creates or updates data. |
| `DELETE` | Deletes or archives data. |
| `EXPORT` | Bulk exports data. |
| `IMPORT` | Bulk imports or replaces data. |
| `ADMIN` | Touches admin-only surfaces (users, roles, audit). |
| `IMPERSONATE` | Acts on behalf of another principal. |

`PermissionSet` wraps a flag bitfield and offers ergonomic helpers:

```python
from maivn import PermissionFlag, PermissionSet, require_permissions

write_only = PermissionSet(PermissionFlag.WRITE)
all_perms = PermissionSet.all()

assert PermissionFlag.WRITE in write_only
assert write_only.to_list() == ["write"]
assert PermissionSet.from_names(["read", "write"]).flags == (
    PermissionFlag.READ | PermissionFlag.WRITE
)
assert PermissionSet(PermissionFlag.DELETE).is_destructive()
```

Hosts can run their own gate:

```python
require_permissions(
    granted=PermissionSet(PermissionFlag.READ),
    required=PermissionSet(PermissionFlag.READ | PermissionFlag.WRITE),
)
# Raises PermissionError: Missing required permissions: ['write']
```

## Declaring tool permissions

Tool callables produced by generic adapters expose `permissions` and
`destructive` attributes. When you write a tool by hand, set them on the
callable so hosts can inspect them:

```python
def archive_message(message_id: str) -> dict:
    ...

archive_message.permissions = PermissionSet(PermissionFlag.WRITE | PermissionFlag.DELETE)
archive_message.destructive = True
```

`destructive=True` is a coarser hint than `permissions`. It is the right
signal for a host UI to warn users; `permissions` is the right signal for
machine-readable gating.

## Dry run

Write-capable tools should accept a `dry_run` flag. When it is true the
tool must:

1. Validate the inputs as if the call were real.
2. Compute the change set it would apply.
3. Return a `DryRunOutcome` describing the planned change.
4. Make no provider mutation.

```python
from maivn_tools import DryRunOutcome, DryRunPlan, dry_run_capable


@dry_run_capable
def archive_message(message_id: str, *, dry_run: bool = False) -> DryRunOutcome | dict:
    if dry_run:
        return DryRunOutcome(
            tool="archive_message",
            plans=(
                DryRunPlan(
                    operation="archive",
                    target=f"messages/{message_id}",
                    before={"folder": "inbox"},
                    after={"folder": "archive"},
                ),
            ),
        )
    return provider_api.archive(message_id)
```

`@dry_run_capable` is a marker decorator. It does not change behavior but
attaches `__maivn_dry_run_capable__ = True` to the callable so hosts and
tests can discover which tools honor the contract without executing them.

## Recommended defaults

- All tools begin life as `PermissionSet(PermissionFlag.READ)`.
- Write tools opt in to `WRITE` only.
- Delete, export, import, and admin tools opt in **explicitly** to those
  flags **in addition to** `destructive=True`.
- Tools that act on behalf of another user set `IMPERSONATE` and document
  the impersonation contract.
