# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.box import BoxToolSet
from maivn_tools.connectors.dropbox import DropboxToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Box


def _box() -> tuple[BoxToolSet, MockTransport]:
    transport = MockTransport()
    return BoxToolSet(token="t", transport=transport), transport


def test_box_requires_token() -> None:
    with pytest.raises(ValueError):
        BoxToolSet(token="")


def test_box_users() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({"id": "1"}))
    transport.enqueue(json_response({"id": "2"}))
    connector.get_current_user()
    connector.get_user("2")
    assert transport.requests[0].url.endswith("/2.0/users/me")
    assert transport.requests[1].url.endswith("/2.0/users/2")
    with pytest.raises(ValueError):
        connector.get_user("")


def test_box_folder_lifecycle() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({"id": "0"}))
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({"id": "100"}))
    transport.enqueue(json_response({"id": "100", "name": "x"}))
    transport.enqueue(json_response({"id": "200"}))
    transport.enqueue(json_response({}))
    connector.get_folder()
    connector.list_folder_items(folder_id="0", fields=["name", "size"])
    connector.create_folder("Reports")
    connector.update_folder("100", name="Reports2")
    connector.copy_folder("100", parent_id="0", name="copy")
    connector.delete_folder("100", recursive=True)
    assert transport.requests[1].params["fields"] == "name,size"
    assert transport.requests[2].json_body["parent"] == {"id": "0"}
    assert transport.requests[3].method == "PUT"
    assert transport.requests[5].method == "DELETE"
    assert transport.requests[5].params == {"recursive": "true"}
    with pytest.raises(ValueError):
        connector.get_folder("")
    with pytest.raises(ValueError):
        connector.create_folder("")
    with pytest.raises(ValueError):
        connector.update_folder("100")
    with pytest.raises(ValueError):
        connector.delete_folder("")
    with pytest.raises(ValueError):
        connector.copy_folder("100", parent_id="")


def test_box_file_ops() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({"id": "f1"}))
    transport.enqueue(json_response({"id": "f1", "name": "new"}))
    transport.enqueue(json_response({"id": "f1-copy"}))
    transport.enqueue(json_response({"download_url": "https://"}))
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({}))
    connector.get_file("f1", fields=["name"])
    connector.update_file("f1", name="new")
    connector.copy_file("f1", parent_id="0", name="copy")
    connector.get_file_download_url("f1")
    connector.list_file_versions("f1")
    connector.delete_file("f1")
    assert transport.requests[3].params["fields"] == "download_url"
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_file("")
    with pytest.raises(ValueError):
        connector.update_file("f1")
    with pytest.raises(ValueError):
        connector.copy_file("", parent_id="0")
    with pytest.raises(ValueError):
        connector.delete_file("")


def test_box_search_and_share() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({"id": "col1"}))
    transport.enqueue(json_response({"id": "f1", "shared_link": {"access": "open"}}))
    transport.enqueue(json_response({}))
    connector.search("budget", type="file", file_extensions=["xlsx", "csv"])
    connector.list_collaborations(item_id="f1", item_type="file")
    connector.create_collaboration(
        item_id="f1",
        item_type="file",
        accessible_by_login="x@example.com",
        role="viewer",
    )
    connector.create_shared_link(item_id="f1", item_type="file", access="open")
    connector.delete_collaboration("col1")
    assert transport.requests[0].params["file_extensions"] == "xlsx,csv"
    assert transport.requests[3].json_body["shared_link"]["access"] == "open"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.list_collaborations(item_id="x", item_type="bogus")
    with pytest.raises(ValueError):
        connector.create_collaboration(item_id="x", item_type="bogus", role="viewer")
    with pytest.raises(ValueError):
        connector.create_collaboration(item_id="x", item_type="file", role="")
    with pytest.raises(ValueError):
        connector.create_collaboration(item_id="x", item_type="file", role="viewer")
    with pytest.raises(ValueError):
        connector.create_shared_link(item_id="x", item_type="file", access="bogus")
    with pytest.raises(ValueError):
        connector.delete_collaboration("")


def test_box_trash() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({}))
    connector.list_trash()
    connector.permanently_delete(item_id="f1", item_type="file")
    assert transport.requests[1].url.endswith("/2.0/files/f1/trash")
    with pytest.raises(NotImplementedError):
        connector.empty_trash()
    with pytest.raises(ValueError):
        connector.permanently_delete(item_id="x", item_type="bogus")
    with pytest.raises(ValueError):
        connector.permanently_delete(item_id="", item_type="file")


