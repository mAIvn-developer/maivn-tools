# pyright: strict
from __future__ import annotations

from typing import cast

import pytest
from maivn._internal.api.agent import Agent
from maivn._internal.api.client import Client
from maivn._internal.utils.configuration import MaivnConfiguration, ServerConfiguration
from maivn._internal.utils.toolset import get_toolify_options, get_toolset_options

from maivn_tools.connectors.github import GitHubToolSet
from maivn_tools.testing import MockResponse, MockTransport, json_response


def _connector() -> tuple[GitHubToolSet, MockTransport]:
    transport = MockTransport()
    connector = GitHubToolSet(token="ghp_secret", transport=transport)
    return connector, transport


def _make_agent() -> Agent:
    config = MaivnConfiguration(
        server=ServerConfiguration(
            base_url="http://example.com",
            mock_base_url="http://example.com",
        )
    )
    client = Client.from_configuration(api_key="key", configuration=config)
    return Agent(name="t", client=client)


def test_github_list_tools_register_first_class_output_schemas() -> None:
    connector, _ = _connector()
    agent = _make_agent()
    tools = agent.add_toolset(connector)

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool suffix, expected array property key)
    expected: dict[str, str] = {
        "GITHUB_list_repositories": "repositories",
        "GITHUB_list_issues": "issues",
        "GITHUB_list_pull_requests": "pull_requests",
        "GITHUB_search_issues": "issues",
        "GITHUB_search_repositories": "repositories",
        "GITHUB_list_branches": "branches",
        "GITHUB_list_commits": "commits",
        "GITHUB_list_releases": "releases",
        "GITHUB_list_workflows": "workflows",
        "GITHUB_list_workflow_runs": "workflow_runs",
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f"{name} missing first-class output_schema"
        properties = cast("dict[str, object]", schema["properties"])
        array_prop = cast("dict[str, object]", properties[array_key])
        assert array_prop["type"] == "array", f"{name}.{array_key} should be an array"


def test_github_output_schemas_not_published_through_metadata() -> None:
    connector, _ = _connector()
    opts = get_toolify_options(connector.list_repositories)
    assert opts is not None
    assert "output_schema" not in opts.metadata


def test_github_connector_validates_inputs() -> None:
    with pytest.raises(ValueError):
        GitHubToolSet(token="")
    with pytest.raises(ValueError):
        GitHubToolSet(token="t", user_agent="")


def test_github_connector_is_a_toolset() -> None:
    opts = get_toolset_options(GitHubToolSet)
    assert opts is not None
    assert opts.prefix == "github"

    connector, _ = _connector()
    assert get_toolify_options(connector.get_authenticated_user) is not None
    assert get_toolify_options(connector.create_issue) is not None


def test_get_authenticated_user_attaches_bearer_and_headers() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"login": "octocat"}))
    user = connector.get_authenticated_user()
    assert user == {"login": "octocat"}
    request = transport.requests[0]
    assert request.headers["Authorization"] == "Bearer ghp_secret"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_list_repositories_returns_summary_by_default() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 999,
                    "node_id": "MDE=",
                    "name": "repo-1",
                    "full_name": "octocat/repo-1",
                    "owner": {"login": "octocat"},
                    "private": False,
                    "default_branch": "main",
                    "description": "demo",
                    "language": "Python",
                    "stargazers_count": 42,
                    "forks_count": 3,
                    "open_issues_count": 5,
                    "updated_at": "2026-01-02T00:00:00Z",
                    "html_url": "https://github.com/octocat/repo-1",
                }
            ]
        )
    )
    result = connector.list_repositories(type="owner", sort="full_name")
    assert isinstance(result, dict)
    assert result["count"] == 1
    repo = result["repositories"][0]
    assert repo["repo_ref"] == "repo_1"
    assert repo["full_name"] == "octocat/repo-1"
    assert repo["owner"] == "octocat"
    # IDs hidden by default
    assert "repo_id" not in repo
    assert "node_id" not in repo
    assert transport.requests[0].url.endswith("/user/repos")


def test_list_repositories_include_ids_exposes_provider_ids() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 999,
                    "node_id": "MDE=",
                    "name": "repo-1",
                    "full_name": "octocat/repo-1",
                    "owner": {"login": "octocat"},
                }
            ]
        )
    )
    result = connector.list_repositories(include_ids=True)
    assert isinstance(result, dict)
    assert result["repositories"][0]["repo_id"] == 999
    assert result["repositories"][0]["node_id"] == "MDE="


