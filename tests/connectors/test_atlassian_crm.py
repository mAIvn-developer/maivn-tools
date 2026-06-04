# pyright: strict
from __future__ import annotations

from typing import cast

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.hubspot import HubSpotToolSet
from maivn_tools.connectors.jira import JiraToolSet
from maivn_tools.connectors.salesforce import SalesforceToolSet
from maivn_tools.connectors.zendesk import ZendeskToolSet
from maivn_tools.core import PermissionFlag, PermissionSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Jira


def _jira() -> tuple[JiraToolSet, MockTransport]:
    transport = MockTransport()
    return (
        JiraToolSet(
            base_url="https://acme.atlassian.net",
            email="ops@example.test",
            api_token="api-token",
            transport=transport,
        ),
        transport,
    )


def test_jira_validates_inputs() -> None:
    with pytest.raises(ValueError):
        JiraToolSet(base_url="", email="x", api_token="t")
    with pytest.raises(ValueError):
        JiraToolSet(base_url="https://x", email="", api_token="t")
    with pytest.raises(ValueError):
        JiraToolSet(base_url="https://x", email="x", api_token="")


def test_jira_myself_uses_basic_auth_header() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({"accountId": "u-1"}))
    connector.myself()
    request = transport.requests[0]
    assert request.url.endswith("/rest/api/3/myself")
    assert request.headers["Authorization"].startswith("Basic ")


def test_jira_search_issues_validates_inputs_and_posts_jql() -> None:
    connector, transport = _jira()
    with pytest.raises(ValueError):
        connector.search_issues(jql="")
    with pytest.raises(ValueError):
        connector.search_issues(jql="project = ENG", max_results=0)
    transport.enqueue(json_response({"issues": []}))
    connector.search_issues(jql="project = ENG", fields=["summary"])
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.json_body["jql"] == "project = ENG"
    assert request.json_body["fields"] == ["summary"]


def test_jira_create_issue_validates_required_fields() -> None:
    connector, transport = _jira()
    opts = get_toolify_options(connector.create_issue)
    assert opts is not None
    assert opts.permissions is not None
    assert cast(PermissionSet, opts.permissions).includes(PermissionFlag.WRITE)
    with pytest.raises(ValueError):
        connector.create_issue(project_key="", summary="x", issue_type="Task")
    with pytest.raises(ValueError):
        connector.create_issue(project_key="ENG", summary="", issue_type="Task")
    with pytest.raises(ValueError):
        connector.create_issue(project_key="ENG", summary="x", issue_type="")
    transport.enqueue(json_response({"id": "10001", "key": "ENG-1"}))
    connector.create_issue(project_key="ENG", summary="Bug", issue_type="Bug", labels=["urgent"])
    payload = transport.requests[0].json_body
    assert payload["fields"]["project"] == {"key": "ENG"}
    assert payload["fields"]["labels"] == ["urgent"]


def test_jira_add_comment_validates_body() -> None:
    connector, _ = _jira()
    with pytest.raises(ValueError):
        connector.add_comment(issue_key="ENG-1", body="")


def test_jira_transition_issue_posts_payload() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({}))
    connector.transition_issue(issue_key="ENG-1", transition_id="31")
    assert transport.requests[0].json_body == {"transition": {"id": "31"}}


def test_jira_list_transitions_and_delete_issue() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({"transitions": []}))
    transport.enqueue(json_response({}))
    connector.list_transitions("ENG-1")
    result = connector.delete_issue("ENG-1", delete_subtasks=True)
    assert transport.requests[0].url.endswith("/rest/api/3/issue/ENG-1/transitions")
    assert transport.requests[1].method == "DELETE"
    assert transport.requests[1].params == {"deleteSubtasks": "true"}
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.list_transitions("")
    with pytest.raises(ValueError):
        connector.delete_issue("")


def test_jira_assign_issue() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.assign_issue("ENG-1", account_id="abc")
    connector.assign_issue("ENG-1", account_id=None)
    assert transport.requests[0].json_body == {"accountId": "abc"}
    assert transport.requests[1].json_body == {"accountId": None}
    with pytest.raises(ValueError):
        connector.assign_issue("")


def test_jira_comments_crud() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({"comments": []}))
    transport.enqueue(json_response({"id": "c1", "body": "new"}))
    transport.enqueue(json_response({}))
    connector.list_comments("ENG-1")
    connector.update_comment("ENG-1", "c1", "new")
    result = connector.delete_comment("ENG-1", "c1")
    assert transport.requests[1].method == "PUT"
    assert transport.requests[2].method == "DELETE"
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.list_comments("")
    with pytest.raises(ValueError):
        connector.update_comment("", "c", "b")
    with pytest.raises(ValueError):
        connector.update_comment("E", "", "b")
    with pytest.raises(ValueError):
        connector.update_comment("E", "c", "")
    with pytest.raises(ValueError):
        connector.delete_comment("", "c")


