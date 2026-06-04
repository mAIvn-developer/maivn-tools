# Developer platforms

Source-control hosting and CI/CD providers. Each toolset gives an agent
a uniform surface over repositories, issues, pull/merge requests, and
pipelines for one platform. Every connector follows the standard
`@toolset` / `@toolify` shape; the snippets below show only the
constructor and the headline tool surface.

> Tip: most agents only need read access. Register with
> `add_toolset(..., include_tags=["read"])` to drop write / delete tools,
> or `exclude_tags=["destructive"]` to drop the irreversible ones.

All four connectors in this group follow the same agent-ready pattern:
broad list/search tools return compact summaries by default with a stable
`*_ref` ordinal (`issue_ref`, `pr_ref`, `repo_ref`, etc.). Raw provider
IDs (GitHub `id`/`node_id`, GitLab numeric `project_id`, Bitbucket `uuid`,
ADO GUIDs) are hidden unless `include_ids=True` is passed. User-facing
identifiers like `issue_number`/`iid`, `pr_number`/`pull_request_id`,
`full_name`/`path_with_namespace`/`slug`, `branch`, `tag_name`, and `sha`
are always shown -- they are stable refs safe to render in final answers.
Where the underlying list returns a wrapped envelope, an
`include_metadata=False` flag returns the raw provider response.

## GitHubToolSet

`GitHubToolSet` wraps the GitHub REST API v3. It authenticates with a
classic personal access token, a fine-grained token, or an installation
token issued by a GitHub App.

```python
from maivn import Agent
from maivn_tools import GitHubToolSet, register_connector

connector = GitHubToolSet(token="ghp_...")
agent = Agent(model="auto")
register_connector(agent, connector)
```

The connector always sends:

```
Authorization: Bearer <token>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
User-Agent: maivn-tools-github/0.1
```

GitHub rejects requests without a user agent, so the connector enforces
a non-empty `user_agent` argument. For GitHub Enterprise, override
`base_url` (e.g. `https://ghe.example.com/api/v3`).

### Tools

**User and rate-limit.** `get_authenticated_user`, `get_user(username)`,
`get_rate_limit`.

**Repositories, branches, commits.** `list_repositories`,
`get_repository`, `list_branches`, `get_branch`, `list_commits`,
`get_commit`, `compare_commits`, `list_tags`, `create_branch`,
`delete_branch` (destructive).

**Repository contents.** `get_file_contents`, `get_readme`,
`create_or_update_file`, `delete_repo_file` (destructive).

**Issues.** `list_issues`, `get_issue`, `list_issue_comments`,
`create_issue`, `update_issue`, `close_issue`, `reopen_issue`,
`add_issue_labels`, `remove_issue_label`, `add_issue_comment`,
`update_issue_comment`, `lock_issue`, `unlock_issue`,
`delete_issue_comment` (destructive).

**Pull requests.** `list_pull_requests`, `get_pull_request`,
`list_pull_request_files`, `list_pull_request_commits`,
`list_pull_request_reviews`, `create_pull_request`,
`update_pull_request`, `merge_pull_request`,
`create_pull_request_review`, `request_pull_request_reviewers`.

**Releases.** `list_releases`, `get_release`, `get_latest_release`,
`create_release`, `update_release`, `delete_release` (destructive).

**Actions, workflows, checks.** `list_workflows`, `list_workflow_runs`,
`get_workflow_run`, `list_check_runs`, `cancel_workflow_run`,
`rerun_workflow`, `dispatch_workflow`.

**Collaborators, organizations, forks.** `list_collaborators`,
`add_collaborator`, `remove_collaborator` (destructive),
`list_organization_repos`, `list_organization_members`, `list_teams`,
`list_forks`, `fork_repository`, `list_stargazers`.

**Search.** `search_code`, `search_issues`, `search_repositories`,
`search_users`.

GitHub returns standard HTTP status codes; the runtime maps them to the
`ConnectorError` hierarchy (`401` -> `AuthError`, `403` ->
`PermissionDeniedError`, `404` -> `NotFoundError`, `422` ->
`ValidationError`, `429` -> `RateLimitError`, `5xx` -> `RetryableError`).

