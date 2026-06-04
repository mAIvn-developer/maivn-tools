# pyright: strict
from __future__ import annotations

from typing import Any

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.azure_devops import AzureDevOpsToolSet
from maivn_tools.connectors.bitbucket import BitbucketToolSet
from maivn_tools.connectors.gitlab import GitLabToolSet
from maivn_tools.connectors.linear import LinearToolSet
from maivn_tools.connectors.servicenow import ServiceNowToolSet
from maivn_tools.testing import MockResponse, MockTransport, json_response, text_response

# MARK: - Linear


def _linear() -> tuple[LinearToolSet, MockTransport]:
    transport = MockTransport()
    return LinearToolSet(api_key="lin_api_xxx", transport=transport), transport


def test_linear_requires_api_key() -> None:
    with pytest.raises(ValueError):
        LinearToolSet(api_key="")


def test_linear_sends_api_key_header() -> None:
    connector, transport = _linear()
    transport.enqueue(json_response({"data": {"viewer": {"id": "u1"}}}))
    connector.viewer()
    assert transport.requests[0].headers["Authorization"] == "lin_api_xxx"


def test_linear_bearer_mode() -> None:
    transport = MockTransport()
    connector = LinearToolSet(api_key="bearer-tok", use_bearer=True, transport=transport)
    transport.enqueue(json_response({"data": {"viewer": {"id": "u1"}}}))
    connector.viewer()
    assert transport.requests[0].headers["Authorization"] == "Bearer bearer-tok"


def test_linear_lists_and_filters() -> None:
    connector, transport = _linear()
    for _ in range(6):
        transport.enqueue(json_response({"data": {"issues": {"nodes": []}}}))
    connector.list_teams()
    connector.list_users(first=10)
    connector.list_projects()
    connector.list_cycles()
    connector.list_issues(filter={"team": {"key": {"eq": "ENG"}}}, order_by="updatedAt")
    connector.get_issue("ENG-1")
    body = transport.requests[4].json_body
    assert body["variables"]["filter"] == {"team": {"key": {"eq": "ENG"}}}
    assert body["variables"]["orderBy"] == "updatedAt"
    with pytest.raises(ValueError):
        connector.list_teams(first=0)
    with pytest.raises(ValueError):
        connector.list_issues(order_by="bogus")
    with pytest.raises(ValueError):
        connector.get_issue("")


def test_linear_mutations() -> None:
    connector, transport = _linear()
    for _ in range(4):
        transport.enqueue(json_response({"data": {"issueCreate": {"success": True}}}))
    connector.create_issue(team_id="t1", title="Bug", description="d", priority=2)
    connector.update_issue("ENG-1", {"title": "x"})
    connector.archive_issue("ENG-1")
    connector.create_comment(issue_id="ENG-1", body="thanks")
    assert transport.requests[0].json_body["variables"]["input"]["teamId"] == "t1"
    assert transport.requests[2].json_body["variables"]["id"] == "ENG-1"
    with pytest.raises(ValueError):
        connector.create_issue(team_id="", title="x")
    with pytest.raises(ValueError):
        connector.create_issue(team_id="t", title="")
    with pytest.raises(ValueError):
        connector.update_issue("", {"x": 1})
    with pytest.raises(ValueError):
        connector.update_issue("ENG-1", {})
    with pytest.raises(ValueError):
        connector.archive_issue("")
    with pytest.raises(ValueError):
        connector.create_comment(issue_id="", body="x")


def test_linear_comments_listing_and_graphql_passthrough() -> None:
    connector, transport = _linear()
    transport.enqueue(json_response({"data": {"comments": {"nodes": []}}}))
    transport.enqueue(json_response({"data": {"x": 1}}))
    connector.list_comments("ENG-1")
    connector.graphql("query { x }", variables={"a": 1})
    assert transport.requests[1].json_body["variables"] == {"a": 1}
    with pytest.raises(ValueError):
        connector.list_comments("")
    with pytest.raises(ValueError):
        connector.graphql("")


def test_linear_propagates_graphql_errors() -> None:
    connector, transport = _linear()
    transport.enqueue(json_response({"errors": [{"message": "bad"}]}))
    with pytest.raises(ValueError):
        connector.viewer()


# MARK: - ServiceNow


def _snow() -> tuple[ServiceNowToolSet, MockTransport]:
    transport = MockTransport()
    return (
        ServiceNowToolSet(
            instance_url="https://acme.service-now.com",
            username="ops",
            password="p",
            transport=transport,
        ),
        transport,
    )


def test_snow_validates_inputs() -> None:
    with pytest.raises(ValueError):
        ServiceNowToolSet(instance_url="", username="u", password="p")
    with pytest.raises(ValueError):
        ServiceNowToolSet(instance_url="x", username="", password="p")
    with pytest.raises(ValueError):
        ServiceNowToolSet(instance_url="x", username="u", password="")


def test_snow_table_validation() -> None:
    connector, _ = _snow()
    with pytest.raises(ValueError):
        connector.list_records("../etc")
    with pytest.raises(ValueError):
        connector.list_records("")