def test_jira_worklog_list_and_add() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({"worklogs": []}))
    transport.enqueue(json_response({"id": "wl1"}))
    connector.list_worklogs("ENG-1")
    connector.add_worklog("ENG-1", time_spent="30m", comment="working")
    assert transport.requests[1].json_body["timeSpent"] == "30m"
    with pytest.raises(ValueError):
        connector.list_worklogs("")
    with pytest.raises(ValueError):
        connector.add_worklog("", time_spent="30m")
    with pytest.raises(ValueError):
        connector.add_worklog("E", time_spent="")


def test_jira_links_and_attachments() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"fields": {"attachment": [{"id": "a1"}]}}))
    transport.enqueue(json_response({}))
    connector.link_issues(inward_issue="ENG-1", outward_issue="ENG-2", link_type="Blocks")
    result_del = connector.delete_issue_link("l1")
    result_att = connector.list_attachments("ENG-1")
    result_del_att = connector.delete_attachment("a1")
    assert transport.requests[0].url.endswith("/rest/api/3/issueLink")
    assert result_del["deleted"] is True
    assert result_att["attachments"][0]["id"] == "a1"
    assert result_del_att["deleted"] is True
    with pytest.raises(ValueError):
        connector.link_issues(inward_issue="", outward_issue="x", link_type="Blocks")
    with pytest.raises(ValueError):
        connector.delete_issue_link("")
    with pytest.raises(ValueError):
        connector.list_attachments("")
    with pytest.raises(ValueError):
        connector.delete_attachment("")


def test_jira_projects_users_metadata() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({"values": []}))
    transport.enqueue(json_response({"id": "10000", "key": "ENG"}))
    transport.enqueue(json_response([{"name": "Task"}]))
    transport.enqueue(json_response({"accountId": "abc"}))
    transport.enqueue(json_response([{"accountId": "abc"}]))
    transport.enqueue(json_response([{"name": "Open"}]))
    transport.enqueue(json_response([{"name": "High"}]))
    transport.enqueue(json_response([{"name": "Done"}]))
    transport.enqueue(json_response([{"id": "summary"}]))
    connector.list_projects()
    connector.get_project("ENG")
    connector.list_issue_types("ENG")
    connector.get_user("abc")
    connector.search_users("alice")
    connector.list_statuses()
    connector.list_priorities()
    connector.list_resolutions()
    connector.list_fields()
    assert transport.requests[0].url.endswith("/rest/api/3/project/search")
    assert transport.requests[3].params == {"accountId": "abc"}
    with pytest.raises(ValueError):
        connector.get_project("")
    with pytest.raises(ValueError):
        connector.list_issue_types("")
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.search_users("")


def test_jira_boards_sprints_versions() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({"values": []}))
    transport.enqueue(json_response({"values": []}))
    transport.enqueue(json_response({"id": 1}))
    transport.enqueue(json_response([{"name": "v1"}]))
    connector.list_boards(type="scrum", project_key="ENG")
    connector.list_sprints(board_id=1, state="active")
    connector.get_sprint(sprint_id=1)
    connector.list_versions("ENG")
    assert transport.requests[0].url.endswith("/rest/agile/1.0/board")
    assert transport.requests[0].params["type"] == "scrum"
    assert transport.requests[1].params["state"] == "active"
    assert transport.requests[3].url.endswith("/rest/api/3/project/ENG/versions")
    with pytest.raises(ValueError):
        connector.list_versions("")


# MARK: - Zendesk


def _zendesk() -> tuple[ZendeskToolSet, MockTransport]:
    transport = MockTransport()
    return (
        ZendeskToolSet(
            subdomain="acme",
            email="ops@example.test",
            api_token="api-token",
            transport=transport,
        ),
        transport,
    )


def test_zendesk_requires_subdomain_or_base_url() -> None:
    with pytest.raises(ValueError):
        ZendeskToolSet(email="x", api_token="t")
    with pytest.raises(ValueError):
        ZendeskToolSet(subdomain="x", email="", api_token="t")
    with pytest.raises(ValueError):
        ZendeskToolSet(subdomain="x", email="x", api_token="")


def test_zendesk_search_serializes_query_and_paging() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"results": []}))
    connector.search_tickets(query="type:ticket status:open", page=2, per_page=10)
    request = transport.requests[0]
    assert request.url.endswith("/api/v2/search.json")
    assert request.params["query"] == "type:ticket status:open"
    assert request.params["page"] == 2
    assert request.headers["Authorization"].startswith("Basic ")


