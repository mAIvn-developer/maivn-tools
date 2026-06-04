# Project management

Issue trackers and team-planning tools. Every connector follows the
standard `@toolset` / `@toolify` shape and the agent-ready toolset
pattern (compact summaries by default, opt-in raw IDs, tolerant write
inputs).

## JiraToolSet

`JiraToolSet` wraps the Atlassian Jira Cloud REST API v3 (with a small
slice of the Jira Agile API for boards and sprints). It authenticates
with HTTP Basic auth using your Atlassian email and an API token issued
at https://id.atlassian.com/manage-profile/security/api-tokens.

```python
from maivn import Agent
from maivn_tools import JiraToolSet, register_connector

connector = JiraToolSet(
    base_url="https://acme.atlassian.net",
    email="ops@acme.com",
    api_token=secrets["JIRA_API_TOKEN"],
)
agent = Agent(model="auto")
register_connector(agent, connector)
```

### Tools

**Identity.** `myself`.

**Issues.** `search_issues` (JQL), `get_issue`, `list_transitions`,
`create_issue`, `update_issue`, `transition_issue`, `assign_issue`,
`delete_issue` (destructive).

**Comments and worklog.** `list_comments`, `add_comment`,
`update_comment`, `delete_comment` (destructive), `list_worklogs`,
`add_worklog`.

**Links and attachments.** `link_issues`, `delete_issue_link`
(destructive), `list_attachments`, `delete_attachment` (destructive).

**Projects, users, metadata.** `list_projects`, `get_project`,
`list_issue_types`, `get_user`, `search_users`, `list_statuses`,
`list_priorities`, `list_resolutions`, `list_fields`.

**Agile (boards, sprints, versions).** `list_boards`, `list_sprints`,
`get_sprint`, `list_versions`.

`extra_fields` on `create_issue` is merged into the request payload so
the caller can set custom fields (e.g. `customfield_10010`).

### Agent-ready behavior

- `search_issues` returns compact summaries by default. Each summary
  carries a stable `issue_ref` (`issue_1`, `issue_2`, ...) plus the
  issue `key` (e.g. `ENG-123` — the canonical user-facing handle),
  `summary`, `status`, `assignee`, `priority`, `issue_type`, and
  `updated`. The issue key is safe to surface in final answers.
- `list_projects` returns the same compact shape with a stable
  `project_ref` (`project_1`, ...) plus the project `key`, `name`,
  `type`, and `lead`.
- Default `max_results` is 25 on `search_issues` (max 100) and 25 on
  `list_projects`.
- Jira numeric `id` values are hidden by default on both tools. Pass
  `include_ids=True` to add `issue_id` or `project_id` to each summary
  — the issue key is normally enough, raw IDs are internal handles.
- Pass `include_metadata=False` on `search_issues` or `list_projects`
  to receive the raw Jira response, including `startAt`, `total`, and
  `isLast` for pagination.
- `get_issue`, `update_issue`, `add_comment`, `transition_issue`,
  `assign_issue`, `delete_issue`, `list_comments`, `list_transitions`,
  `list_worklogs`, `add_worklog`, and `list_attachments` accept either
  a key string (`"ENG-123"`), a summary dict from `search_issues`, or
  a list of such dicts. The connector resolves the key from `key`,
  `issue_key`, or `issueKey`.

### Destructive tools

`delete_issue`, `delete_comment`, `delete_issue_link`, and
`delete_attachment` carry `destructive=True`. Issue and link deletes
are permanent — confirm with the user, or filter them out with
`exclude_tags=["destructive"]`.

### Example: summary-mode search

```python
agent.add_toolset(JiraToolSet(base_url="https://acme.atlassian.net",
                              email="ops@acme.com",
                              api_token=secrets["JIRA_API_TOKEN"]))

response = connector.search_issues(
    "project = ENG AND status = 'In Progress' ORDER BY updated DESC",
    max_results=10,
)
# response == {
#   "issues": [
#     {"issue_ref": "issue_1", "key": "ENG-512",
#      "summary": "Fix login flakiness", "status": "In Progress",
#      "assignee": "Casey K.", "priority": "High",
#      "issue_type": "Bug", "updated": "..."},
#     ...
#   ],
#   "startAt": 0, "maxResults": 10, "total": 3,
# }
```