def test_snow_list_and_get() -> None:
    connector, transport = _snow()
    transport.enqueue(json_response({"result": []}))
    transport.enqueue(json_response({"result": {}}))
    connector.list_records(
        "incident",
        query="active=true",
        fields=["sys_id", "number"],
        limit=10,
        order_by="number",
        display_value="true",
    )
    connector.get_record(
        "incident",
        "abc",
        fields=["sys_id"],
        display_value="all",
    )
    assert "ORDERBYnumber" in transport.requests[0].params["sysparm_query"]
    assert transport.requests[0].params["sysparm_display_value"] == "true"
    with pytest.raises(ValueError):
        connector.list_records("incident", limit=0)
    with pytest.raises(ValueError):
        connector.list_records("incident", display_value="bogus")
    with pytest.raises(ValueError):
        connector.get_record("incident", "")


def test_snow_crud() -> None:
    connector, transport = _snow()
    for _ in range(3):
        transport.enqueue(json_response({"result": {"sys_id": "abc"}}))
    connector.create_record("incident", {"short_description": "x"})
    connector.update_record("incident", "abc", {"state": "2"})
    connector.delete_record("incident", "abc")
    assert transport.requests[1].method == "PATCH"
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.create_record("incident", {})
    with pytest.raises(ValueError):
        connector.update_record("incident", "", {"x": 1})
    with pytest.raises(ValueError):
        connector.update_record("incident", "abc", {})
    with pytest.raises(ValueError):
        connector.delete_record("incident", "")


def test_snow_incident_and_change_helpers() -> None:
    connector, transport = _snow()
    transport.enqueue(json_response({"result": []}))
    transport.enqueue(json_response({"result": {"sys_id": "abc"}}))
    transport.enqueue(json_response({"result": {"sys_id": "chg"}}))
    connector.list_incidents(query="active=true")
    connector.create_incident(short_description="Bug", description="d", urgency="2")
    connector.create_change_request(short_description="rollout", type="normal")
    body = transport.requests[1].json_body
    assert body["short_description"] == "Bug"
    with pytest.raises(ValueError):
        connector.create_incident(short_description="")
    with pytest.raises(ValueError):
        connector.create_change_request(short_description="")


def test_snow_aggregate_and_attachments() -> None:
    connector, transport = _snow()
    transport.enqueue(json_response({"result": {}}))
    transport.enqueue(json_response({"result": []}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"result": []}))
    connector.aggregate(
        "incident",
        group_by=["priority"],
        sum_fields=["business_duration"],
        max_fields=["sys_updated_on"],
    )
    connector.list_attachments(table="incident", sys_id="abc")
    connector.delete_attachment("att1")
    connector.find_user(email="x@y", user_name="x")
    assert "table_name=incident" in transport.requests[1].params["sysparm_query"]
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.aggregate("../")
    with pytest.raises(ValueError):
        connector.delete_attachment("")
    with pytest.raises(ValueError):
        connector.find_user()


# MARK: - GitLab


def _gitlab() -> tuple[GitLabToolSet, MockTransport]:
    transport = MockTransport()
    return GitLabToolSet(token="gtok", transport=transport), transport


def test_gitlab_user_lookup() -> None:
    connector, transport = _gitlab()
    transport.enqueue(json_response({"id": 1}))
    transport.enqueue(json_response([]))
    connector.get_current_user()
    connector.list_users(search="alice", active=True)
    assert transport.requests[0].headers["Authorization"] == "Bearer gtok"
    assert transport.requests[1].params["active"] == "true"


def test_gitlab_projects_and_issues() -> None:
    connector, transport = _gitlab()
    for _ in range(6):
        transport.enqueue(json_response({}))
    connector.list_projects(search="x", membership=True, owned=False, archived=False)
    connector.get_project("group/repo")
    connector.list_issues("group/repo", state="opened", labels=["bug", "p1"])
    connector.get_issue("group/repo", 42)
    connector.create_issue(
        "group/repo",
        title="Issue",
        description="d",
        labels=["bug"],
        assignee_ids=[1],
    )
    connector.update_issue("group/repo", 42, {"state_event": "close"})
    assert "%2F" in transport.requests[1].url
    assert transport.requests[2].params["labels"] == "bug,p1"
    assert transport.requests[4].json_body["labels"] == "bug"
    with pytest.raises(ValueError):
        connector.list_issues("group/repo", state="bogus")
    with pytest.raises(ValueError):
        connector.create_issue("group/repo", title="")
    with pytest.raises(ValueError):
        connector.update_issue("group/repo", 42, {})


def test_gitlab_merge_requests() -> None:
    connector, transport = _gitlab()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.list_merge_requests("group/repo", state="opened")
    connector.create_merge_request(
        "group/repo",
        source_branch="feat/x",
        target_branch="main",
        title="MR",
        description="d",
        assignee_ids=[1],
        reviewer_ids=[2],
        remove_source_branch=True,
    )
    connector.merge_merge_request("group/repo", 99, squash=True, should_remove_source_branch=True)
    connector.get_merge_request("group/repo", 99)
    body = transport.requests[1].json_body
    assert body["source_branch"] == "feat/x"
    assert transport.requests[2].method == "PUT"
    with pytest.raises(ValueError):
        connector.list_merge_requests("group/repo", state="bogus")
    with pytest.raises(ValueError):
        connector.create_merge_request("group/repo", source_branch="", target_branch="m", title="t")