def test_zendesk_create_ticket_validates_and_wraps_body() -> None:
    connector, transport = _zendesk()
    with pytest.raises(ValueError):
        connector.create_ticket(subject="", description="x")
    with pytest.raises(ValueError):
        connector.create_ticket(subject="x", description="")
    transport.enqueue(json_response({"ticket": {"id": 1}}))
    connector.create_ticket(
        subject="Help",
        description="Body",
        requester_email="user@example.test",
        priority="urgent",
        tags=["vip"],
    )
    payload = transport.requests[0].json_body
    assert payload["ticket"]["comment"]["body"] == "Body"
    assert payload["ticket"]["requester"]["email"] == "user@example.test"
    assert payload["ticket"]["tags"] == ["vip"]


def test_zendesk_add_comment_validates_body_and_uses_put() -> None:
    connector, transport = _zendesk()
    with pytest.raises(ValueError):
        connector.add_comment(ticket_id=1, body="")
    transport.enqueue(json_response({"ticket": {"id": 1}}))
    connector.add_comment(ticket_id=1, body="hi", public=False)
    request = transport.requests[0]
    assert request.method == "PUT"
    assert request.json_body["ticket"]["comment"]["public"] is False


def test_zendesk_list_and_delete_tickets_and_comments() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"tickets": []}))
    transport.enqueue(json_response({"comments": []}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"job_status": {}}))
    connector.list_tickets(per_page=50)
    connector.list_ticket_comments(ticket_id=1, per_page=10)
    result = connector.delete_ticket(ticket_id=1)
    connector.merge_tickets(target_ticket_id=1, source_ticket_ids=[2, 3], comment="merged")
    assert transport.requests[0].params["per_page"] == 50
    assert transport.requests[1].url.endswith("/api/v2/tickets/1/comments.json")
    assert result["deleted"] is True
    assert transport.requests[3].json_body["ids"] == [2, 3]
    with pytest.raises(ValueError):
        connector.list_tickets(per_page=0)
    with pytest.raises(ValueError):
        connector.merge_tickets(target_ticket_id=1, source_ticket_ids=[])


def test_zendesk_user_lifecycle() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"users": []}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"user": {"id": 5}}))
    transport.enqueue(json_response({"user": {"id": 5}}))
    transport.enqueue(json_response({}))
    connector.list_users(role="agent", per_page=10)
    connector.search_users("alice")
    connector.create_user(name="Alice", email="alice@example.test", role="agent")
    connector.update_user(user_id=5, patch={"role": "end-user"})
    result = connector.delete_user(user_id=5)
    assert transport.requests[0].params["role"] == "agent"
    assert transport.requests[1].params["query"].startswith("type:user ")
    assert transport.requests[2].json_body["user"]["email"] == "alice@example.test"
    assert transport.requests[3].method == "PUT"
    assert result["deleted"] is True
    with pytest.raises(ValueError):
        connector.search_users("")
    with pytest.raises(ValueError):
        connector.create_user(name="", email="x")
    with pytest.raises(ValueError):
        connector.update_user(user_id=1, patch={})


def test_zendesk_orgs_and_groups() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"organizations": []}))
    transport.enqueue(json_response({"organization": {"id": 9}}))
    transport.enqueue(json_response({"organization": {"id": 9}}))
    transport.enqueue(json_response({"groups": []}))
    transport.enqueue(json_response({"group": {"id": 2}}))
    connector.list_organizations()
    connector.get_organization(organization_id=9)
    connector.create_organization(name="Acme")
    connector.list_groups()
    connector.get_group(group_id=2)
    assert transport.requests[0].url.endswith("/api/v2/organizations.json")
    assert transport.requests[2].json_body == {"organization": {"name": "Acme"}}
    with pytest.raises(ValueError):
        connector.create_organization(name="")


def test_zendesk_macros_and_views() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"macros": []}))
    transport.enqueue(json_response({"result": {}}))
    transport.enqueue(json_response({"views": []}))
    transport.enqueue(json_response({"tickets": []}))
    connector.list_macros(active=True)
    connector.show_macro_application(ticket_id=1, macro_id=2)
    connector.list_views()
    connector.execute_view(view_id=3)
    assert transport.requests[0].params["active"] == "true"
    assert transport.requests[1].url.endswith("/api/v2/tickets/1/macros/2/apply.json")
    assert transport.requests[3].url.endswith("/api/v2/views/3/execute.json")


def test_zendesk_fields_and_tags() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"ticket_fields": []}))
    transport.enqueue(json_response({"user_fields": []}))
    transport.enqueue(json_response({"tags": []}))
    transport.enqueue(json_response({"tags": []}))
    connector.list_ticket_fields()
    connector.list_user_fields()
    connector.add_tags_to_ticket(ticket_id=1, tags=["vip"])
    connector.remove_tags_from_ticket(ticket_id=1, tags=["vip"])
    assert transport.requests[2].method == "PUT"
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.add_tags_to_ticket(ticket_id=1, tags=[])
    with pytest.raises(ValueError):
        connector.remove_tags_from_ticket(ticket_id=1, tags=[])


# MARK: - HubSpot


