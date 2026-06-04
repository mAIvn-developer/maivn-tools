# pyright: strict
from __future__ import annotations

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.airtable import AirtableToolSet
from maivn_tools.connectors.confluence import ConfluenceToolSet
from maivn_tools.connectors.notion import NotionToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Notion


def _notion() -> tuple[NotionToolSet, MockTransport]:
    transport = MockTransport()
    return NotionToolSet(token="secret-token", transport=transport), transport


def test_notion_requires_token() -> None:
    with pytest.raises(ValueError):
        NotionToolSet(token="")
    with pytest.raises(ValueError):
        NotionToolSet(token="t", notion_version="")


def test_notion_get_self_sets_version_header() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"object": "user"}))
    connector.get_self()
    request = transport.requests[0]
    assert request.url.endswith("/v1/users/me")
    assert request.headers["Notion-Version"] == "2022-06-28"
    assert request.headers["Authorization"] == "Bearer secret-token"


def test_notion_get_user_validates() -> None:
    connector, _ = _notion()
    with pytest.raises(ValueError):
        connector.get_user("")


def test_notion_list_users_validates_page_size() -> None:
    connector, transport = _notion()
    with pytest.raises(ValueError):
        connector.list_users(page_size=0)
    transport.enqueue(json_response({"results": []}))
    connector.list_users(start_cursor="cursor", page_size=10)
    assert transport.requests[0].params == {"page_size": 10, "start_cursor": "cursor"}


def test_notion_search_validates_filters() -> None:
    connector, transport = _notion()
    with pytest.raises(ValueError):
        connector.search(filter_type="bogus")
    with pytest.raises(ValueError):
        connector.search(sort_direction="bogus")
    transport.enqueue(json_response({"results": []}))
    connector.search("hello", filter_type="page", sort_direction="ascending")
    body = transport.requests[0].json_body
    assert body["query"] == "hello"
    assert body["filter"]["value"] == "page"
    assert body["sort"]["direction"] == "ascending"


def test_notion_get_page_and_property() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"object": "page"}))
    transport.enqueue(json_response({"object": "property_item"}))
    connector.get_page("p-1")
    connector.get_page_property("p-1", "prop-1", start_cursor="cur")
    assert transport.requests[0].url.endswith("/v1/pages/p-1")
    assert transport.requests[1].url.endswith("/v1/pages/p-1/properties/prop-1")
    with pytest.raises(ValueError):
        connector.get_page("")
    with pytest.raises(ValueError):
        connector.get_page_property("", "x")


def test_notion_create_page() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"id": "p-2"}))
    connector.create_page(
        parent={"database_id": "db-1"},
        properties={"Name": {"title": [{"text": {"content": "Hi"}}]}},
        children=[{"type": "paragraph"}],
        icon={"emoji": "📝"},
    )
    body = transport.requests[0].json_body
    assert body["parent"] == {"database_id": "db-1"}
    assert body["children"]
    with pytest.raises(ValueError):
        connector.create_page(parent={}, properties={})


def test_notion_update_page_requires_field() -> None:
    connector, transport = _notion()
    with pytest.raises(ValueError):
        connector.update_page("p-1")
    transport.enqueue(json_response({"id": "p-1"}))
    connector.update_page("p-1", archived=True)
    assert transport.requests[0].json_body == {"archived": True}


def test_notion_archive_page() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"id": "p-1", "archived": True}))
    connector.archive_page("p-1")
    assert transport.requests[0].json_body == {"archived": True}
    with pytest.raises(ValueError):
        connector.archive_page("")


def test_notion_databases() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"id": "db-1"}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "db-2"}))
    transport.enqueue(json_response({"id": "db-1"}))
    connector.get_database("db-1")
    connector.query_database("db-1", filter={"property": "Name"}, sorts=[{"property": "Name"}])
    connector.create_database(
        parent={"page_id": "p-1"},
        title=[{"text": {"content": "Db"}}],
        properties={"Name": {"title": {}}},
    )
    connector.update_database("db-1", title=[{"text": {"content": "x"}}])
    with pytest.raises(ValueError):
        connector.get_database("")
    with pytest.raises(ValueError):
        connector.query_database("", filter=None)
    with pytest.raises(ValueError):
        connector.create_database(parent={}, title=[], properties={})
    with pytest.raises(ValueError):
        connector.update_database("db-1")