def test_gitlab_pipelines_and_files() -> None:
    connector, transport = _gitlab()
    for _ in range(6):
        transport.enqueue(json_response({}))
    connector.list_pipelines("group/repo", status="success", ref="main")
    connector.trigger_pipeline("group/repo", ref="main", variables={"K": "v"})
    connector.get_pipeline("group/repo", 1)
    connector.get_file("group/repo", file_path="app.py", ref="main")
    connector.list_branches("group/repo", search="release")
    connector.list_commits("group/repo", ref_name="main", since="2026-01-01")
    assert transport.requests[1].json_body["variables"] == [{"key": "K", "value": "v"}]
    with pytest.raises(ValueError):
        connector.trigger_pipeline("group/repo", ref="")
    with pytest.raises(ValueError):
        connector.get_file("group/repo", file_path="", ref="main")


def test_gitlab_delete_and_search_blobs() -> None:
    connector, transport = _gitlab()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response([]))
    connector.delete_issue("group/repo", 1)
    connector.search_blobs("group/repo", search="def main")
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[1].params["scope"] == "blobs"
    with pytest.raises(ValueError):
        connector.search_blobs("group/repo", search="")


# MARK: - Bitbucket


def _bb() -> tuple[BitbucketToolSet, MockTransport]:
    transport = MockTransport()
    return (
        BitbucketToolSet(
            email="u",
            api_token="p",
            transport=transport,
        ),
        transport,
    )


def test_bb_requires_auth() -> None:
    with pytest.raises(ValueError):
        BitbucketToolSet()


def test_bb_with_token() -> None:
    transport = MockTransport()
    connector = BitbucketToolSet(token="t", transport=transport)
    transport.enqueue(json_response({"username": "x"}))
    connector.get_current_user()
    assert transport.requests[0].headers["Authorization"] == "Bearer t"


def test_bb_workspaces_and_repos() -> None:
    connector, transport = _bb()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.get_current_user()
    connector.list_workspaces()
    connector.list_repositories(
        "acme",
        role="member",
        q="updated_on>2026-01-01",
        sort="-updated_on",
    )
    connector.get_repository("acme", "myrepo")
    assert transport.requests[2].params["role"] == "member"
    with pytest.raises(ValueError):
        connector.list_repositories("")
    with pytest.raises(ValueError):
        connector.get_repository("", "x")


def test_bb_pull_requests() -> None:
    connector, transport = _bb()
    for _ in range(5):
        transport.enqueue(json_response({}))
    connector.list_pull_requests("acme", "myrepo", state="OPEN")
    connector.get_pull_request("acme", "myrepo", 1)
    connector.create_pull_request(
        "acme",
        "myrepo",
        title="PR",
        source_branch="feat",
        destination_branch="main",
        description="d",
        close_source_branch=True,
        reviewers=["abc"],
    )
    connector.merge_pull_request("acme", "myrepo", 1, merge_strategy="squash", message="m")
    connector.decline_pull_request("acme", "myrepo", 1)
    body = transport.requests[2].json_body
    assert body["source"]["branch"]["name"] == "feat"
    assert body["reviewers"] == [{"uuid": "abc"}]
    with pytest.raises(ValueError):
        connector.list_pull_requests("acme", "myrepo", state="bogus")
    with pytest.raises(ValueError):
        connector.create_pull_request("", "r", title="t", source_branch="s", destination_branch="d")
    with pytest.raises(ValueError):
        connector.merge_pull_request("acme", "myrepo", 1, merge_strategy="bogus")


def test_bb_issues_pipelines_and_files() -> None:
    connector, transport = _bb()
    for _ in range(6):
        transport.enqueue(json_response({}))
    transport.enqueue(text_response("file body"))
    connector.list_issues("acme", "myrepo", q='state="new"')
    connector.create_issue("acme", "myrepo", title="bug", content="repro", kind="bug")
    connector.list_pipelines("acme", "myrepo")
    connector.run_pipeline("acme", "myrepo", branch="main")
    connector.run_pipeline("acme", "myrepo", commit="abc")
    connector.list_branches("acme", "myrepo", q='name="main"')
    result = connector.get_file_contents("acme", "myrepo", commit_or_branch="main", path="app.py")
    assert result["body"] == "file body"
    with pytest.raises(ValueError):
        connector.create_issue("acme", "myrepo", title="")
    with pytest.raises(ValueError):
        connector.create_issue("acme", "myrepo", title="x", kind="bogus")
    with pytest.raises(ValueError):
        connector.run_pipeline("acme", "myrepo")
    with pytest.raises(ValueError):
        connector.get_file_contents("acme", "myrepo", commit_or_branch="", path="x")


# MARK: - Azure DevOps


def _ado() -> tuple[AzureDevOpsToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AzureDevOpsToolSet(organization="acme", pat="pat", transport=transport),
        transport,
    )