def _hubspot() -> tuple[HubSpotToolSet, MockTransport]:
    transport = MockTransport()
    return HubSpotToolSet(token="hs-secret", transport=transport), transport


def test_hubspot_validates_token() -> None:
    with pytest.raises(ValueError):
        HubSpotToolSet(token="")


def test_hubspot_rejects_unknown_object_type() -> None:
    connector, _ = _hubspot()
    with pytest.raises(ValueError):
        connector.list_objects(object_type="files")


def test_hubspot_list_objects_serializes_properties() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({"results": []}))
    connector.list_objects(object_type="contacts", properties=["email", "firstname"])
    request = transport.requests[0]
    assert request.url.endswith("/crm/v3/objects/contacts")
    assert request.params["properties"] == "email,firstname"


def test_hubspot_create_object_validates_and_wraps_payload() -> None:
    connector, transport = _hubspot()
    with pytest.raises(ValueError):
        connector.create_object(object_type="contacts", properties={})
    transport.enqueue(json_response({"id": "1"}))
    connector.create_object(object_type="contacts", properties={"email": "x@example.test"})
    assert transport.requests[0].json_body == {"properties": {"email": "x@example.test"}}


def test_hubspot_archive_object_is_destructive() -> None:
    connector, transport = _hubspot()
    opts = get_toolify_options(connector.archive_object)
    assert opts is not None and opts.destructive is True
    transport.enqueue(json_response({}))
    connector.archive_object(object_type="contacts", object_id="1")


def test_hubspot_create_note_attaches_timestamp() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({"id": "n1"}))
    connector.create_note(body="Followed up")
    payload = transport.requests[0].json_body
    assert payload["properties"]["hs_note_body"] == "Followed up"
    assert isinstance(payload["properties"]["hs_timestamp"], int)


def test_hubspot_engagements_and_tasks() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "t1"}))
    transport.enqueue(json_response({"id": "e1"}))
    connector.list_engagements(engagement_type="tasks", limit=10)
    connector.create_task(subject="Follow up", priority="HIGH", status="IN_PROGRESS")
    connector.create_email_engagement(subject="Re:", text="hello")
    assert transport.requests[0].url.endswith("/crm/v3/objects/tasks")
    assert transport.requests[1].json_body["properties"]["hs_task_priority"] == "HIGH"
    assert transport.requests[2].json_body["properties"]["hs_email_subject"] == "Re:"
    with pytest.raises(ValueError):
        connector.list_engagements(engagement_type="bogus")
    with pytest.raises(ValueError):
        connector.create_task(subject="")
    with pytest.raises(ValueError):
        connector.create_task(subject="x", priority="BAD")
    with pytest.raises(ValueError):
        connector.create_task(subject="x", status="BAD")
    with pytest.raises(ValueError):
        connector.create_email_engagement(subject="", text="hi")
    with pytest.raises(ValueError):
        connector.create_email_engagement(subject="x", text="hi", direction="BAD")


def test_hubspot_pipelines_owners_properties() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "p1"}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "o1"}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"name": "email"}))
    connector.list_pipelines(object_type="deals")
    connector.get_pipeline(object_type="deals", pipeline_id="p1")
    connector.list_owners(email="alice@x")
    connector.get_owner("o1")
    connector.list_properties(object_type="contacts")
    connector.get_property(object_type="contacts", property_name="email")
    assert transport.requests[0].url.endswith("/crm/v3/pipelines/deals")
    assert transport.requests[2].params["email"] == "alice@x"
    assert transport.requests[5].url.endswith("/crm/v3/properties/contacts/email")
    with pytest.raises(ValueError):
        connector.get_pipeline(object_type="deals", pipeline_id="")
    with pytest.raises(ValueError):
        connector.get_owner("")
    with pytest.raises(ValueError):
        connector.get_property(object_type="contacts", property_name="")


def test_hubspot_associations_and_batch() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({}))
    connector.associate_objects(
        from_object_type="contacts",
        from_object_id="c1",
        to_object_type="deals",
        to_object_id="d1",
    )
    result = connector.remove_association(
        from_object_type="contacts",
        from_object_id="c1",
        to_object_type="deals",
        to_object_id="d1",
    )
    connector.batch_read_objects(object_type="contacts", ids=["1", "2"], properties=["email"])
    connector.batch_create_objects(
        object_type="contacts", inputs=[{"properties": {"email": "a@b"}}]
    )
    connector.batch_update_objects(
        object_type="contacts",
        inputs=[{"id": "1", "properties": {"email": "x@y"}}],
    )
    archive_result = connector.batch_archive_objects(object_type="contacts", ids=["1"])
    assert transport.requests[0].method == "PUT"
    assoc_url = transport.requests[0].url
    assert "/crm/v4/objects/contacts/c1/associations/default/deals/d1" in assoc_url
    assert result["removed"] is True
    assert transport.requests[2].json_body["inputs"] == [{"id": "1"}, {"id": "2"}]
    assert archive_result["archived"] == 1
    with pytest.raises(ValueError):
        connector.associate_objects(
            from_object_type="contacts",
            from_object_id="",
            to_object_type="deals",
            to_object_id="d1",
        )
    with pytest.raises(ValueError):
        connector.batch_read_objects(object_type="contacts", ids=[])
    with pytest.raises(ValueError):
        connector.batch_create_objects(object_type="contacts", inputs=[])
    with pytest.raises(ValueError):
        connector.batch_update_objects(object_type="contacts", inputs=[])
    with pytest.raises(ValueError):
        connector.batch_archive_objects(object_type="contacts", ids=[])