def test_notion_blocks() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"id": "b-1"}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": [{"id": "b-2"}]}))
    transport.enqueue(json_response({"id": "b-1"}))
    transport.enqueue(json_response({"id": "b-1", "archived": True}))
    connector.get_block("b-1")
    connector.list_block_children("b-1", page_size=5)
    connector.append_block_children("b-1", [{"type": "paragraph"}], after="b-0")
    connector.update_block("b-1", {"paragraph": {"rich_text": []}})
    connector.delete_block("b-1")
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_block("")
    with pytest.raises(ValueError):
        connector.list_block_children("")
    with pytest.raises(ValueError):
        connector.append_block_children("b-1", [])
    with pytest.raises(ValueError):
        connector.update_block("b-1", {})


def test_notion_comments() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "c-1"}))
    connector.list_comments("b-1")
    connector.create_comment(parent={"page_id": "p-1"}, rich_text=[{"text": {"content": "hi"}}])
    assert transport.requests[0].params["block_id"] == "b-1"
    with pytest.raises(ValueError):
        connector.list_comments("")
    with pytest.raises(ValueError):
        connector.create_comment(rich_text=[{"text": {"content": "hi"}}])
    with pytest.raises(ValueError):
        connector.create_comment(parent={"page_id": "p-1"}, rich_text=[])


# MARK: - Confluence


def _confluence() -> tuple[ConfluenceToolSet, MockTransport]:
    transport = MockTransport()
    return (
        ConfluenceToolSet(
            base_url="https://acme.atlassian.net",
            email="ops@example.test",
            api_token="api-token",
            transport=transport,
        ),
        transport,
    )


def test_confluence_validates_inputs() -> None:
    with pytest.raises(ValueError):
        ConfluenceToolSet(base_url="", email="x", api_token="t")
    with pytest.raises(ValueError):
        ConfluenceToolSet(base_url="https://x", email="", api_token="t")
    with pytest.raises(ValueError):
        ConfluenceToolSet(base_url="https://x", email="x", api_token="")


def test_confluence_appends_wiki_prefix() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"accountId": "u"}))
    connector.get_current_user()
    assert "/wiki/rest/api/user/current" in transport.requests[0].url


def test_confluence_user_lookup() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"accountId": "u-1"}))
    connector.get_user("u-1")
    assert transport.requests[0].params == {"accountId": "u-1"}
    with pytest.raises(ValueError):
        connector.get_user("")


def test_confluence_spaces() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"key": "ENG"}))
    transport.enqueue(json_response({"key": "OPS"}))
    transport.enqueue(json_response({"taskId": "1"}))
    connector.list_spaces(space_key=["ENG"], type="global", limit=10)
    connector.get_space("ENG")
    connector.create_space(key="OPS", name="Ops", description="An ops space", private=True)
    connector.delete_space("OPS")
    assert transport.requests[0].params["spaceKey"] == ["ENG"]
    assert transport.requests[2].url.endswith("/rest/api/space/_private")
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_spaces(limit=0)
    with pytest.raises(ValueError):
        connector.get_space("")
    with pytest.raises(ValueError):
        connector.create_space(key="", name="x")
    with pytest.raises(ValueError):
        connector.delete_space("")


def test_confluence_content_lifecycle() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "p-1"}))
    transport.enqueue(json_response({"id": "p-2"}))
    transport.enqueue(json_response({"id": "p-2", "version": {"number": 2}}))
    transport.enqueue(json_response({}))
    connector.list_content(type="page", space_key="ENG", title="Hello", expand="body.storage")
    connector.get_content("p-1", expand="body.storage", version=1)
    connector.create_page(space_key="ENG", title="Hello", body="<p>Hi</p>", parent_id="parent")
    connector.update_page("p-2", title="New", body="<p>New</p>", version=2)
    connector.delete_content("p-2")
    assert transport.requests[2].json_body["space"] == {"key": "ENG"}
    assert transport.requests[3].method == "PUT"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_content(type="bogus")
    with pytest.raises(ValueError):
        connector.get_content("")
    with pytest.raises(ValueError):
        connector.create_page(space_key="", title="x", body="x")
    with pytest.raises(ValueError):
        connector.create_page(space_key="ENG", title="x", body="x", representation="bogus")
    with pytest.raises(ValueError):
        connector.update_page("", title="x", body="x", version=1)
    with pytest.raises(ValueError):
        connector.delete_content("")