def test_ado_requires_inputs() -> None:
    with pytest.raises(ValueError):
        AzureDevOpsToolSet(organization="", pat="x")
    with pytest.raises(ValueError):
        AzureDevOpsToolSet(organization="x", pat="")


def test_ado_projects_and_repos() -> None:
    connector, transport = _ado()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.list_projects(state="all", top=10)
    connector.get_project("MyProj")
    connector.list_repositories("MyProj")
    connector.get_repository("MyProj", "myrepo")
    assert transport.requests[0].params["api-version"] == "7.1"
    assert transport.requests[0].params["stateFilter"] == "all"
    with pytest.raises(ValueError):
        connector.get_project("")
    with pytest.raises(ValueError):
        connector.list_repositories("")
    with pytest.raises(ValueError):
        connector.get_repository("", "x")


def test_ado_pull_requests() -> None:
    connector, transport = _ado()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.list_pull_requests("MyProj", "myrepo", status="active")
    connector.create_pull_request(
        "MyProj",
        "myrepo",
        source_ref="refs/heads/feat",
        target_ref="refs/heads/main",
        title="PR",
        description="d",
        reviewers=["abc"],
    )
    connector.complete_pull_request(
        "MyProj",
        "myrepo",
        1,
        last_merge_source_commit="abcd",
        squash_merge=True,
    )
    connector.list_branches("MyProj", "myrepo")
    body = transport.requests[1].json_body
    assert body["sourceRefName"] == "refs/heads/feat"
    assert transport.requests[2].method == "PATCH"
    with pytest.raises(ValueError):
        connector.list_pull_requests("MyProj", "myrepo", status="bogus")
    with pytest.raises(ValueError):
        connector.create_pull_request("", "r", source_ref="s", target_ref="t", title="x")


def test_ado_work_items() -> None:
    connector, transport = _ado()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.get_work_item(1, expand="all")
    connector.wiql_query("MyProj", query="SELECT [System.Id] FROM workitems")
    connector.create_work_item(
        "MyProj",
        type="Bug",
        title="t",
        description="d",
        extra_fields={"System.Tags": "x"},
    )
    connector.update_work_item(1, {"System.Title": "new"})
    create_req = transport.requests[2]
    assert b"System.Title" in (create_req.data or b"")
    assert create_req.headers["Content-Type"] == "application/json-patch+json"
    with pytest.raises(ValueError):
        connector.wiql_query("", query="x")
    with pytest.raises(ValueError):
        connector.create_work_item("MyProj", type="", title="t")
    with pytest.raises(ValueError):
        connector.update_work_item(1, {})


def test_ado_delete_work_item_and_pipelines() -> None:
    connector, transport = _ado()
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.delete_work_item(1, destroy=True)
    connector.list_pipelines("MyProj")
    connector.run_pipeline("MyProj", 1, branch="main", variables={"k": "v"})
    connector.list_builds("MyProj", definitions=[1, 2], top=10)
    assert transport.requests[0].params["destroy"] == "true"
    assert transport.requests[2].json_body["resources"]["repositories"]["self"]["refName"] == "main"
    assert transport.requests[3].params["definitions"] == "1,2"
    with pytest.raises(ValueError):
        connector.list_pipelines("")
    with pytest.raises(ValueError):
        connector.run_pipeline("", 1)


def test_ado_file_lookup() -> None:
    connector, transport = _ado()
    transport.enqueue(json_response({}))
    connector.get_file("MyProj", "myrepo", path="app.py", version="main")
    assert transport.requests[0].params["path"] == "app.py"
    assert transport.requests[0].params["versionDescriptor.version"] == "main"
    with pytest.raises(ValueError):
        connector.get_file("MyProj", "myrepo", path="", version="main")


# Ensure the MockResponse import is used so static analyzers do not warn.
_ = MockResponse


# MARK: - Agent-ready behavior: GitLab


def test_gitlab_list_projects_returns_summary_by_default() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 99,
                    "name": "repo",
                    "path_with_namespace": "group/repo",
                    "namespace": {"full_path": "group"},
                    "visibility": "private",
                    "default_branch": "main",
                    "description": "demo",
                    "star_count": 3,
                    "web_url": "https://gitlab.com/group/repo",
                }
            ]
        )
    )
    result = connector.list_projects(search="demo")
    assert isinstance(result, dict)
    project = result["projects"][0]
    assert project["project_ref"] == "project_1"
    assert project["path_with_namespace"] == "group/repo"
    assert project["visibility"] == "private"
    # Opaque numeric ID hidden by default
    assert "project_id" not in project


def test_gitlab_list_projects_include_ids() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 99,
                    "name": "repo",
                    "path_with_namespace": "group/repo",
                }
            ]
        )
    )
    result = connector.list_projects(include_ids=True)
    assert isinstance(result, dict)
    assert result["projects"][0]["project_id"] == 99


def test_gitlab_list_projects_raw_mode() -> None:
    connector, transport = _gitlab()
    transport.enqueue(json_response([{"name": "repo"}]))
    raw = connector.list_projects(include_metadata=False)
    assert raw == [{"name": "repo"}]