def test_list_repositories_raw_mode_returns_provider_payload() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"name": "repo-1"}]))
    raw = connector.list_repositories(include_metadata=False)
    assert raw == [{"name": "repo-1"}]


def test_get_repository_accepts_full_name_string() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"name": "repo-1"}))
    transport.enqueue(json_response({"name": "repo-1"}))
    transport.enqueue(json_response({"name": "repo-1"}))
    connector.get_repository(owner="octocat", repo="repo-1")
    connector.get_repository("octocat/repo-1")
    connector.get_repository({"full_name": "octocat/repo-1"})
    for request in transport.requests[:3]:
        assert request.url.endswith("/repos/octocat/repo-1")


def test_list_issues_returns_summary_with_ref_and_number() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 12345,
                    "node_id": "MDE=",
                    "number": 7,
                    "title": "Bug",
                    "state": "open",
                    "user": {"login": "alice"},
                    "labels": [{"name": "bug"}],
                    "assignees": [{"login": "bob"}],
                    "comments": 2,
                    "created_at": "2026-05-01T00:00:00Z",
                    "updated_at": "2026-05-02T00:00:00Z",
                    "html_url": "https://github.com/octocat/r/issues/7",
                }
            ]
        )
    )
    result = connector.list_issues(owner="octocat", repo="r", labels="bug")
    assert isinstance(result, dict)
    issue = result["issues"][0]
    assert issue["issue_ref"] == "issue_1"
    assert issue["issue_number"] == 7  # user-facing number is always included
    assert issue["title"] == "Bug"
    assert issue["author"] == "alice"
    assert issue["labels"] == ["bug"]
    assert issue["assignees"] == ["bob"]
    assert issue["is_pull_request"] is False
    # Raw IDs hidden
    assert "issue_id" not in issue
    assert "node_id" not in issue


def test_list_issues_include_ids_exposes_provider_id() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 12345,
                    "node_id": "MDE=",
                    "number": 7,
                    "title": "Bug",
                    "state": "open",
                }
            ]
        )
    )
    result = connector.list_issues(owner="o", repo="r", include_ids=True)
    assert isinstance(result, dict)
    assert result["issues"][0]["issue_id"] == 12345


def test_list_issues_raw_mode_skips_summarization() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"number": 1, "title": "x"}]))
    raw = connector.list_issues(owner="o", repo="r", include_metadata=False)
    assert raw == [{"number": 1, "title": "x"}]


def test_list_issues_only_sends_supplied_filters() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([]))
    connector.list_issues(owner="octocat", repo="r", labels="bug")
    request = transport.requests[0]
    assert request.params["labels"] == "bug"
    assert "assignee" not in request.params


def test_create_issue_serializes_optional_lists() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 7}))
    response = connector.create_issue(
        owner="octocat",
        repo="r",
        title="Bug",
        body="Repro",
        labels=["bug"],
        assignees=["octocat"],
    )
    assert response == {"number": 7}
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.json_body == {
        "title": "Bug",
        "body": "Repro",
        "labels": ["bug"],
        "assignees": ["octocat"],
    }


def test_create_issue_accepts_full_name() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 9}))
    connector.create_issue("octocat/r", title="t")
    assert transport.requests[0].url.endswith("/repos/octocat/r/issues")


def test_create_issue_validates_title() -> None:
    connector, _ = _connector()
    with pytest.raises(ValueError):
        connector.create_issue(owner="o", repo="r", title="")


def test_add_issue_comment_validates_body() -> None:
    connector, _ = _connector()
    with pytest.raises(ValueError):
        connector.add_issue_comment(owner="o", repo="r", issue_number=1, body="")


def test_add_issue_comment_posts_body() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"id": 99}))
    connector.add_issue_comment(owner="o", repo="r", issue_number=1, body="hi")
    request = transport.requests[0]
    assert request.url.endswith("/repos/o/r/issues/1/comments")
    assert request.json_body == {"body": "hi"}


def test_search_code_requires_query() -> None:
    connector, transport = _connector()
    with pytest.raises(ValueError):
        connector.search_code("")
    transport.enqueue(json_response({"items": []}))
    connector.search_code("repo:octocat/r needle")
    assert transport.requests[0].params["q"] == "repo:octocat/r needle"