def test_box_search_returns_summaries_without_raw_ids() -> None:
    connector, transport = _box()
    transport.enqueue(
        json_response(
            {
                "entries": [
                    {
                        "id": "raw-1",
                        "type": "file",
                        "name": "budget.xlsx",
                        "size": 9000,
                        "modified_at": "2026-05-16T09:00:00Z",
                        "owned_by": {"name": "Alice"},
                    },
                    {
                        "id": "raw-2",
                        "type": "folder",
                        "name": "Reports",
                        "modified_at": "2026-05-10T09:00:00Z",
                        "owned_by": {"login": "bob@x.test"},
                    },
                ]
            }
        )
    )
    result = connector.search("budget")
    items = result["items"]
    assert items[0]["file_ref"] == "file_1"
    assert items[0]["name"] == "budget.xlsx"
    assert "file_id" not in items[0]
    assert items[1]["folder_ref"] == "folder_2"
    assert "folder_id" not in items[1]


def test_box_search_include_ids_exposes_raw_ids() -> None:
    connector, transport = _box()
    transport.enqueue(
        json_response(
            {"entries": [{"id": "raw-1", "type": "file", "name": "x", "modified_at": "t"}]}
        )
    )
    result = connector.search("x", include_ids=True)
    assert result["items"][0]["file_id"] == "raw-1"