def test_gitlab_list_issues_returns_summary_with_iid() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 1234,
                    "iid": 7,
                    "project_id": 99,
                    "title": "Bug",
                    "state": "opened",
                    "author": {"username": "alice"},
                    "assignees": [{"username": "bob"}],
                    "labels": ["bug"],
                }
            ]
        )
    )
    result = connector.list_issues("group/repo", state="opened")
    assert isinstance(result, dict)
    issue = result["issues"][0]
    assert issue["issue_ref"] == "issue_1"
    assert issue["iid"] == 7  # user-facing number always shown
    assert issue["author"] == "alice"
    assert issue["assignees"] == ["bob"]
    assert "issue_id" not in issue
    assert "project_id" not in issue


def test_gitlab_list_issues_include_ids() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response([{"id": 1234, "iid": 7, "project_id": 99, "title": "Bug", "state": "opened"}])
    )
    result = connector.list_issues("group/repo", include_ids=True)
    assert isinstance(result, dict)
    assert result["issues"][0]["issue_id"] == 1234
    assert result["issues"][0]["project_id"] == 99


def test_gitlab_update_issue_accepts_issue_dict() -> None:
    connector, transport = _gitlab()
    transport.enqueue(json_response({"iid": 7, "state": "closed"}))
    issue = {"iid": 7, "project_id": 99}
    connector.update_issue(issue, {"state_event": "close"})
    request = transport.requests[0]
    assert "/projects/99/issues/7" in request.url
    assert request.json_body == {"state_event": "close"}


def test_gitlab_list_merge_requests_summary() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 1234,
                    "iid": 99,
                    "project_id": 5,
                    "title": "Feature",
                    "state": "opened",
                    "author": {"username": "alice"},
                    "source_branch": "feat/x",
                    "target_branch": "main",
                    "merge_status": "can_be_merged",
                }
            ]
        )
    )
    result = connector.list_merge_requests("group/repo", state="opened")
    assert isinstance(result, dict)
    mr = result["merge_requests"][0]
    assert mr["mr_ref"] == "mr_1"
    assert mr["iid"] == 99
    assert mr["source_branch"] == "feat/x"
    assert "mr_id" not in mr


def test_gitlab_list_pipelines_summary() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 42,
                    "project_id": 5,
                    "status": "success",
                    "source": "push",
                    "ref": "main",
                    "sha": "abcdef1234567890",
                }
            ]
        )
    )
    result = connector.list_pipelines("group/repo", status="success")
    assert isinstance(result, dict)
    pipeline = result["pipelines"][0]
    assert pipeline["pipeline_ref"] == "pipeline_1"
    assert pipeline["pipeline_id"] == 42
    assert pipeline["short_sha"] == "abcdef12"
    assert "sha" not in pipeline


def test_gitlab_list_branches_summary() -> None:
    connector, transport = _gitlab()
    transport.enqueue(
        json_response(
            [
                {
                    "name": "main",
                    "default": True,
                    "protected": True,
                    "merged": False,
                    "commit": {"id": "abcdef1234567890"},
                }
            ]
        )
    )
    result = connector.list_branches("group/repo")
    assert isinstance(result, dict)
    branch = result["branches"][0]
    assert branch["branch_ref"] == "branch_1"
    assert branch["name"] == "main"
    assert branch["short_sha"] == "abcdef12"


def test_gitlab_destructive_delete_issue_tagged() -> None:
    connector, _ = _gitlab()
    opts = get_toolify_options(connector.delete_issue)
    assert opts is not None
    assert opts.destructive is True
    list_opts = get_toolify_options(connector.list_issues)
    assert list_opts is not None
    assert list_opts.destructive is False


# MARK: - Agent-ready behavior: Bitbucket


def test_bb_list_repositories_returns_summary() -> None:
    connector, transport = _bb()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {
                        "uuid": "{abc}",
                        "name": "myrepo",
                        "slug": "myrepo",
                        "full_name": "acme/myrepo",
                        "workspace": {"slug": "acme"},
                        "is_private": True,
                        "description": "demo",
                        "language": "python",
                        "mainbranch": {"name": "main"},
                    }
                ],
                "next": None,
            }
        )
    )
    result = connector.list_repositories("acme")
    assert isinstance(result, dict)
    repo = result["repositories"][0]
    assert repo["repo_ref"] == "repo_1"
    assert repo["full_name"] == "acme/myrepo"
    assert repo["slug"] == "myrepo"
    assert repo["default_branch"] == "main"
    assert "uuid" not in repo


def test_bb_list_repositories_include_ids() -> None:
    connector, transport = _bb()
    transport.enqueue(
        json_response({"values": [{"uuid": "{abc}", "name": "r", "full_name": "acme/r"}]})
    )
    result = connector.list_repositories("acme", include_ids=True)
    assert isinstance(result, dict)
    assert result["repositories"][0]["uuid"] == "{abc}"