def test_confluence_children_versions_labels() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": [{"name": "x"}]}))
    transport.enqueue(json_response({}))
    connector.list_children("p-1", type="page")
    connector.list_versions("p-1")
    connector.list_labels("p-1")
    connector.add_label("p-1", "tag")
    connector.remove_label("p-1", "tag")
    assert transport.requests[3].json_body == [{"prefix": "global", "name": "tag"}]
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_children("")
    with pytest.raises(ValueError):
        connector.list_versions("")
    with pytest.raises(ValueError):
        connector.list_labels("")
    with pytest.raises(ValueError):
        connector.add_label("", "tag")
    with pytest.raises(ValueError):
        connector.remove_label("p-1", "")


def test_confluence_comments_and_search() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"id": "c-1"}))
    transport.enqueue(json_response({"results": []}))
    transport.enqueue(json_response({"results": []}))
    connector.list_comments("p-1", location="footer", depth="all")
    connector.create_comment(container_id="p-1", body="<p>hi</p>")
    connector.search("type = page AND space = ENG")
    connector.search_content("type = page", expand="body.storage")
    assert transport.requests[0].params["location"] == "footer"
    assert transport.requests[1].json_body["type"] == "comment"
    assert transport.requests[2].url.endswith("/rest/api/search")
    assert transport.requests[3].url.endswith("/rest/api/content/search")
    with pytest.raises(ValueError):
        connector.list_comments("")
    with pytest.raises(ValueError):
        connector.create_comment(container_id="", body="x")
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.search_content("")


def test_confluence_attachments() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"results": []}))
    connector.list_attachments("p-1", media_type="image/png", filename="x.png")
    assert transport.requests[0].params["mediaType"] == "image/png"
    with pytest.raises(ValueError):
        connector.list_attachments("")


# MARK: - Airtable


def _airtable() -> tuple[AirtableToolSet, MockTransport]:
    transport = MockTransport()
    return AirtableToolSet(access_token="pat123", transport=transport), transport


def test_airtable_requires_token() -> None:
    with pytest.raises(ValueError):
        AirtableToolSet(access_token="")


def test_airtable_meta() -> None:
    connector, transport = _airtable()
    for _ in range(5):
        transport.enqueue(json_response({"bases": []}))
    connector.list_bases(offset="cur")
    connector.get_base_schema("app1", include=["visibleFieldIds"])
    connector.create_table(
        "app1",
        name="Tasks",
        fields=[{"name": "Title", "type": "singleLineText"}],
        description="Task list",
    )
    connector.create_field(
        base_id="app1",
        table_id="tbl1",
        name="Owner",
        field_type="singleCollaborator",
        options={"choices": []},
        description="Assignee",
    )
    connector.get_current_user()
    assert transport.requests[0].headers["Authorization"] == "Bearer pat123"
    assert transport.requests[1].url.endswith("/v0/meta/bases/app1/tables")
    with pytest.raises(ValueError):
        connector.get_base_schema("")
    with pytest.raises(ValueError):
        connector.create_table("", name="x", fields=[{}])
    with pytest.raises(ValueError):
        connector.create_table("a", name="", fields=[{}])
    with pytest.raises(ValueError):
        connector.create_table("a", name="x", fields=[])
    with pytest.raises(ValueError):
        connector.create_field(
            base_id="",
            table_id="t",
            name="x",
            field_type="y",
        )
    with pytest.raises(ValueError):
        connector.create_field(
            base_id="a",
            table_id="t",
            name="",
            field_type="y",
        )