def test_box_list_folder_items_returns_summaries() -> None:
    connector, transport = _box()
    transport.enqueue(
        json_response(
            {
                "entries": [
                    {
                        "id": "raw-1",
                        "type": "file",
                        "name": "report.docx",
                        "size": 1234,
                        "modified_at": "2026-05-16T09:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_folder_items()
    assert result["items"][0]["file_ref"] == "file_1"


def test_box_delete_file_accepts_dict_input() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({}))
    connector.delete_file({"file_id": "raw-1", "name": "x"})
    assert transport.requests[0].method == "DELETE"
    assert transport.requests[0].url.endswith("/2.0/files/raw-1")


def test_box_update_file_accepts_dict_input() -> None:
    connector, transport = _box()
    transport.enqueue(json_response({"id": "raw-1"}))
    connector.update_file({"file_id": "raw-1"}, name="new.txt")
    assert transport.requests[0].method == "PUT"
    assert transport.requests[0].url.endswith("/2.0/files/raw-1")


def test_box_delete_folder_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, transport = _box()
    transport.enqueue(json_response({}))
    opts = get_toolify_options(connector.delete_folder)
    assert opts is not None and opts.destructive is True
    connector.delete_folder("100")


def test_box_permanently_delete_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _box()
    opts = get_toolify_options(connector.permanently_delete)
    assert opts is not None and opts.destructive is True


# MARK: - Dropbox


def _dropbox() -> tuple[DropboxToolSet, MockTransport]:
    transport = MockTransport()
    return DropboxToolSet(token="t", transport=transport), transport


def test_dropbox_requires_token() -> None:
    with pytest.raises(ValueError):
        DropboxToolSet(token="")


def test_dropbox_identity() -> None:
    connector, transport = _dropbox()
    transport.enqueue(json_response({"account_id": "a"}))
    transport.enqueue(json_response({"used": 0}))
    connector.get_current_account()
    connector.get_space_usage()
    assert transport.requests[0].url.endswith("/2/users/get_current_account")
    assert transport.requests[0].method == "POST"


def test_dropbox_list_and_search() -> None:
    connector, transport = _dropbox()
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({"entries": []}))
    transport.enqueue(json_response({"matches": []}))
    transport.enqueue(json_response({"link": "https://"}))
    connector.list_folder("/Project")
    connector.list_folder_continue("cur-1")
    connector.get_metadata("/Project/spec.md", include_deleted=True)
    connector.search("budget", path="/Project", max_results=50)
    connector.get_temporary_link("/Project/spec.md")
    assert transport.requests[0].json_body["path"] == "/Project"
    assert transport.requests[1].json_body["cursor"] == "cur-1"
    assert transport.requests[3].json_body["options"]["path"] == "/Project"
    with pytest.raises(ValueError):
        connector.list_folder_continue("")
    with pytest.raises(ValueError):
        connector.get_metadata("")
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.search("x", max_results=0)
    with pytest.raises(ValueError):
        connector.get_temporary_link("")


def test_dropbox_mutations() -> None:
    connector, transport = _dropbox()
    for _ in range(6):
        transport.enqueue(json_response({"metadata": {}}))
    connector.create_folder("/New")
    connector.move(from_path="/a", to_path="/b")
    connector.copy(from_path="/a", to_path="/c")
    connector.delete("/a")
    connector.restore(path="/a", rev="rev1")
    connector.list_revisions("/a", limit=5)
    assert transport.requests[0].url.endswith("/2/files/create_folder_v2")
    assert transport.requests[5].json_body["mode"] == "path"
    with pytest.raises(ValueError):
        connector.create_folder("")
    with pytest.raises(ValueError):
        connector.move(from_path="", to_path="/b")
    with pytest.raises(ValueError):
        connector.copy(from_path="", to_path="/b")
    with pytest.raises(ValueError):
        connector.delete("")
    with pytest.raises(ValueError):
        connector.restore(path="", rev="r")
    with pytest.raises(ValueError):
        connector.list_revisions("")


def test_dropbox_sharing_and_file_requests() -> None:
    connector, transport = _dropbox()
    transport.enqueue(json_response({"url": "https://x"}))
    transport.enqueue(json_response({"links": []}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"file_requests": []}))
    transport.enqueue(json_response({"id": "fr-1"}))
    connector.create_shared_link("/x", require_password=True, link_password="abc")
    connector.list_shared_links(path="/x")
    connector.revoke_shared_link("https://x")
    connector.list_file_requests()
    connector.create_file_request(
        title="Send invoices",
        destination="/inbox",
        deadline_iso="2026-06-01T00:00:00Z",
    )
    assert transport.requests[0].json_body["settings"]["require_password"] is True
    assert transport.requests[4].json_body["deadline"] == {"deadline": "2026-06-01T00:00:00Z"}
    with pytest.raises(ValueError):
        connector.create_shared_link("")
    with pytest.raises(ValueError):
        connector.revoke_shared_link("")
    with pytest.raises(ValueError):
        connector.create_file_request(title="", destination="/x")


def test_dropbox_list_folder_returns_summaries_without_raw_ids() -> None:
    connector, transport = _dropbox()
    transport.enqueue(
        json_response(
            {
                "entries": [
                    {
                        ".tag": "file",
                        "name": "spec.md",
                        "path_display": "/Project/spec.md",
                        "id": "id:abc",
                        "size": 4567,
                        "server_modified": "2026-05-16T09:00:00Z",
                        "rev": "rev1",
                    },
                    {
                        ".tag": "folder",
                        "name": "Drafts",
                        "path_display": "/Project/Drafts",
                        "id": "id:def",
                    },
                ]
            }
        )
    )
    result = connector.list_folder("/Project")
    items = result["items"]
    assert items[0]["file_ref"] == "file_1"
    assert items[0]["name"] == "spec.md"
    assert items[0]["path"] == "/Project/spec.md"
    # Dropbox 'id' is included only with include_ids=True
    assert "id" not in items[0]
    assert items[1]["folder_ref"] == "folder_2"


def test_dropbox_list_folder_include_ids() -> None:
    connector, transport = _dropbox()
    transport.enqueue(
        json_response(
            {
                "entries": [
                    {
                        ".tag": "file",
                        "name": "x",
                        "path_display": "/x",
                        "id": "id:abc",
                        "rev": "rev1",
                    }
                ]
            }
        )
    )
    result = connector.list_folder("/Project", include_ids=True)
    assert result["items"][0]["id"] == "id:abc"
    assert result["items"][0]["rev"] == "rev1"


def test_dropbox_list_folder_raw_mode_returns_provider_payload() -> None:
    connector, transport = _dropbox()
    transport.enqueue(json_response({"entries": [{"name": "x"}]}))
    result = connector.list_folder("/Project", include_metadata=False)
    assert "entries" in result


def test_dropbox_search_returns_summaries() -> None:
    connector, transport = _dropbox()
    transport.enqueue(
        json_response(
            {
                "matches": [
                    {
                        "metadata": {
                            "metadata": {
                                ".tag": "file",
                                "name": "budget.xlsx",
                                "path_display": "/x/budget.xlsx",
                                "id": "id:1",
                                "size": 1,
                                "server_modified": "2026-05-16T09:00:00Z",
                            }
                        }
                    }
                ]
            }
        )
    )
    result = connector.search("budget")
    assert result["items"][0]["file_ref"] == "file_1"
    assert result["items"][0]["name"] == "budget.xlsx"
    assert "id" not in result["items"][0]


def test_dropbox_delete_accepts_dict_input() -> None:
    connector, transport = _dropbox()
    transport.enqueue(json_response({"metadata": {}}))
    connector.delete({"path": "/Project/old.md"})
    assert transport.requests[0].json_body == {"path": "/Project/old.md"}


def test_dropbox_move_accepts_dict_input() -> None:
    connector, transport = _dropbox()
    transport.enqueue(json_response({"metadata": {}}))
    connector.move(from_path={"path": "/a"}, to_path="/b")
    body = transport.requests[0].json_body
    assert body["from_path"] == "/a"
    assert body["to_path"] == "/b"


def test_dropbox_delete_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _dropbox()
    opts = get_toolify_options(connector.delete)
    assert opts is not None and opts.destructive is True


def test_dropbox_revoke_shared_link_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _dropbox()
    opts = get_toolify_options(connector.revoke_shared_link)
    assert opts is not None and opts.destructive is True