def test_get_file_contents_passes_ref_when_supplied() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"name": "README.md"}))
    transport.enqueue(json_response({"name": "README.md"}))
    connector.get_file_contents(owner="o", repo="r", path="README.md", ref="main")
    connector.get_file_contents(owner="o", repo="r", path="README.md")
    assert transport.requests[0].params == {"ref": "main"}
    assert transport.requests[1].params == {}


def test_create_issue_failure_raises_provider_error() -> None:
    connector, transport = _connector()
    transport.enqueue(MockResponse(response=lambda _: json_response({}, status=422)))
    with pytest.raises(Exception) as exc:
        connector.create_issue(owner="o", repo="r", title="t")
    assert exc.value.__class__.__name__ == "ValidationError"


def test_github_search_endpoints_serialize_query() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"items": [], "total_count": 0}))
    transport.enqueue(json_response({"items": [], "total_count": 0}))
    transport.enqueue(json_response({"items": []}))
    connector.search_issues("type:pr author:me")
    connector.search_repositories("topic:python")
    connector.search_users("location:paris")
    assert transport.requests[0].url.endswith("/search/issues")
    assert transport.requests[0].params["q"] == "type:pr author:me"
    assert transport.requests[1].url.endswith("/search/repositories")
    assert transport.requests[2].url.endswith("/search/users")
    for method in (connector.search_issues, connector.search_repositories, connector.search_users):
        with pytest.raises(ValueError):
            method("")


def test_search_issues_returns_summary_envelope() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "total_count": 1,
                "incomplete_results": False,
                "items": [
                    {
                        "id": 1,
                        "number": 7,
                        "title": "Bug",
                        "state": "open",
                        "user": {"login": "alice"},
                    }
                ],
            }
        )
    )
    result = connector.search_issues("type:issue")
    assert result["total_count"] == 1
    assert result["incomplete_results"] is False
    assert result["issues"][0]["issue_ref"] == "issue_1"
    assert result["issues"][0]["issue_number"] == 7
    assert "issue_id" not in result["issues"][0]


def test_search_issues_raw_mode_returns_provider_envelope() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response({"items": [{"number": 1}], "total_count": 1, "incomplete_results": False})
    )
    raw = connector.search_issues("x", include_metadata=False)
    assert raw["items"] == [{"number": 1}]


def test_search_repositories_returns_summary_envelope() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "total_count": 1,
                "incomplete_results": False,
                "items": [
                    {
                        "id": 5,
                        "name": "x",
                        "full_name": "o/x",
                        "owner": {"login": "o"},
                    }
                ],
            }
        )
    )
    result = connector.search_repositories("topic:python")
    assert result["repositories"][0]["repo_ref"] == "repo_1"
    assert result["repositories"][0]["full_name"] == "o/x"
    assert "repo_id" not in result["repositories"][0]


def test_github_update_close_reopen_issue() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 1, "state": "closed"}))
    transport.enqueue(json_response({"number": 1, "state": "open"}))
    transport.enqueue(json_response({"number": 1, "title": "x"}))
    connector.close_issue(owner="o", repo="r", issue_number=1)
    connector.reopen_issue(owner="o", repo="r", issue_number=1)
    connector.update_issue(owner="o", repo="r", issue_number=1, patch={"title": "x"})
    assert transport.requests[0].json_body == {"state": "closed"}
    assert transport.requests[1].json_body == {"state": "open"}
    assert transport.requests[2].method == "PATCH"
    with pytest.raises(ValueError):
        connector.update_issue(owner="o", repo="r", issue_number=1, patch={})


def test_update_issue_accepts_issue_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 7, "state": "closed"}))
    issue = {"number": 7, "title": "x", "repository_url": "x"}
    issue_dict_with_full_name = {**issue, "full_name": "o/r"}
    connector.update_issue(issue_dict_with_full_name, {"state": "closed"})
    request = transport.requests[0]
    assert request.url.endswith("/repos/o/r/issues/7")
    assert request.json_body == {"state": "closed"}


def test_close_issue_accepts_issue_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 7, "state": "closed"}))
    issue = {"number": 7, "full_name": "o/r"}
    connector.close_issue(issue)
    assert transport.requests[0].url.endswith("/repos/o/r/issues/7")


def test_close_issue_accepts_full_name_and_number() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 7, "state": "closed"}))
    connector.close_issue("o/r", 7)
    assert transport.requests[0].url.endswith("/repos/o/r/issues/7")