### Agent-ready behavior

- `list_repositories`, `list_issues`, `list_pull_requests`,
  `list_branches`, `list_commits`, `list_releases`, `list_workflows`,
  `list_workflow_runs`, `list_organization_repos`, `search_issues`, and
  `search_repositories` return compact summaries by default. Each entry
  carries a stable ordinal ref (`repo_ref`, `issue_ref`, `pr_ref`,
  `branch_ref`, `commit_ref`, `release_ref`, `workflow_ref`, `run_ref`)
  plus the user-facing identifier (`full_name`, `issue_number`,
  `pr_number`, `branch`, `sha` / `short_sha`, `tag_name`, `workflow_id`,
  `run_id`).
- Raw GitHub `id` / `node_id` are hidden by default; pass
  `include_ids=True` to opt in. Pass `include_metadata=False` for the
  unmodified provider list / search envelope.
- Default `per_page` is **10** for list/search tools, **25** for
  `list_branches` / `list_workflows`.
- Write tools that take `(owner, repo)` accept either two strings, a
  single `"owner/repo"` shorthand, or a repo dict returned by
  list/search/get. `update_issue`, `close_issue`, `reopen_issue`,
  `merge_pull_request`, and `delete_branch` additionally accept the
  issue / PR / branch dict directly.
- Destructive tools: `delete_branch`, `delete_repo_file`,
  `delete_issue_comment`, `delete_release`, `remove_collaborator`.

Example (summary mode):

```python
result = connector.list_issues("octocat/Hello-World", state="open")
# {"issues": [{"issue_ref": "issue_1", "issue_number": 42, "title": ..., "state": "open", ...}, ...], "count": 10, "page": 1, "state": "open"}
followup = connector.close_issue(result["issues"][0])  # accepts the dict directly
```

## GitLabToolSet

GitLab API v4 with a personal access token (or OAuth bearer).

```python
from maivn_tools import GitLabToolSet

connector = GitLabToolSet(token=secrets["GITLAB_TOKEN"])
```

Tools: `get_current_user`, `list_users`, `list_projects`, `get_project`,
`list_issues`, `get_issue`, `create_issue`, `update_issue`,
`delete_issue` (destructive), `list_merge_requests`,
`get_merge_request`, `create_merge_request`, `merge_merge_request`,
`list_pipelines`, `get_pipeline`, `trigger_pipeline`, `get_file`,
`list_branches`, `list_commits`, `search_blobs`.

### Agent-ready behavior

- `list_projects`, `list_issues`, `list_merge_requests`,
  `list_pipelines`, `list_branches`, and `list_commits` return compact
  summaries with stable refs (`project_ref`, `issue_ref`, `mr_ref`,
  `pipeline_ref`, `branch_ref`, `commit_ref`).
- User-facing identifiers always shown: `path_with_namespace`, `iid`
  (the project-scoped issue / MR number), branch `name`, `short_sha`,
  pipeline `pipeline_id`.
- Raw GitLab numeric `project_id` / `issue_id` / `mr_id` / full `sha`
  are omitted unless `include_ids=True`. Pass `include_metadata=False`
  for the raw provider list.
- Default `per_page` is **10** for list tools, **25** for
  `list_branches`.
- `project` arguments on read and write tools accept a numeric ID, a
  `"group/repo"` path, or a project dict returned by `list_projects` /
  `get_project`. `update_issue` additionally accepts
  `update_issue(issue_dict, fields)` when the dict was returned with
  `include_ids=True` (so the project reference is available).
- Destructive tools: `delete_issue`. `merge_merge_request` is destructive
  in effect -- confirm before calling.

Example:

```python
result = connector.list_merge_requests("acme/web", state="opened")
# {"merge_requests": [{"mr_ref": "mr_1", "iid": 17, "title": ..., "source_branch": ..., ...}], ...}
```

## BitbucketToolSet

Bitbucket Cloud REST API v2. Accepts a bearer token *or*
`username + app_password`.