# MARK: - Salesforce


def _salesforce() -> tuple[SalesforceToolSet, MockTransport]:
    transport = MockTransport()
    return (
        SalesforceToolSet(
            instance_url="https://acme.my.salesforce.com",
            token="at-sf",
            transport=transport,
        ),
        transport,
    )


def test_salesforce_validates_inputs() -> None:
    with pytest.raises(ValueError):
        SalesforceToolSet(instance_url="", token="t")
    with pytest.raises(ValueError):
        SalesforceToolSet(instance_url="https://x", token="t", api_version="")


def test_salesforce_soql_query_targets_query_endpoint() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response({"records": []}))
    connector.soql_query("SELECT Id FROM Account")
    request = transport.requests[0]
    assert request.url.endswith("/services/data/v66.0/query")
    assert request.params["q"] == "SELECT Id FROM Account"


def test_salesforce_soql_query_rejects_writes_and_empty() -> None:
    connector, _ = _salesforce()
    with pytest.raises(ValueError):
        connector.soql_query("")
    with pytest.raises(ValueError):
        connector.soql_query("UPDATE Account SET Name = 'x'")


def test_salesforce_describe_object_validates_name() -> None:
    connector, transport = _salesforce()
    with pytest.raises(ValueError):
        connector.describe_object(object_name="Account; DROP")
    transport.enqueue(json_response({"name": "Account"}))
    connector.describe_object(object_name="Account")
    assert transport.requests[0].url.endswith("/sobjects/Account/describe")


def test_salesforce_create_and_update_require_fields() -> None:
    connector, _ = _salesforce()
    with pytest.raises(ValueError):
        connector.create_record(object_name="Account", fields={})
    with pytest.raises(ValueError):
        connector.update_record(object_name="Account", record_id="", fields={"Name": "x"})
    with pytest.raises(ValueError):
        connector.update_record(object_name="Account", record_id="1", fields={})


def test_salesforce_delete_is_destructive() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_record)
    assert opts is not None and opts.destructive is True
    connector.delete_record(object_name="Account", record_id="1")


def test_salesforce_upsert_record_validates_and_calls() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response({"id": "001"}))
    connector.upsert_record(
        object_name="Account",
        external_field="ExtId__c",
        external_value="abc-123",
        fields={"Name": "Acme"},
    )
    assert "/sobjects/Account/ExtId__c/abc-123" in transport.requests[0].url
    assert transport.requests[0].method == "PATCH"
    with pytest.raises(ValueError):
        connector.upsert_record(
            object_name="Account",
            external_field="bad name",
            external_value="x",
            fields={"Name": "y"},
        )
    with pytest.raises(ValueError):
        connector.upsert_record(
            object_name="Account",
            external_field="Ext__c",
            external_value="",
            fields={"Name": "y"},
        )
    with pytest.raises(ValueError):
        connector.upsert_record(
            object_name="Account",
            external_field="Ext__c",
            external_value="x",
            fields={},
        )


def test_salesforce_query_more_and_query_all_and_sosl() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response({"records": []}))
    transport.enqueue(json_response({"records": []}))
    transport.enqueue(json_response({"searchRecords": []}))
    connector.query_more("/services/data/v66.0/query/01g00")
    connector.query_all("SELECT Id FROM Account WHERE IsDeleted = TRUE")
    connector.sosl_search("FIND {acme} RETURNING Account(Id, Name)")
    assert transport.requests[1].url.endswith("/services/data/v66.0/queryAll")
    assert transport.requests[2].url.endswith("/services/data/v66.0/search")
    with pytest.raises(ValueError):
        connector.query_more("")
    with pytest.raises(ValueError):
        connector.query_all("")
    with pytest.raises(ValueError):
        connector.query_all("UPDATE Account SET Name = 'x'")
    with pytest.raises(ValueError):
        connector.sosl_search("")
    with pytest.raises(ValueError):
        connector.sosl_search("SELECT 1")