def test_bb_list_pull_requests_summary() -> None:
    connector, transport = _bb()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {
                        "id": 7,
                        "title": "PR",
                        "state": "OPEN",
                        "author": {"display_name": "Alice"},
                        "source": {"branch": {"name": "feat"}},
                        "destination": {"branch": {"name": "main"}},
                        "links": {"html": {"href": "https://bitbucket.org/acme/r/pr/7"}},
                    }
                ]
            }
        )
    )
    result = connector.list_pull_requests("acme", "myrepo", state="OPEN")
    assert isinstance(result, dict)
    pr = result["pull_requests"][0]
    assert pr["pr_ref"] == "pr_1"
    assert pr["pr_id"] == 7
    assert pr["source_branch"] == "feat"
    assert pr["destination_branch"] == "main"
    assert pr["html_url"] == "https://bitbucket.org/acme/r/pr/7"


def test_bb_list_issues_summary() -> None:
    connector, transport = _bb()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {
                        "id": 12,
                        "title": "bug",
                        "state": "new",
                        "kind": "bug",
                        "priority": "major",
                        "reporter": {"display_name": "Alice"},
                    }
                ]
            }
        )
    )
    result = connector.list_issues("acme", "myrepo")
    assert isinstance(result, dict)
    issue = result["issues"][0]
    assert issue["issue_ref"] == "issue_1"
    assert issue["issue_id"] == 12
    assert issue["kind"] == "bug"


def test_bb_list_pipelines_summary() -> None:
    connector, transport = _bb()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {
                        "uuid": "{xyz}",
                        "build_number": 5,
                        "state": {
                            "name": "COMPLETED",
                            "result": {"name": "SUCCESSFUL"},
                        },
                        "target": {
                            "ref_name": "main",
                            "commit": {"hash": "abcdef1234"},
                        },
                        "creator": {"display_name": "Alice"},
                    }
                ]
            }
        )
    )
    result = connector.list_pipelines("acme", "myrepo")
    assert isinstance(result, dict)
    pipeline = result["pipelines"][0]
    assert pipeline["pipeline_ref"] == "pipeline_1"
    assert pipeline["build_number"] == 5
    assert pipeline["state"] == "COMPLETED"
    assert pipeline["result"] == "SUCCESSFUL"
    assert pipeline["short_sha"] == "abcdef1"


def test_bb_list_branches_summary() -> None:
    connector, transport = _bb()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {"name": "main", "target": {"hash": "abcdef1234"}},
                ]
            }
        )
    )
    result = connector.list_branches("acme", "myrepo")
    assert isinstance(result, dict)
    branch = result["branches"][0]
    assert branch["branch_ref"] == "branch_1"
    assert branch["name"] == "main"
    assert branch["short_sha"] == "abcdef1"


def test_bb_repo_lookup_accepts_full_name_shorthand() -> None:
    connector, transport = _bb()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.get_repository("acme/myrepo")
    connector.get_repository({"full_name": "acme/myrepo"})
    for request in transport.requests:
        assert request.url.endswith("/2.0/repositories/acme/myrepo")


def test_bb_merge_pull_request_accepts_pr_dict() -> None:
    connector, transport = _bb()
    transport.enqueue(json_response({"state": "MERGED"}))
    pr = {
        "id": 7,
        "destination": {"repository": {"full_name": "acme/myrepo"}},
    }
    connector.merge_pull_request(pr, merge_strategy="squash")
    request = transport.requests[0]
    assert "/2.0/repositories/acme/myrepo/pullrequests/7/merge" in request.url
    assert request.json_body == {"merge_strategy": "squash"}


def test_bb_merge_pull_request_accepts_full_name_shorthand() -> None:
    connector, transport = _bb()
    transport.enqueue(json_response({"state": "MERGED"}))
    connector.merge_pull_request("acme/myrepo", 1, merge_strategy="squash")
    request = transport.requests[0]
    assert "/2.0/repositories/acme/myrepo/pullrequests/1/merge" in request.url


# MARK: - Agent-ready behavior: Azure DevOps


def test_ado_list_projects_returns_summary() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [
                    {
                        "id": "abc-123-guid",
                        "name": "MyProj",
                        "description": "demo",
                        "state": "wellFormed",
                        "visibility": "private",
                        "url": "https://dev.azure.com/acme/MyProj",
                    }
                ],
            }
        )
    )
    result = connector.list_projects()
    assert isinstance(result, dict)
    project = result["projects"][0]
    assert project["project_ref"] == "project_1"
    assert project["name"] == "MyProj"
    assert "project_id" not in project
    assert "url" not in project


def test_ado_list_projects_include_ids() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [{"id": "abc-123", "name": "MyProj"}],
            }
        )
    )
    result = connector.list_projects(include_ids=True)
    assert isinstance(result, dict)
    assert result["projects"][0]["project_id"] == "abc-123"


def test_ado_list_repositories_summary() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [
                    {
                        "id": "repo-guid",
                        "name": "myrepo",
                        "project": {"id": "proj-guid", "name": "MyProj"},
                        "defaultBranch": "refs/heads/main",
                        "size": 1024,
                        "webUrl": "https://dev.azure.com/acme/MyProj/_git/myrepo",
                    }
                ],
            }
        )
    )
    result = connector.list_repositories("MyProj")
    assert isinstance(result, dict)
    repo = result["repositories"][0]
    assert repo["repo_ref"] == "repo_1"
    assert repo["name"] == "myrepo"
    assert repo["project"] == "MyProj"
    assert repo["default_branch"] == "main"
    assert "repo_id" not in repo