def test_github_issue_labels_add_and_remove() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"name": "bug"}]))
    transport.enqueue(json_response({}))
    connector.add_issue_labels(owner="o", repo="r", issue_number=1, labels=["bug"])
    result = connector.remove_issue_label(owner="o", repo="r", issue_number=1, label="bug")
    assert transport.requests[0].json_body == {"labels": ["bug"]}
    assert transport.requests[1].method == "DELETE"
    assert result["removed"] == "bug"
    with pytest.raises(ValueError):
        connector.add_issue_labels(owner="o", repo="r", issue_number=1, labels=[])
    with pytest.raises(ValueError):
        connector.remove_issue_label(owner="o", repo="r", issue_number=1, label="")


def test_github_issue_comments_list_update_delete() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"id": 1}]))
    transport.enqueue(json_response({"id": 1, "body": "new"}))
    transport.enqueue(json_response({}))
    connector.list_issue_comments(owner="o", repo="r", issue_number=1)
    connector.update_issue_comment(owner="o", repo="r", comment_id=1, body="new")
    result = connector.delete_issue_comment(owner="o", repo="r", comment_id=1)
    assert transport.requests[1].method == "PATCH"
    assert transport.requests[2].method == "DELETE"
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.update_issue_comment(owner="o", repo="r", comment_id=1, body="")


def test_github_lock_unlock_issue() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.lock_issue(owner="o", repo="r", issue_number=1, lock_reason="spam")
    connector.unlock_issue(owner="o", repo="r", issue_number=1)
    assert transport.requests[0].url.endswith("/issues/1/lock")
    assert transport.requests[0].json_body == {"lock_reason": "spam"}
    assert transport.requests[1].method == "DELETE"
    with pytest.raises(ValueError):
        connector.lock_issue(owner="o", repo="r", issue_number=1, lock_reason="bogus")


def test_github_pull_request_create_update_merge() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"number": 7}))
    transport.enqueue(json_response({"number": 7, "title": "new"}))
    transport.enqueue(json_response({"merged": True}))
    connector.create_pull_request(
        owner="o", repo="r", title="t", head="feat", base="main", body="d"
    )
    connector.update_pull_request(owner="o", repo="r", pull_number=7, patch={"title": "new"})
    connector.merge_pull_request(owner="o", repo="r", pull_number=7, merge_method="squash")
    assert transport.requests[0].json_body["base"] == "main"
    assert transport.requests[0].json_body["draft"] is False
    assert transport.requests[1].method == "PATCH"
    assert transport.requests[2].method == "PUT"
    assert transport.requests[2].json_body["merge_method"] == "squash"
    with pytest.raises(ValueError):
        connector.create_pull_request(owner="o", repo="r", title="", head="x", base="y")
    with pytest.raises(ValueError):
        connector.update_pull_request(owner="o", repo="r", pull_number=1, patch={})
    with pytest.raises(ValueError):
        connector.merge_pull_request(owner="o", repo="r", pull_number=1, merge_method="bad")


def test_merge_pull_request_accepts_pr_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"merged": True}))
    pr = {"number": 99, "full_name": "o/r"}
    connector.merge_pull_request(pr, merge_method="squash")
    assert transport.requests[0].url.endswith("/repos/o/r/pulls/99/merge")
    assert transport.requests[0].json_body["merge_method"] == "squash"


def test_merge_pull_request_accepts_full_name_and_number() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"merged": True}))
    connector.merge_pull_request("o/r", 42)
    assert transport.requests[0].url.endswith("/repos/o/r/pulls/42/merge")


def test_list_pull_requests_returns_summary() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 999,
                    "node_id": "x",
                    "number": 12,
                    "title": "PR title",
                    "state": "open",
                    "draft": False,
                    "user": {"login": "alice"},
                    "head": {"ref": "feature"},
                    "base": {"ref": "main"},
                    "merged": False,
                    "html_url": "https://github.com/o/r/pull/12",
                }
            ]
        )
    )
    result = connector.list_pull_requests(owner="o", repo="r")
    assert isinstance(result, dict)
    pr = result["pull_requests"][0]
    assert pr["pr_ref"] == "pr_1"
    assert pr["pr_number"] == 12
    assert pr["head"] == "feature"
    assert pr["base"] == "main"
    assert "pr_id" not in pr


def test_list_pull_requests_include_ids() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"id": 999, "number": 1, "title": "t", "state": "open"}]))
    result = connector.list_pull_requests(owner="o", repo="r", include_ids=True)
    assert isinstance(result, dict)
    assert result["pull_requests"][0]["pr_id"] == 999