def test_salesforce_recent_versions_limits_user_info() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response([{"Id": "1"}]))
    transport.enqueue(json_response([{"version": "59.0"}]))
    transport.enqueue(json_response({"Limits": {}}))
    transport.enqueue(json_response({"id": "u1"}))
    connector.get_recent_items()
    connector.list_versions()
    connector.list_limits()
    connector.get_user_info()
    assert transport.requests[0].params == {"limit": 50}
    assert transport.requests[1].url.endswith("/services/data/")
    assert transport.requests[3].url.endswith("/services/data/v66.0/chatter/users/me")
    with pytest.raises(ValueError):
        connector.get_recent_items(limit=0)
    with pytest.raises(ValueError):
        connector.get_recent_items(limit=999)


def test_salesforce_reports_and_dashboards() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response([{"id": "r1"}]))
    transport.enqueue(json_response({"id": "r1"}))
    transport.enqueue(json_response({"factMap": {}}))
    transport.enqueue(json_response([{"id": "d1"}]))
    connector.list_reports()
    connector.get_report("r1")
    connector.run_report("r1", include_details=False)
    connector.list_dashboards()
    assert transport.requests[0].url.endswith("/analytics/reports")
    assert transport.requests[2].params["includeDetails"] == "false"
    assert transport.requests[3].url.endswith("/analytics/dashboards")
    with pytest.raises(ValueError):
        connector.get_report("")
    with pytest.raises(ValueError):
        connector.run_report("")


def test_salesforce_composite_endpoints() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response({"compositeResponse": []}))
    transport.enqueue(json_response([]))
    transport.enqueue(json_response([]))
    transport.enqueue(json_response([]))
    connector.composite_request({"compositeRequest": [{"method": "GET", "url": "/x"}]})
    connector.composite_sobjects_create(
        records=[{"attributes": {"type": "Account"}, "Name": "Acme"}]
    )
    connector.composite_sobjects_update(records=[{"attributes": {"type": "Account"}, "Id": "1"}])
    connector.composite_sobjects_delete(ids=["1", "2"])
    assert transport.requests[1].method == "POST"
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[3].method == "DELETE"
    assert transport.requests[3].params["ids"] == "1,2"
    with pytest.raises(ValueError):
        connector.composite_request({})
    with pytest.raises(ValueError):
        connector.composite_sobjects_create(records=[])
    with pytest.raises(ValueError):
        connector.composite_sobjects_create(records=[{}] * 201)
    with pytest.raises(ValueError):
        connector.composite_sobjects_update(records=[])
    with pytest.raises(ValueError):
        connector.composite_sobjects_delete(ids=[])


# MARK: - Agent-ready summary mode (Jira)


def test_jira_search_issues_returns_summaries_by_default() -> None:
    connector, transport = _jira()
    transport.enqueue(
        json_response(
            {
                "issues": [
                    {
                        "id": "10001",
                        "key": "ENG-1",
                        "fields": {
                            "summary": "Login bug",
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Alice"},
                            "priority": {"name": "High"},
                            "issuetype": {"name": "Bug"},
                            "updated": "2026-05-01T10:00:00Z",
                        },
                    },
                    {
                        "id": "10002",
                        "key": "ENG-2",
                        "fields": {
                            "summary": "Improve speed",
                            "status": {"name": "In Progress"},
                            "assignee": None,
                            "priority": {"name": "Medium"},
                            "issuetype": {"name": "Task"},
                            "updated": "2026-05-02T10:00:00Z",
                        },
                    },
                ],
                "startAt": 0,
                "maxResults": 25,
                "total": 2,
            }
        )
    )
    result = connector.search_issues(jql="project = ENG")
    issues = result["issues"]
    assert [item["issue_ref"] for item in issues] == ["issue_1", "issue_2"]
    assert issues[0]["key"] == "ENG-1"
    assert issues[0]["summary"] == "Login bug"
    assert issues[0]["status"] == "To Do"
    assert issues[0]["assignee"] == "Alice"
    assert "issue_id" not in issues[0]
    assert "nextPageToken" in result
    assert "isLast" in result


def test_jira_search_issues_include_ids_exposes_raw_id() -> None:
    connector, transport = _jira()
    transport.enqueue(
        json_response(
            {
                "issues": [
                    {
                        "id": "10001",
                        "key": "ENG-1",
                        "fields": {"summary": "x", "status": {"name": "Open"}},
                    }
                ],
                "startAt": 0,
                "maxResults": 25,
                "total": 1,
            }
        )
    )
    result = connector.search_issues(jql="project = ENG", include_ids=True)
    assert result["issues"][0]["issue_id"] == "10001"
    assert result["issues"][0]["key"] == "ENG-1"


def test_jira_search_issues_raw_mode_returns_provider_payload() -> None:
    connector, transport = _jira()
    raw = {"issues": [{"id": "1", "key": "ENG-1"}], "total": 1}
    transport.enqueue(json_response(raw))
    result = connector.search_issues(jql="project = ENG", include_metadata=False)
    assert result == raw