The key is enough to drive follow-up actions — no `include_ids` round
trip required:

```python
hits = connector.search_issues("assignee = currentUser()")["issues"]
connector.transition_issue(hits[0], transition_id="31")
```

### Live tests

Set `MAIVN_TOOLS_JIRA_LIVE_BASE_URL`, `MAIVN_TOOLS_JIRA_LIVE_EMAIL`, and
`MAIVN_TOOLS_JIRA_LIVE_TOKEN` to exercise the connector against a
sandbox Jira Cloud site. See [testing.md](../testing.md).

## LinearToolSet

`LinearToolSet` wraps the
[Linear GraphQL API](https://developers.linear.app/).

```python
from maivn_tools import LinearToolSet

connector = LinearToolSet(api_key=secrets["LINEAR_API_KEY"])
```

Pass `use_bearer=True` if the credential is an OAuth bearer rather
than a personal API key.

### Tools

`viewer`, `list_teams`, `list_users`, `list_projects`, `list_cycles`,
`list_issues` (filter follows Linear's `IssueFilter` shape),
`get_issue` (UUID or shortcut like `ENG-123`), `create_issue`,
`update_issue`, `archive_issue` (destructive), `list_comments`,
`create_comment`, `graphql` (escape hatch for arbitrary
queries / mutations).

### Agent-ready behavior

- `list_issues` returns compact summaries by default. Each summary
  carries a stable `issue_ref` (`issue_1`, `issue_2`, ...) plus the
  Linear `identifier` (e.g. `ENG-123` — the canonical user-facing
  handle), `title`, `status`, `priority`, `assignee`, `team` key,
  `updated_at`, and `url`. The identifier is safe to show in final
  answers.
- Default `first` is 25 on `list_issues`, `list_teams`, `list_users`,
  `list_projects`, and `list_cycles` (max 250).
- The GraphQL `id` (UUID) is hidden by default on `list_issues`. Pass
  `include_ids=True` to add `issue_id` to each summary — only needed
  for tools that explicitly require the UUID; most operations accept
  the identifier directly.
- Pass `include_metadata=False` on `list_issues` to receive the raw
  Linear `{"issues": {"nodes": [...], "pageInfo": ...}}` response.
  The other list tools always return the raw GraphQL payload.
- `get_issue`, `update_issue`, `archive_issue`, `list_comments`, and
  `create_comment` accept either a Linear identifier string
  (`"ENG-123"`), a UUID string, a summary dict from `list_issues`, or
  a list of such dicts. The connector resolves the handle from
  `identifier`, `issue_id`, or `id`.

### Destructive tools

`archive_issue` carries `destructive=True`. Archive is a soft-delete
(recoverable through the Linear UI), but should still be confirmed
with the user, or filtered out with `exclude_tags=["destructive"]`.
`graphql` is gated with READ permission; if you need raw mutations,
gate it behind a write permission in your own override.

### Example: summary-mode list

```python
agent.add_toolset(LinearToolSet(api_key=secrets["LINEAR_API_KEY"]))

response = connector.list_issues(
    filter={"team": {"key": {"eq": "ENG"}}, "state": {"name": {"eq": "Todo"}}},
    first=10,
)
# response == {
#   "issues": [
#     {"issue_ref": "issue_1", "identifier": "ENG-512",
#      "title": "Fix login flakiness", "status": "Todo",
#      "priority": 2, "assignee": "Casey K.", "team": "ENG",
#      "updated_at": "...", "url": "https://linear.app/..."},
#     ...
#   ],
#   "pageInfo": {"hasNextPage": False, "endCursor": "..."},
# }
```

The identifier is enough to drive follow-up actions:

```python
hits = connector.list_issues(
    filter={"assignee": {"isMe": {"eq": True}}}
)["issues"]
connector.create_comment(issue_id=hits[0], body="Picking this up.")
```