def test_github_pull_request_files_commits_reviews() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"filename": "x"}]))
    transport.enqueue(json_response([{"sha": "abc"}]))
    transport.enqueue(json_response([{"id": 1}]))
    transport.enqueue(json_response({"id": 1, "state": "APPROVED"}))
    transport.enqueue(json_response({}))
    connector.list_pull_request_files(owner="o", repo="r", pull_number=7)
    connector.list_pull_request_commits(owner="o", repo="r", pull_number=7)
    connector.list_pull_request_reviews(owner="o", repo="r", pull_number=7)
    connector.create_pull_request_review(
        owner="o", repo="r", pull_number=7, body="LGTM", event="APPROVE"
    )
    connector.request_pull_request_reviewers(
        owner="o", repo="r", pull_number=7, reviewers=["alice"]
    )
    assert transport.requests[0].url.endswith("/pulls/7/files")
    assert transport.requests[1].url.endswith("/pulls/7/commits")
    assert transport.requests[2].url.endswith("/pulls/7/reviews")
    assert transport.requests[3].json_body["event"] == "APPROVE"
    assert transport.requests[4].json_body["reviewers"] == ["alice"]
    with pytest.raises(ValueError):
        connector.create_pull_request_review(owner="o", repo="r", pull_number=7, event="BAD")
    with pytest.raises(ValueError):
        connector.request_pull_request_reviewers(owner="o", repo="r", pull_number=7)


def test_github_branches_crud_and_commits() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response([{"name": "main", "commit": {"sha": "abc123def456"}, "protected": True}])
    )
    transport.enqueue(json_response({"name": "main"}))
    transport.enqueue(json_response({"ref": "refs/heads/feat"}))
    transport.enqueue(json_response({}))
    transport.enqueue(
        json_response(
            [
                {
                    "sha": "abc123def456",
                    "commit": {
                        "message": "first line\nsecond line",
                        "author": {"name": "alice", "date": "2026-01-01T00:00:00Z"},
                    },
                }
            ]
        )
    )
    transport.enqueue(json_response({"sha": "abc"}))
    transport.enqueue(json_response({"files": []}))
    branches_result = connector.list_branches(owner="o", repo="r", protected=True)
    connector.get_branch(owner="o", repo="r", branch="main")
    connector.create_branch(owner="o", repo="r", branch="feat", sha="abc")
    result = connector.delete_branch(owner="o", repo="r", branch="feat")
    commits_result = connector.list_commits(owner="o", repo="r", author="alice", since="2026-01-01")
    connector.get_commit(owner="o", repo="r", ref="abc")
    connector.compare_commits(owner="o", repo="r", base="main", head="feat")
    assert isinstance(branches_result, dict)
    assert branches_result["branches"][0]["branch_ref"] == "branch_1"
    assert branches_result["branches"][0]["short_sha"] == "abc123d"
    assert transport.requests[0].params["protected"] == "true"
    assert transport.requests[2].json_body["ref"] == "refs/heads/feat"
    assert transport.requests[3].method == "DELETE"
    assert result["deleted"] is True
    assert isinstance(commits_result, dict)
    assert commits_result["commits"][0]["commit_ref"] == "commit_1"
    assert commits_result["commits"][0]["short_sha"] == "abc123d"
    assert commits_result["commits"][0]["message"] == "first line"
    assert transport.requests[4].params["author"] == "alice"
    with pytest.raises(ValueError):
        connector.get_branch(owner="o", repo="r", branch="")
    with pytest.raises(ValueError):
        connector.create_branch(owner="o", repo="r", branch="x", sha="")
    with pytest.raises(ValueError):
        connector.delete_branch(owner="o", repo="r", branch="")
    with pytest.raises(ValueError):
        connector.get_commit(owner="o", repo="r", ref="")
    with pytest.raises(ValueError):
        connector.compare_commits(owner="o", repo="r", base="", head="x")


def test_delete_branch_accepts_full_name_and_dict() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.delete_branch("o/r", "feat")
    connector.delete_branch({"full_name": "o/r"}, "feat")
    connector.delete_branch({"full_name": "o/r"}, {"name": "feat"})
    for request in transport.requests:
        assert request.method == "DELETE"
        assert request.url.endswith("/repos/o/r/git/refs/heads/feat")