def test_airtable_records() -> None:
    connector, transport = _airtable()
    for _ in range(5):
        transport.enqueue(json_response({"records": []}))
    connector.list_records(
        base_id="app1",
        table_id_or_name="Tasks",
        view="Grid",
        fields=["Title", "Owner"],
        filter_by_formula="{Status}='Open'",
        sort=[{"field": "Title", "direction": "asc"}],
        max_records=100,
        page_size=50,
        offset="rec123",
        cell_format="json",
        time_zone="UTC",
        user_locale="en-us",
        return_fields_by_field_id=True,
    )
    connector.get_record(
        base_id="app1",
        table_id_or_name="Tasks",
        record_id="rec1",
    )
    connector.create_records(
        base_id="app1",
        table_id_or_name="Tasks",
        records=[{"fields": {"Title": "Hello"}}],
        typecast=True,
        return_fields_by_field_id=False,
    )
    connector.update_records(
        base_id="app1",
        table_id_or_name="Tasks",
        records=[{"id": "rec1", "fields": {"Title": "Bye"}}],
        typecast=True,
        replace=False,
    )
    connector.update_records(
        base_id="app1",
        table_id_or_name="Tasks",
        records=[{"fields": {"Title": "Up"}}],
        replace=True,
        perform_upsert={"fieldsToMergeOn": ["Title"]},
    )
    assert transport.requests[0].params["sort[0][field]"] == "Title"
    assert transport.requests[0].params["filterByFormula"] == "{Status}='Open'"
    assert transport.requests[3].method == "PATCH"
    assert transport.requests[4].method == "PUT"
    with pytest.raises(ValueError):
        connector.list_records(base_id="", table_id_or_name="x")
    with pytest.raises(ValueError):
        connector.list_records(
            base_id="a",
            table_id_or_name="x",
            cell_format="bogus",
        )
    with pytest.raises(ValueError):
        connector.get_record(
            base_id="",
            table_id_or_name="x",
            record_id="r",
        )
    with pytest.raises(ValueError):
        connector.create_records(
            base_id="",
            table_id_or_name="x",
            records=[{"fields": {}}],
        )
    with pytest.raises(ValueError):
        connector.create_records(
            base_id="a",
            table_id_or_name="x",
            records=[],
        )
    with pytest.raises(ValueError):
        connector.create_records(
            base_id="a",
            table_id_or_name="x",
            records=[{"fields": {}}] * 11,
        )
    with pytest.raises(ValueError):
        connector.update_records(
            base_id="",
            table_id_or_name="x",
            records=[{"id": "r"}],
        )
    with pytest.raises(ValueError):
        connector.update_records(
            base_id="a",
            table_id_or_name="x",
            records=[{"id": "r"}] * 11,
        )


def test_airtable_delete_records() -> None:
    connector, transport = _airtable()
    transport.enqueue(json_response({"records": []}))
    connector.delete_records(
        base_id="app1",
        table_id_or_name="Tasks",
        record_ids=["rec1", "rec2"],
    )
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[0].params["records[]"] == ["rec1", "rec2"]
    with pytest.raises(ValueError):
        connector.delete_records(
            base_id="",
            table_id_or_name="x",
            record_ids=["r"],
        )
    with pytest.raises(ValueError):
        connector.delete_records(
            base_id="a",
            table_id_or_name="x",
            record_ids=[],
        )
    with pytest.raises(ValueError):
        connector.delete_records(
            base_id="a",
            table_id_or_name="x",
            record_ids=["r"] * 11,
        )


def test_airtable_comments() -> None:
    connector, transport = _airtable()
    for _ in range(3):
        transport.enqueue(json_response({"id": "com1"}))
    connector.list_comments(
        base_id="app1",
        table_id_or_name="Tasks",
        record_id="rec1",
        page_size=10,
        offset="cur",
    )
    connector.create_comment(
        base_id="app1",
        table_id_or_name="Tasks",
        record_id="rec1",
        text="Looks good",
    )
    connector.delete_comment(
        base_id="app1",
        table_id_or_name="Tasks",
        record_id="rec1",
        comment_id="com1",
    )
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_comments(
            base_id="",
            table_id_or_name="x",
            record_id="r",
        )
    with pytest.raises(ValueError):
        connector.create_comment(
            base_id="",
            table_id_or_name="x",
            record_id="r",
            text="t",
        )
    with pytest.raises(ValueError):
        connector.create_comment(
            base_id="a",
            table_id_or_name="x",
            record_id="r",
            text="",
        )
    with pytest.raises(ValueError):
        connector.delete_comment(
            base_id="",
            table_id_or_name="x",
            record_id="r",
            comment_id="c",
        )


def test_airtable_webhooks() -> None:
    connector, transport = _airtable()
    for _ in range(4):
        transport.enqueue(json_response({"webhooks": []}))
    connector.list_webhooks("app1")
    connector.create_webhook(
        "app1",
        notification_url="https://example.com/hook",
        specification={"options": {"filters": {}}},
    )
    connector.delete_webhook(base_id="app1", webhook_id="hook1")
    connector.list_webhook_payloads(
        base_id="app1",
        webhook_id="hook1",
        cursor=1,
        limit=10,
    )
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_webhooks("")
    with pytest.raises(ValueError):
        connector.create_webhook(
            "",
            notification_url="u",
            specification={"x": 1},
        )
    with pytest.raises(ValueError):
        connector.create_webhook(
            "a",
            notification_url="",
            specification={"x": 1},
        )
    with pytest.raises(ValueError):
        connector.delete_webhook(base_id="", webhook_id="w")
    with pytest.raises(ValueError):
        connector.list_webhook_payloads(base_id="a", webhook_id="")