def test_ado_list_pull_requests_summary() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [
                    {
                        "pullRequestId": 7,
                        "title": "PR",
                        "status": "active",
                        "isDraft": False,
                        "createdBy": {"displayName": "Alice"},
                        "sourceRefName": "refs/heads/feat",
                        "targetRefName": "refs/heads/main",
                        "mergeStatus": "succeeded",
                        "repository": {"id": "repo-guid", "name": "myrepo"},
                    }
                ],
            }
        )
    )
    result = connector.list_pull_requests("MyProj", "myrepo", status="active")
    assert isinstance(result, dict)
    pr = result["pull_requests"][0]
    assert pr["pr_ref"] == "pr_1"
    assert pr["pull_request_id"] == 7
    assert pr["source_ref"] == "refs/heads/feat"
    assert pr["author"] == "Alice"
    assert "repo_id" not in pr


def test_ado_list_branches_summary_strips_refs_prefix() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [
                    {
                        "name": "refs/heads/main",
                        "objectId": "abcdef1234",
                        "creator": {"displayName": "Alice"},
                    }
                ],
            }
        )
    )
    result = connector.list_branches("MyProj", "myrepo")
    assert isinstance(result, dict)
    branch = result["branches"][0]
    assert branch["name"] == "main"
    assert branch["short_sha"] == "abcdef1"


def test_ado_list_pipelines_summary() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [
                    {
                        "id": 42,
                        "name": "ci",
                        "folder": "\\",
                        "revision": 1,
                        "_links": {
                            "web": {
                                "href": "https://dev.azure.com/acme/MyProj/_build/definition/42"
                            }
                        },
                    }
                ],
            }
        )
    )
    result = connector.list_pipelines("MyProj")
    assert isinstance(result, dict)
    pipeline = result["pipelines"][0]
    assert pipeline["pipeline_ref"] == "pipeline_1"
    assert pipeline["pipeline_id"] == 42
    assert pipeline["name"] == "ci"


def test_ado_list_builds_summary() -> None:
    connector, transport = _ado()
    transport.enqueue(
        json_response(
            {
                "count": 1,
                "value": [
                    {
                        "id": 99,
                        "buildNumber": "20260101.1",
                        "status": "completed",
                        "result": "succeeded",
                        "sourceBranch": "refs/heads/main",
                        "sourceVersion": "abcdef1234",
                        "definition": {"id": 42, "name": "ci"},
                        "requestedBy": {"displayName": "Alice"},
                    }
                ],
            }
        )
    )
    result = connector.list_builds("MyProj")
    assert isinstance(result, dict)
    build = result["builds"][0]
    assert build["build_ref"] == "build_1"
    assert build["build_id"] == 99
    assert build["build_number"] == "20260101.1"
    assert build["source_branch"] == "main"
    assert build["short_sha"] == "abcdef1"
    assert build["definition"] == "ci"


def test_ado_repo_lookup_accepts_project_and_repo_dicts() -> None:
    connector, transport = _ado()
    transport.enqueue(json_response({}))
    project = {"name": "MyProj"}
    repo = {"name": "myrepo"}
    connector.get_repository(project, repo)
    request = transport.requests[0]
    assert "/MyProj/_apis/git/repositories/myrepo" in request.url


def test_ado_complete_pull_request_accepts_pr_dict() -> None:
    connector, transport = _ado()
    transport.enqueue(json_response({"status": "completed"}))
    pr = {
        "pullRequestId": 5,
        "repository": {"name": "myrepo", "project": {"name": "MyProj"}},
        "lastMergeSourceCommit": {"commitId": "abc123"},
    }
    connector.complete_pull_request(pr, squash_merge=True)
    request = transport.requests[0]
    assert "/MyProj/_apis/git/repositories/myrepo/pullrequests/5" in request.url
    assert request.method == "PATCH"
    body = request.json_body
    assert body["status"] == "completed"
    assert body["lastMergeSourceCommit"]["commitId"] == "abc123"
    assert body["completionOptions"]["squashMerge"] is True


def test_ado_destructive_delete_work_item_tagged() -> None:
    connector, _ = _ado()
    opts = get_toolify_options(connector.delete_work_item)
    assert opts is not None
    assert opts.destructive is True
    list_opts = get_toolify_options(connector.list_pull_requests)
    assert list_opts is not None
    assert list_opts.destructive is False


# MARK: - Agent-ready behavior: Bitbucket destructive tagging


def test_bb_no_strict_destructive_tools_but_writes_are_marked() -> None:
    connector, _ = _bb()
    # Bitbucket connector has no DELETE tools; verify writes are WRITE not destructive.
    write_methods = [
        connector.create_issue,
        connector.create_pull_request,
        connector.merge_pull_request,
        connector.run_pipeline,
    ]
    for method in write_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False, f"{method.__name__} should not be tagged destructive"


