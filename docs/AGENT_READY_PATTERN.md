# Agent-Ready ToolSet Pattern Spec

**Reference implementation:** `src/maivn_tools/connectors/google_workspace/gmail.py` (GmailToolSet).
**Reference demo:** `apps/maivn-demos/demos/custom_toolset_demo.py` (FleetOpsToolSet).

A developer should be able to plug any ToolSet into an Agent with
`agent.add_toolset(MyToolSet(...))` and get useful behavior from ordinary
user prompts — no custom graph wiring, no demo-specific wrappers, no
long system prompts.

---

## 1. Permissions and tags

Every `@toolify` method must declare a `PermissionSet`:

```python
@toolify(permissions=PermissionSet(PermissionFlag.READ))
def list_records(self, ...) -> ...:
    ...

@toolify(permissions=PermissionSet(PermissionFlag.WRITE))
def create_record(self, ...) -> ...:
    ...

@toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
def delete_record(self, ...) -> ...:
    ...
```

Rules:
- READ tools are filterable with `include_tags=["read"]`.
- WRITE tools should be separate from READ tools.
- DELETE or irreversible tools must use `destructive=True` and are
  filterable with `exclude_tags=["destructive"]`.
- The "read"/"write"/"destructive" tags are auto-derived from
  `permissions`/`destructive`; do not maintain a parallel `tags=` list.

## 2. Tool docstrings

Each tool docstring should briefly explain:
- **when to use** the tool ("Best first tool for triage", "Use after
  list_records to fetch full content", etc.).
- **what arguments mean** (especially anything non-obvious).
- **what shape** the tool returns.
- **what follow-up tool** should consume any returned identifiers.
- whether **IDs are internal handles** that should not appear in final
  answers.

Keep it short. Optimize for model usability, not API-reference prose.

## 3. Human-readable defaults for search/list/lookup

For broad search/list tools:

- Return **compact, human-readable summaries by default**.
- Avoid dumping raw provider IDs unless needed.
- Prefer stable display refs like `message_ref`, `record_ref`,
  `ticket_ref`, `page_ref`, etc.
- Add an opt-in flag `include_ids: bool = False` when downstream tools
  need raw IDs.
- If raw IDs are included, the docstring must say they are internal
  handles and should not be exposed in final answers.

Example pattern:

```python
@toolify(permissions=PermissionSet(PermissionFlag.READ))
def list_records(
    self,
    *,
    table_id: str,
    max_results: int = 25,
    include_ids: bool = False,
) -> dict[str, Any]:
    """Search records in a table.

    Best first tool for record exploration. Returns compact summaries
    with a stable ``record_ref`` (``record_1``, ``record_2``, ...) that
    is safe to show in final answers. Raw provider IDs are omitted by
    default — they are internal handles. Set ``include_ids=True`` only
    when a follow-up tool (update_record, delete_record) needs the raw
    ID.
    """
    ...
    summaries = []
    for index, record in enumerate(records, start=1):
        summary = {
            "record_ref": f"record_{index}",
            # ...display fields like name, status, created_at, ...
        }
        if include_ids:
            summary["record_id"] = record["id"]
        summaries.append(summary)
    return {"records": summaries, ...}
```

## 4. Bounded list/search behavior

- Broad list/search tools should default to a small useful limit (10
  or 25, not 100+).
- Expensive metadata expansion should be capped — if summary mode
  requires a per-record fetch, cap to a smaller limit (e.g. 10 in Gmail).
- Raw/full output should be opt-in (e.g. `include_metadata=False` returns
  raw provider response with all fields).
- Preserve pagination tokens where provider APIs support them.

## 5. Tolerant write-tool inputs

Write tools should accept the natural output of corresponding read/list
tools when practical. For example, if `list_records()` returns records
with `record_id` (in `include_ids=True` mode) or `record_ref` paired with
raw IDs in another field, then `update_record()` should tolerate:

- the raw ID string
- the returned record dict (look up `record_id` inside it)
- a list of returned records (select the first valid candidate when safe
  and obvious)

Do not make write tools dangerously permissive. Only add tolerance where
it removes obvious agent friction and preserves safe behavior. See
`FleetOpsToolSet._select_vehicle_id` for the reference pattern.

## 6. Structured model fields

Any Pydantic model intended as a model/final tool must use brief
`Field(description=...)` values for all fields. Descriptions should be
short and operational, not verbose.

## 7. Keep provider toolsets generic

Do not bake demo-specific behavior into provider toolsets. Use the SDK
`ToolOverride` pattern for app-specific behavior:

- direct tools: `agent.add_tool(..., override=ToolOverride(...))`
- toolsets: `agent.add_toolset(toolset, overrides={"method_name": ToolOverride(...)})`
- MCP servers: `MCPServer(..., tool_overrides={"raw_tool_name": ToolOverride(...)})`

Use overrides for: app-specific descriptions, default args,
always-execute/final-tool behavior, app-specific dependencies, renamed
public tool names.

## 8. Demo prompts

Demo prompts should be plain user workflows. They should not instruct
exact tool order unless the workflow truly requires it. If the demo only
works with detailed tool choreography, fix the toolset instead.

## 9. Tests

For each updated toolset, add or update tests for:

- Default search/list summaries (verify `_ref` is present and raw IDs
  are absent).
- `include_ids=True` returns raw IDs (verify the opt-in works).
- Permission/tag filtering on the toolset class (`include_tags=["read"]`
  drops write/destructive tools).
- Tolerant input behavior for write tools where added.

## Constraints

- Do not remove useful existing capabilities.
- Do not hide IDs when a provider operation cannot be performed without
  them; make IDs opt-in or return them only in fields intended for
  follow-up tool calls.
- Final answers should be useful to humans and should not be littered
  with raw provider IDs.
- The core success criterion: an Agent with a ToolSet should work from
  ordinary user requests.