# MARK: - Agent-ready behavior: Notion


def test_notion_search_returns_summaries_by_default() -> None:
    connector, transport = _notion()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "object": "page",
                        "id": "page-uuid-1",
                        "url": "https://www.notion.so/page-uuid-1",
                        "last_edited_time": "2026-05-01T10:00:00Z",
                        "parent": {"type": "database_id", "database_id": "db-1"},
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": [{"plain_text": "Project Plan"}],
                            }
                        },
                    },
                    {
                        "object": "database",
                        "id": "db-uuid-1",
                        "url": "https://www.notion.so/db-uuid-1",
                        "title": [{"plain_text": "Projects DB"}],
                        "last_edited_time": "2026-04-01T10:00:00Z",
                    },
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )
    )
    result = connector.search("plan")
    page_summary = result["results"][0]
    db_summary = result["results"][1]
    assert page_summary["page_ref"] == "page_1"
    assert page_summary["title"] == "Project Plan"
    assert page_summary["object"] == "page"
    assert "page_id" not in page_summary
    assert db_summary["result_ref"] == "result_2"
    assert db_summary["title"] == "Projects DB"
    assert result["has_more"] is False


def test_notion_search_include_ids_exposes_uuid() -> None:
    connector, transport = _notion()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "object": "page",
                        "id": "page-uuid-1",
                        "url": "x",
                        "properties": {},
                    }
                ]
            }
        )
    )
    result = connector.search("x", include_ids=True)
    assert result["results"][0]["page_id"] == "page-uuid-1"


def test_notion_search_raw_mode_returns_provider_payload() -> None:
    connector, transport = _notion()
    raw = {"results": [{"object": "page", "id": "p1"}], "has_more": False}
    transport.enqueue(json_response(raw))
    result = connector.search("x", include_metadata=False)
    assert result == raw


def test_notion_query_database_returns_page_summaries() -> None:
    connector, transport = _notion()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "object": "page",
                        "id": "page-1",
                        "url": "https://www.notion.so/page-1",
                        "last_edited_time": "2026-05-01T00:00:00Z",
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": [{"plain_text": "Row 1"}],
                            }
                        },
                    }
                ]
            }
        )
    )
    result = connector.query_database("db-1")
    assert result["results"][0]["page_ref"] == "page_1"
    assert result["results"][0]["title"] == "Row 1"
    assert "page_id" not in result["results"][0]


def test_notion_update_page_tolerates_summary_dict() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"id": "p-1"}))
    summary = {"page_ref": "page_1", "page_id": "p-1"}
    connector.update_page(summary, archived=True)
    assert transport.requests[0].url.endswith("/v1/pages/p-1")
    assert transport.requests[0].json_body == {"archived": True}


def test_notion_archive_page_tolerates_list() -> None:
    connector, transport = _notion()
    transport.enqueue(json_response({"id": "p-1", "archived": True}))
    summaries = [{"page_ref": "page_1", "page_id": "p-1"}]
    connector.archive_page(summaries)
    assert transport.requests[0].url.endswith("/v1/pages/p-1")


def test_notion_destructive_tools_are_tagged() -> None:
    connector, _ = _notion()
    for method in (connector.archive_page, connector.delete_block):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - Agent-ready behavior: Confluence


def test_confluence_list_content_returns_summaries_by_default() -> None:
    connector, transport = _confluence()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "111",
                        "type": "page",
                        "status": "current",
                        "title": "Runbook",
                        "space": {"key": "ENG"},
                        "version": {"number": 3},
                        "_links": {"webui": "/spaces/ENG/pages/111/Runbook"},
                    }
                ],
                "start": 0,
                "limit": 25,
                "size": 1,
            }
        )
    )
    result = connector.list_content(space_key="ENG")
    summary = result["results"][0]
    assert summary["page_ref"] == "page_1"
    assert summary["title"] == "Runbook"
    assert summary["space_key"] == "ENG"
    assert summary["version"] == 3
    assert "content_id" not in summary
    assert result["size"] == 1


def test_confluence_list_content_include_ids_exposes_content_id() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"results": [{"id": "111", "type": "page", "title": "x"}]}))
    result = connector.list_content(include_ids=True)
    assert result["results"][0]["content_id"] == "111"


def test_confluence_list_content_raw_mode() -> None:
    connector, transport = _confluence()
    raw = {"results": [{"id": "111", "title": "x"}], "size": 1}
    transport.enqueue(json_response(raw))
    result = connector.list_content(include_metadata=False)
    assert result == raw