def test_jira_list_projects_returns_summaries_by_default() -> None:
    connector, transport = _jira()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {
                        "id": "10000",
                        "key": "ENG",
                        "name": "Engineering",
                        "projectTypeKey": "software",
                        "lead": {"displayName": "Alice"},
                    }
                ],
                "startAt": 0,
                "maxResults": 25,
                "total": 1,
                "isLast": True,
            }
        )
    )
    result = connector.list_projects()
    projects = result["projects"]
    assert projects[0]["project_ref"] == "project_1"
    assert projects[0]["key"] == "ENG"
    assert "project_id" not in projects[0]
    assert result["isLast"] is True


def test_jira_list_projects_include_ids_exposes_raw_id() -> None:
    connector, transport = _jira()
    transport.enqueue(
        json_response(
            {"values": [{"id": "10000", "key": "ENG", "name": "Engineering"}], "isLast": True}
        )
    )
    result = connector.list_projects(include_ids=True)
    assert result["projects"][0]["project_id"] == "10000"


def test_jira_update_issue_tolerates_search_dict() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({}))
    summary_dict = {"issue_ref": "issue_1", "key": "ENG-1"}
    result = connector.update_issue(summary_dict, {"summary": "New"})
    assert result["key"] == "ENG-1"
    assert transport.requests[0].url.endswith("/rest/api/3/issue/ENG-1")


def test_jira_update_issue_tolerates_list_of_summaries() -> None:
    connector, transport = _jira()
    transport.enqueue(json_response({}))
    summaries = [
        {"issue_ref": "issue_1", "key": "ENG-1"},
        {"issue_ref": "issue_2", "key": "ENG-2"},
    ]
    connector.update_issue(summaries, {"summary": "y"})
    assert transport.requests[0].url.endswith("/rest/api/3/issue/ENG-1")


def test_jira_destructive_tools_are_tagged() -> None:
    connector, _ = _jira()
    for method in (
        connector.delete_issue,
        connector.delete_comment,
        connector.delete_issue_link,
        connector.delete_attachment,
    ):
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is True


# MARK: - Agent-ready summary mode (Zendesk)


def test_zendesk_list_tickets_returns_summaries_by_default() -> None:
    connector, transport = _zendesk()
    transport.enqueue(
        json_response(
            {
                "tickets": [
                    {
                        "id": 101,
                        "subject": "Login broken",
                        "status": "open",
                        "priority": "urgent",
                        "requester_id": 5,
                        "updated_at": "2026-05-01T10:00:00Z",
                        "tags": ["vip"],
                    },
                    {
                        "id": 102,
                        "subject": "Refund please",
                        "status": "pending",
                        "priority": "normal",
                        "requester_id": 6,
                        "updated_at": "2026-05-02T10:00:00Z",
                        "tags": [],
                    },
                ],
                "next_page": None,
                "previous_page": None,
                "count": 2,
            }
        )
    )
    result = connector.list_tickets()
    assert [t["ticket_ref"] for t in result["tickets"]] == ["ticket_1", "ticket_2"]
    assert result["tickets"][0]["subject"] == "Login broken"
    assert "ticket_id" not in result["tickets"][0]
    assert result["count"] == 2


def test_zendesk_list_tickets_include_ids_exposes_raw_id() -> None:
    connector, transport = _zendesk()
    transport.enqueue(
        json_response(
            {
                "tickets": [
                    {
                        "id": 42,
                        "subject": "Bug",
                        "status": "open",
                    }
                ]
            }
        )
    )
    result = connector.list_tickets(include_ids=True)
    assert result["tickets"][0]["ticket_id"] == 42


def test_zendesk_search_tickets_filters_to_ticket_results() -> None:
    connector, transport = _zendesk()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": 7,
                        "subject": "Help",
                        "status": "open",
                        "result_type": "ticket",
                    },
                    {
                        "id": 999,
                        "name": "Alice",
                        "result_type": "user",
                    },
                ]
            }
        )
    )
    result = connector.search_tickets(query="type:ticket help")
    assert len(result["tickets"]) == 1
    assert result["tickets"][0]["ticket_ref"] == "ticket_1"
    assert result["tickets"][0]["subject"] == "Help"


def test_zendesk_update_ticket_tolerates_summary_dict() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"ticket": {"id": 42}}))
    summary = {"ticket_ref": "ticket_1", "ticket_id": 42, "subject": "x"}
    connector.update_ticket(summary, {"status": "solved"})
    assert transport.requests[0].url.endswith("/api/v2/tickets/42.json")


def test_zendesk_update_ticket_tolerates_list() -> None:
    connector, transport = _zendesk()
    transport.enqueue(json_response({"ticket": {"id": 42}}))
    summaries = [{"ticket_ref": "ticket_1", "ticket_id": 42}]
    connector.update_ticket(summaries, {"status": "solved"})
    assert transport.requests[0].url.endswith("/api/v2/tickets/42.json")