def test_github_create_update_delete_file_and_readme() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"content": {"sha": "new"}}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"name": "README.md"}))
    transport.enqueue(json_response([{"name": "v1"}]))
    connector.create_or_update_file(
        owner="o",
        repo="r",
        path="docs/x.md",
        message="add",
        content_base64="aGVsbG8=",
        branch="main",
    )
    result = connector.delete_repo_file(
        owner="o",
        repo="r",
        path="docs/x.md",
        message="rm",
        sha="abc",
    )
    connector.get_readme(owner="o", repo="r", ref="main")
    connector.list_tags(owner="o", repo="r")
    assert transport.requests[0].method == "PUT"
    assert transport.requests[0].json_body["branch"] == "main"
    assert transport.requests[1].method == "DELETE"
    assert transport.requests[1].json_body["sha"] == "abc"
    assert result == {}
    with pytest.raises(ValueError):
        connector.create_or_update_file(
            owner="o", repo="r", path="", message="m", content_base64="x"
        )
    with pytest.raises(ValueError):
        connector.delete_repo_file(owner="o", repo="r", path="p", message="m", sha="")


def test_github_releases_crud() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 1,
                    "tag_name": "v1",
                    "name": "v1",
                    "draft": False,
                    "prerelease": False,
                    "author": {"login": "rel-bot"},
                    "html_url": "https://github.com/o/r/releases/tag/v1",
                }
            ]
        )
    )
    transport.enqueue(json_response({"id": 1}))
    transport.enqueue(json_response({"id": 1}))
    transport.enqueue(json_response({"id": 2}))
    transport.enqueue(json_response({"id": 2, "name": "new"}))
    transport.enqueue(json_response({}))
    releases_result = connector.list_releases(owner="o", repo="r")
    connector.get_release(owner="o", repo="r", release_id=1)
    connector.get_latest_release(owner="o", repo="r")
    connector.create_release(owner="o", repo="r", tag_name="v1", name="v1", body="notes")
    connector.update_release(owner="o", repo="r", release_id=2, patch={"name": "new"})
    result = connector.delete_release(owner="o", repo="r", release_id=2)
    assert isinstance(releases_result, dict)
    assert releases_result["releases"][0]["release_ref"] == "release_1"
    assert releases_result["releases"][0]["tag_name"] == "v1"
    assert "release_id" not in releases_result["releases"][0]
    assert transport.requests[2].url.endswith("/releases/latest")
    assert transport.requests[3].json_body["tag_name"] == "v1"
    assert transport.requests[4].method == "PATCH"
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.create_release(owner="o", repo="r", tag_name="")
    with pytest.raises(ValueError):
        connector.update_release(owner="o", repo="r", release_id=1, patch={})


def test_list_releases_include_ids_exposes_release_id() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"id": 99, "tag_name": "v9"}]))
    result = connector.list_releases(owner="o", repo="r", include_ids=True)
    assert isinstance(result, dict)
    assert result["releases"][0]["release_id"] == 99


def test_github_workflows_and_check_runs() -> None:
    connector, transport = _connector()
    transport.enqueue(
        json_response(
            {
                "total_count": 1,
                "workflows": [
                    {
                        "id": 42,
                        "name": "ci",
                        "state": "active",
                        "path": ".github/workflows/ci.yml",
                    }
                ],
            }
        )
    )
    transport.enqueue(
        json_response(
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 99,
                        "name": "ci",
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                        "head_branch": "main",
                        "head_sha": "abcdef1234",
                        "run_number": 5,
                    }
                ],
            }
        )
    )
    transport.enqueue(json_response({"id": 99}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"check_runs": []}))
    workflows = connector.list_workflows(owner="o", repo="r")
    runs = connector.list_workflow_runs(owner="o", repo="r", workflow_id=42, status="success")
    connector.get_workflow_run(owner="o", repo="r", run_id=99)
    connector.cancel_workflow_run(owner="o", repo="r", run_id=99)
    connector.rerun_workflow(owner="o", repo="r", run_id=99)
    connector.dispatch_workflow(owner="o", repo="r", workflow_id=42, ref="main", inputs={"a": 1})
    connector.list_check_runs(owner="o", repo="r", ref="abc")
    assert isinstance(workflows, dict)
    assert workflows["workflows"][0]["workflow_ref"] == "workflow_1"
    assert workflows["workflows"][0]["workflow_id"] == 42
    assert isinstance(runs, dict)
    assert runs["workflow_runs"][0]["run_ref"] == "run_1"
    assert runs["workflow_runs"][0]["run_id"] == 99
    assert runs["workflow_runs"][0]["short_sha"] == "abcdef1"
    assert transport.requests[0].url.endswith("/actions/workflows")
    assert "/actions/workflows/42/runs" in transport.requests[1].url
    assert transport.requests[1].params["status"] == "success"
    assert transport.requests[2].url.endswith("/actions/runs/99")
    assert transport.requests[3].url.endswith("/actions/runs/99/cancel")
    assert transport.requests[4].url.endswith("/actions/runs/99/rerun")
    assert transport.requests[5].json_body == {"ref": "main", "inputs": {"a": 1}}
    assert transport.requests[6].url.endswith("/commits/abc/check-runs")
    with pytest.raises(ValueError):
        connector.dispatch_workflow(owner="o", repo="r", workflow_id=1, ref="")
    with pytest.raises(ValueError):
        connector.list_check_runs(owner="o", repo="r", ref="")