```python
from maivn_tools import BitbucketToolSet

connector = BitbucketToolSet(token=secrets["BITBUCKET_TOKEN"])
```

Tools: `get_current_user`, `list_workspaces`, `list_repositories`,
`get_repository`, `list_pull_requests`, `get_pull_request`,
`create_pull_request`, `merge_pull_request`, `decline_pull_request`,
`list_issues`, `create_issue`, `list_pipelines`, `run_pipeline`,
`list_branches`, `get_file_contents`.

### Agent-ready behavior

- `list_repositories`, `list_pull_requests`, `list_issues`,
  `list_pipelines`, and `list_branches` return compact summaries with
  stable refs (`repo_ref`, `pr_ref`, `issue_ref`, `pipeline_ref`,
  `branch_ref`).
- User-facing identifiers always shown: `full_name` / `slug`, `pr_id`,
  `issue_id`, pipeline `build_number`, branch `name`, `short_sha`.
- Opaque Bitbucket UUIDs hidden by default; pass `include_ids=True` to
  opt in. Pass `include_metadata=False` for the raw paged response (with
  the provider `next` link preserved).
- Default `pagelen` is **10**.
- `(workspace, repo_slug)` arguments on read and write tools accept two
  strings, a `"workspace/repo_slug"` shorthand, or a repository dict.
  `merge_pull_request` additionally accepts a PR dict directly
  (it pulls workspace, slug, and PR id from `destination.repository`).
- Destructive tools: none marked `destructive=True` on this surface;
  `merge_pull_request` and `decline_pull_request` are destructive in
  effect -- confirm with the user.

Example:

```python
prs = connector.list_pull_requests("acme/web", state="OPEN")
# {"pull_requests": [{"pr_ref": "pr_1", "pr_id": 42, "title": ..., ...}], "count": 10, "page": 1, "next": "..."}
connector.merge_pull_request(prs["pull_requests"][0])  # accepts the PR dict
```

## AzureDevOpsToolSet

Azure DevOps Services REST. Uses basic auth with an empty username and
your personal access token.

```python
from maivn_tools import AzureDevOpsToolSet

connector = AzureDevOpsToolSet(organization="acme", pat=secrets["ADO_PAT"])
```

Tools: `list_projects`, `get_project`, `list_repositories`,
`get_repository`, `list_pull_requests`, `create_pull_request`,
`complete_pull_request`, `list_branches`, `get_file`, `get_work_item`,
`wiql_query`, `create_work_item`, `update_work_item`,
`delete_work_item` (destructive), `list_pipelines`, `run_pipeline`,
`list_builds`.

### Agent-ready behavior

- `list_projects`, `list_repositories`, `list_pull_requests`,
  `list_branches`, `list_pipelines`, and `list_builds` return compact
  summaries with stable refs (`project_ref`, `repo_ref`, `pr_ref`,
  `branch_ref`, `pipeline_ref`, `build_ref`).
- User-facing identifiers always shown: project / repository `name`,
  `pull_request_id`, `work_item_id`, branch `name`, `pipeline_id`,
  `build_id`.
- Opaque ADO GUIDs (project `id`, repo `id`, full `url`) hidden by
  default; pass `include_ids=True` to opt in. Pass
  `include_metadata=False` for the raw `{"value": [...], "count": N}`
  envelope.
- Default `$top` is **10** for list tools that accept it.
- `(project, repository)` arguments on read and write tools accept
  strings (the name) or the project / repository dicts from list/get.
  `complete_pull_request` additionally accepts a PR dict directly -- it
  pulls project, repository, and `pullRequestId`, and derives
  `lastMergeSourceCommit.commitId` automatically.
- Destructive tools: `delete_work_item`. `complete_pull_request` is
  destructive in effect -- confirm before calling.

Example:

```python
prs = connector.list_pull_requests("MyProj", "myrepo", status="active")
# {"pull_requests": [{"pr_ref": "pr_1", "pull_request_id": 17, "title": ..., ...}], "count": 5}
connector.complete_pull_request(prs["pull_requests"][0])
```