def test_zendesk_delete_ticket_is_destructive() -> None:
    connector, _ = _zendesk()
    opts = get_toolify_options(connector.delete_ticket)
    assert opts is not None and opts.destructive is True
    opts_user = get_toolify_options(connector.delete_user)
    assert opts_user is not None and opts_user.destructive is True


# MARK: - Agent-ready summary mode (HubSpot)


def test_hubspot_list_objects_returns_summaries_by_default() -> None:
    connector, transport = _hubspot()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "c1",
                        "properties": {
                            "email": "alice@example.test",
                            "firstname": "Alice",
                            "lastname": "Anderson",
                            "company": "Acme",
                            "lifecyclestage": "customer",
                        },
                        "updatedAt": "2026-05-01T10:00:00Z",
                    }
                ],
                "paging": {"next": {"after": "cursor"}},
            }
        )
    )
    result = connector.list_objects(object_type="contacts")
    summary = result["objects"][0]
    assert summary["object_ref"] == "object_1"
    assert summary["email"] == "alice@example.test"
    assert summary["firstname"] == "Alice"
    assert "object_id" not in summary
    assert result["paging"]["next"]["after"] == "cursor"


def test_hubspot_list_objects_include_ids_exposes_raw_id() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({"results": [{"id": "c1", "properties": {"email": "x@y"}}]}))
    result = connector.list_objects(object_type="contacts", include_ids=True)
    assert result["objects"][0]["object_id"] == "c1"


def test_hubspot_search_objects_returns_summaries() -> None:
    connector, transport = _hubspot()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "d1",
                        "properties": {
                            "dealname": "Big Deal",
                            "dealstage": "closedwon",
                            "amount": "5000",
                        },
                        "updatedAt": "2026-04-01T00:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.search_objects(object_type="deals", query="big")
    assert result["objects"][0]["dealname"] == "Big Deal"
    assert "object_id" not in result["objects"][0]


def test_hubspot_update_object_tolerates_summary_dict() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({"id": "c1"}))
    summary = {"object_ref": "object_1", "object_id": "c1"}
    connector.update_object("contacts", summary, {"firstname": "Bob"})
    assert transport.requests[0].url.endswith("/crm/v3/objects/contacts/c1")


def test_hubspot_batch_archive_tolerates_summary_dicts() -> None:
    connector, transport = _hubspot()
    transport.enqueue(json_response({}))
    summaries = [
        {"object_ref": "object_1", "object_id": "c1"},
        {"object_ref": "object_2", "object_id": "c2"},
    ]
    connector.batch_archive_objects("contacts", summaries)
    body = transport.requests[0].json_body
    assert body["inputs"] == [{"id": "c1"}, {"id": "c2"}]


# MARK: - Agent-ready summary mode (Salesforce)


def test_salesforce_soql_query_returns_summaries_by_default() -> None:
    connector, transport = _salesforce()
    transport.enqueue(
        json_response(
            {
                "totalSize": 2,
                "done": True,
                "records": [
                    {
                        "attributes": {
                            "type": "Account",
                            "url": "/services/data/v59.0/sobjects/Account/001abc",
                        },
                        "Id": "001abc",
                        "Name": "Acme",
                    },
                    {
                        "attributes": {"type": "Account"},
                        "Id": "001def",
                        "Name": "Foo",
                    },
                ],
            }
        )
    )
    result = connector.soql_query("SELECT Id, Name FROM Account")
    records = result["records"]
    assert [r["record_ref"] for r in records] == ["record_1", "record_2"]
    assert records[0]["Name"] == "Acme"
    assert records[0]["object_type"] == "Account"
    assert "record_id" not in records[0]
    assert result["totalSize"] == 2
    assert result["done"] is True


def test_salesforce_soql_query_include_ids_exposes_id() -> None:
    connector, transport = _salesforce()
    transport.enqueue(
        json_response(
            {
                "totalSize": 1,
                "done": True,
                "records": [{"attributes": {"type": "Account"}, "Id": "001abc", "Name": "Acme"}],
            }
        )
    )
    result = connector.soql_query("SELECT Id, Name FROM Account", include_ids=True)
    assert result["records"][0]["record_id"] == "001abc"


def test_salesforce_update_record_tolerates_summary_dict() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response({}))
    summary = {"record_ref": "record_1", "record_id": "001abc"}
    connector.update_record("Account", summary, {"Name": "Acme"})
    assert transport.requests[0].url.endswith("/sobjects/Account/001abc")


def test_salesforce_composite_delete_tolerates_summary_dicts() -> None:
    connector, transport = _salesforce()
    transport.enqueue(json_response([]))
    summaries = [{"record_id": "001a"}, {"record_id": "001b"}]
    connector.composite_sobjects_delete(summaries)
    assert transport.requests[0].params["ids"] == "001a,001b"