def test_list_workflows_raw_mode_returns_envelope() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({"total_count": 0, "workflows": []}))
    raw = connector.list_workflows(owner="o", repo="r", include_metadata=False)
    assert raw == {"total_count": 0, "workflows": []}


def test_github_collaborators_orgs_teams_forks() -> None:
    connector, transport = _connector()
    transport.enqueue(json_response([{"login": "a"}]))
    transport.enqueue(json_response({"permission": "push"}))
    transport.enqueue(json_response({}))
    transport.enqueue(
        json_response([{"name": "r", "full_name": "acme/r", "owner": {"login": "acme"}}])
    )
    transport.enqueue(json_response([{"login": "u"}]))
    transport.enqueue(json_response([{"slug": "t"}]))
    transport.enqueue(json_response([{"name": "fork"}]))
    transport.enqueue(json_response({"name": "fork"}))
    transport.enqueue(json_response([{"login": "star"}]))
    transport.enqueue(json_response({"resources": {}}))
    transport.enqueue(json_response({"login": "octocat"}))
    connector.list_collaborators(owner="o", repo="r")
    connector.add_collaborator(owner="o", repo="r", username="alice", permission="maintain")
    result = connector.remove_collaborator(owner="o", repo="r", username="alice")
    org_repos = connector.list_organization_repos(org="acme")
    connector.list_organization_members(org="acme")
    connector.list_teams(org="acme")
    connector.list_forks(owner="o", repo="r")
    connector.fork_repository(owner="o", repo="r", organization="acme")
    connector.list_stargazers(owner="o", repo="r")
    connector.get_rate_limit()
    connector.get_user("octocat")
    assert transport.requests[1].json_body == {"permission": "maintain"}
    assert result["removed"] is True
    assert transport.requests[3].url.endswith("/orgs/acme/repos")
    assert isinstance(org_repos, dict)
    assert org_repos["repositories"][0]["repo_ref"] == "repo_1"
    assert transport.requests[7].json_body == {"organization": "acme"}
    assert transport.requests[9].url.endswith("/rate_limit")
    with pytest.raises(ValueError):
        connector.add_collaborator(owner="o", repo="r", username="", permission="push")
    with pytest.raises(ValueError):
        connector.add_collaborator(owner="o", repo="r", username="u", permission="bad")
    with pytest.raises(ValueError):
        connector.remove_collaborator(owner="o", repo="r", username="")
    with pytest.raises(ValueError):
        connector.list_organization_repos(org="")
    with pytest.raises(ValueError):
        connector.list_organization_members(org="")
    with pytest.raises(ValueError):
        connector.list_teams(org="")
    with pytest.raises(ValueError):
        connector.get_user("")


def test_destructive_tools_are_tagged_destructive() -> None:
    """destructive=True propagates to the toolify tags so hosts can filter."""
    connector, _ = _connector()
    destructive_methods = [
        connector.delete_branch,
        connector.delete_issue_comment,
        connector.delete_repo_file,
        connector.delete_release,
        connector.remove_collaborator,
    ]
    for method in destructive_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is True, f"{method.__name__} should be destructive"

    # And the read-only tools should not be destructive.
    read_methods = [
        connector.get_authenticated_user,
        connector.list_issues,
        connector.list_pull_requests,
        connector.search_code,
    ]
    for method in read_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False, f"{method.__name__} must not be destructive"