def test_confluence_search_returns_summaries_with_excerpt() -> None:
    connector, transport = _confluence()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "content": {
                            "id": "222",
                            "type": "page",
                            "title": "Onboarding",
                            "space": {"key": "ENG"},
                            "_links": {"webui": "/spaces/ENG/pages/222"},
                        },
                        "excerpt": "Welcome to the team...",
                        "resultGlobalContainer": "ENG",
                    }
                ],
                "size": 1,
            }
        )
    )
    result = connector.search("type = page")
    summary = result["results"][0]
    assert summary["page_ref"] == "page_1"
    assert summary["title"] == "Onboarding"
    assert summary["excerpt"] == "Welcome to the team..."
    assert "content_id" not in summary


def test_confluence_update_page_tolerates_summary_dict() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({"id": "111"}))
    summary = {"page_ref": "page_1", "content_id": "111"}
    connector.update_page(summary, title="New", body="<p>body</p>", version=2)
    assert transport.requests[0].url.endswith("/rest/api/content/111")
    assert transport.requests[0].method == "PUT"


def test_confluence_delete_content_tolerates_list() -> None:
    connector, transport = _confluence()
    transport.enqueue(json_response({}))
    summaries = [{"page_ref": "page_1", "content_id": "111"}]
    connector.delete_content(summaries)
    assert transport.requests[0].url.endswith("/rest/api/content/111")


def test_confluence_destructive_tools_are_tagged() -> None:
    connector, _ = _confluence()
    for method in (connector.delete_content, connector.delete_space, connector.remove_label):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - Agent-ready behavior: Airtable


def test_airtable_list_records_returns_summaries_by_default() -> None:
    connector, transport = _airtable()
    transport.enqueue(
        json_response(
            {
                "records": [
                    {
                        "id": "rec1",
                        "fields": {"Title": "Hello", "Status": "Open"},
                        "createdTime": "2026-05-01T10:00:00Z",
                    },
                    {
                        "id": "rec2",
                        "fields": {"Title": "World", "Status": "Closed"},
                        "createdTime": "2026-05-02T10:00:00Z",
                    },
                ]
            }
        )
    )
    result = connector.list_records(base_id="app1", table_id_or_name="Tasks")
    records = result["records"]
    assert [r["record_ref"] for r in records] == ["record_1", "record_2"]
    assert records[0]["fields"]["Title"] == "Hello"
    assert "record_id" not in records[0]


def test_airtable_list_records_include_ids_exposes_record_id() -> None:
    connector, transport = _airtable()
    transport.enqueue(json_response({"records": [{"id": "rec1", "fields": {"Title": "Hello"}}]}))
    result = connector.list_records(
        base_id="app1",
        table_id_or_name="Tasks",
        include_ids=True,
    )
    assert result["records"][0]["record_id"] == "rec1"


def test_airtable_list_records_raw_mode_returns_provider_payload() -> None:
    connector, transport = _airtable()
    raw = {"records": [{"id": "rec1", "fields": {"x": 1}}], "offset": "cur"}
    transport.enqueue(json_response(raw))
    result = connector.list_records(
        base_id="app1",
        table_id_or_name="Tasks",
        include_metadata=False,
    )
    assert result == raw


def test_airtable_delete_records_tolerates_summary_dicts() -> None:
    connector, transport = _airtable()
    transport.enqueue(json_response({"records": []}))
    summaries = [
        {"record_ref": "record_1", "record_id": "rec1"},
        {"record_ref": "record_2", "record_id": "rec2"},
    ]
    connector.delete_records(
        base_id="app1",
        table_id_or_name="Tasks",
        record_ids=summaries,
    )
    assert transport.requests[0].params["records[]"] == ["rec1", "rec2"]


def test_airtable_delete_records_tolerates_mixed_inputs() -> None:
    connector, transport = _airtable()
    transport.enqueue(json_response({"records": []}))
    mixed = ["rec1", {"id": "rec2"}, [{"record_id": "rec3"}]]
    connector.delete_records(
        base_id="app1",
        table_id_or_name="Tasks",
        record_ids=mixed,
    )
    assert transport.requests[0].params["records[]"] == ["rec1", "rec2", "rec3"]


def test_airtable_destructive_tools_are_tagged() -> None:
    connector, _ = _airtable()
    for method in (
        connector.delete_records,
        connector.delete_comment,
        connector.delete_webhook,
    ):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True