# MARK: - Agent-ready behavior: Linear


def test_linear_list_issues_returns_summary_by_default() -> None:
    connector, transport = _linear()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "uuid-1",
                                "identifier": "ENG-1",
                                "title": "Login bug",
                                "state": {"name": "Todo"},
                                "priority": 2,
                                "assignee": {"id": "u1", "name": "Alice"},
                                "team": {"id": "t1", "key": "ENG"},
                                "updatedAt": "2026-05-01T00:00:00Z",
                                "url": "https://linear.app/x/issue/ENG-1",
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        )
    )
    result = connector.list_issues()
    issue = result["issues"][0]
    assert issue["issue_ref"] == "issue_1"
    assert issue["identifier"] == "ENG-1"
    assert issue["team"] == "ENG"
    assert issue["assignee"] == "Alice"
    assert "issue_id" not in issue


def test_linear_list_issues_include_ids_exposes_uuid() -> None:
    connector, transport = _linear()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "uuid-1",
                                "identifier": "ENG-1",
                                "title": "x",
                                "state": {"name": "Todo"},
                            }
                        ],
                        "pageInfo": {},
                    }
                }
            }
        )
    )
    result = connector.list_issues(include_ids=True)
    assert result["issues"][0]["issue_id"] == "uuid-1"


def test_linear_list_issues_raw_mode() -> None:
    connector, transport = _linear()
    raw: dict[str, Any] = {
        "issues": {"nodes": [{"id": "u", "identifier": "ENG-1"}], "pageInfo": {}}
    }
    transport.enqueue(json_response({"data": raw}))
    result = connector.list_issues(include_metadata=False)
    assert result == raw


def test_linear_update_issue_tolerates_summary_dict() -> None:
    connector, transport = _linear()
    transport.enqueue(json_response({"data": {"issueUpdate": {"success": True}}}))
    summary = {"issue_ref": "issue_1", "identifier": "ENG-1"}
    connector.update_issue(summary, {"title": "New"})
    body = transport.requests[0].json_body
    assert body["variables"]["id"] == "ENG-1"


def test_linear_archive_issue_tolerates_list() -> None:
    connector, transport = _linear()
    transport.enqueue(json_response({"data": {"issueArchive": {"success": True}}}))
    connector.archive_issue([{"identifier": "ENG-1"}])
    body = transport.requests[0].json_body
    assert body["variables"]["id"] == "ENG-1"


def test_linear_archive_is_destructive() -> None:
    connector, _ = _linear()
    opts = get_toolify_options(connector.archive_issue)
    assert opts is not None and opts.destructive is True


# MARK: - Agent-ready behavior: ServiceNow


def test_snow_list_records_returns_summary_by_default() -> None:
    connector, transport = _snow()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "sys_id": "abc",
                        "number": "INC0001",
                        "short_description": "Email is down",
                        "state": "1",
                        "priority": "1",
                        "urgency": "1",
                        "assigned_to": "alice",
                        "sys_updated_on": "2026-05-01 10:00:00",
                    },
                    {
                        "sys_id": "def",
                        "number": "INC0002",
                        "short_description": "Printer offline",
                        "state": "2",
                        "priority": "3",
                    },
                ]
            }
        )
    )
    result = connector.list_records("incident")
    records = result["records"]
    assert [r["record_ref"] for r in records] == ["record_1", "record_2"]
    assert records[0]["number"] == "INC0001"
    assert records[0]["short_description"] == "Email is down"
    assert "sys_id" not in records[0]
    assert records[0]["table"] == "incident"


def test_snow_list_records_include_ids_exposes_sys_id() -> None:
    connector, transport = _snow()
    transport.enqueue(json_response({"result": [{"sys_id": "abc", "number": "INC0001"}]}))
    result = connector.list_records("incident", include_ids=True)
    assert result["records"][0]["sys_id"] == "abc"


def test_snow_list_records_raw_mode_returns_provider_payload() -> None:
    connector, transport = _snow()
    raw = {"result": [{"sys_id": "abc", "number": "INC0001"}]}
    transport.enqueue(json_response(raw))
    result = connector.list_records("incident", include_metadata=False)
    assert result == raw


def test_snow_update_record_tolerates_summary_dict() -> None:
    connector, transport = _snow()
    transport.enqueue(json_response({"result": {"sys_id": "abc"}}))
    summary = {"record_ref": "record_1", "sys_id": "abc"}
    connector.update_record("incident", summary, {"state": "2"})
    assert transport.requests[0].url.endswith("/api/now/table/incident/abc")


def test_snow_delete_record_tolerates_list_of_summaries() -> None:
    connector, transport = _snow()
    transport.enqueue(json_response({}))
    summaries = [{"record_ref": "record_1", "sys_id": "abc"}]
    connector.delete_record("incident", summaries)
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[0].url.endswith("/api/now/table/incident/abc")


def test_snow_destructive_tools_are_tagged() -> None:
    connector, _ = _snow()
    for method in (connector.delete_record, connector.delete_attachment):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True
